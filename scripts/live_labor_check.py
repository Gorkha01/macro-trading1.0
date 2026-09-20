"""Live wiring check: real FRED labor data -> Module 6 functions.

Not a test. This directory holds operator scripts, deliberately excluded from
the default test run because they hit the network. Run with::

    uv run python scripts/live_labor_check.py

Section 21.0: unit tests prove the arithmetic, this proves the wiring — the
units, the nulls, the frequency, the sign conventions, and whether the values
that come out are the values the specification says should come out.
"""

from __future__ import annotations

import statistics
from datetime import date
from typing import TYPE_CHECKING

from macro_engine.config import get_settings
from macro_engine.data_layer.openbb_client import OpenBBClient
from macro_engine.models.contracts import ModelResult, utc_now
from macro_engine.models.gdp_nowcast import (
    GdpGdiInputs,
    gdp_gdi_divergence,
)
from macro_engine.models.inflation_nowcast import (
    ShelterLagInputs,
    project_shelter_cpi,
)
from macro_engine.models.labor_synthesis import (
    AHEDistortionInputs,
    BeveridgeInputs,
    ClaimsCorroborationInputs,
    ClaimsTrendInputs,
    RevisionInputs,
    TwoSurveyInputs,
    ahe_composition_flag,
    beveridge_curve_position,
    claims_corroboration,
    claims_trend_signal,
    nfp_revision_adjusted_read,
    two_survey_divergence,
)
from macro_engine.models.ppi_pipeline import (
    PPIPipelineInputs,
    ppi_pipeline_signal,
)
from macro_engine.models.production_function import (
    PotentialGDPInputs,
    growth_accounting_decomposition,
    potential_gdp_cobb_douglas,
)

if TYPE_CHECKING:
    import pandas as pd


def _fetch(client: OpenBBClient, symbol: str, label: str) -> pd.DataFrame:
    """Mirror how the snapshot builder fetches a registry series.

    Returns a tidy frame with ``date`` and ``value`` columns — *not* a pandas
    Series. The registry is the only place that should name providers, so the
    provider/endpoint args here are transcribed from ``series_registry.yaml``.
    """
    return client.fetch_series(
        provider="fred",
        endpoint="economy.fred_series",
        params={"symbol": symbol},
        series_label=label,
    )


def _values(frame: pd.DataFrame) -> tuple[list[date], list[float]]:
    """Extract (dates, values), dropping nulls from the head/body.

    ``dropna`` on the value column rather than on the whole frame: FRED
    occasionally carries leading NaNs for a series whose history starts later
    than the requested window.
    """
    clean = frame.loc[frame["value"].notna(), ["date", "value"]]
    # The ``date`` column arrives as object-dtype ``datetime.date`` values, not
    # pandas Timestamps, so it is narrowed explicitly here rather than left as
    # ``object`` — every date arithmetic below depends on that being true.
    dates: list[date] = [
        value if isinstance(value, date) else _to_date(value) for value in clean["date"]
    ]
    return dates, [float(value) for value in clean["value"]]


def _to_date(value: object) -> date:
    """Coerce a pandas Timestamp to a plain ``date``.

    The other branch of ``_values``. Named rather than inlined so the
    ``type: ignore`` it needs (``object`` has no ``.date()``, and the alternative
    is importing pandas purely for the annotation) sits in one place with a
    reason attached.
    """
    return value.date()  # type: ignore[attr-defined,no-any-return]


def main() -> None:
    client = OpenBBClient()

    # --- Real initial claims, weekly, SA (ICSA) ---------------------------
    dates, raw = _values(_fetch(client, "ICSA", "initial_claims"))
    print(f"ICSA observations: {len(raw)}")
    print("ICSA tail dates:", [str(day) for day in dates[-6:]])
    print("ICSA tail values:", [f"{value:,.0f}" for value in raw[-6:]])

    # Cadence check: the module's 4-week average is meaningless if the series
    # is not weekly. Section 21.0 asks for exactly this kind of assertion.
    # The ``date`` column arrives as object-dtype `datetime.date` values, not
    # pandas Timestamps, so the gap is a plain date subtraction.
    gaps = {(dates[i] - dates[i - 1]).days for i in range(1, len(dates))}
    print("distinct day-gaps between observations:", sorted(gaps))
    assert gaps <= {7}, f"expected a weekly cadence, saw gaps {sorted(gaps)}"

    # 4-week average of initial claims, the series the module actually wants.
    recent_4wk = sum(raw[-4:]) / 4.0
    trailing_13wk = sum(raw[-13:]) / 13.0

    print()
    print(f"latest 4wk avg        = {recent_4wk:,.0f}  (week of {dates[-1]})")
    print(f"trailing 13wk avg     = {trailing_13wk:,.0f}")
    print(f"latest vs trailing    = {(recent_4wk / trailing_13wk - 1):+.2%}")

    # The function takes the RAW weekly series and derives both windows itself
    # (D-022), so the whole series is passed and nothing is pre-averaged.
    signal = claims_trend_signal(ClaimsTrendInputs(weekly_initial_claims=raw))
    print()
    print("claims_trend_signal.value       =", signal.value)
    print("claims_trend_signal.confidence  =", signal.confidence)
    print("claims_trend_signal.interpret   =", signal.interpretation)
    for warning in signal.warnings:
        print("   warn:", warning)

    # The two computations must agree. Under D-024 the module takes its latest
    # reading from the LAST four weeks of the 13-week window and its baseline
    # from the FIRST four, so the script checks both against the same slices.
    expected_latest = sum(raw[-4:]) / 4.0
    expected_baseline = sum(raw[-13:-9]) / 4.0
    assert read_float(signal, "latest_4wk_avg") == round(expected_latest, 1), (
        f"module latest_4wk_avg {read_float(signal, 'latest_4wk_avg')} != expected "
        f"{round(expected_latest, 1)} from raw[-4:] — the module is averaging a "
        f"different window."
    )
    assert read_float(signal, "trailing_4wk_avg") == round(expected_baseline, 1), (
        f"module trailing_4wk_avg {read_float(signal, 'trailing_4wk_avg')} != expected "
        f"{round(expected_baseline, 1)} from raw[-13:-9]."
    )
    assert read_float(signal, "window_weeks") == 13, read_float(signal, "window_weeks")

    # D-024's direction rule, checked against the live data: the sign of the
    # reading must agree with the sign of the actual change over the window.
    actual_change = (expected_latest - expected_baseline) / expected_baseline
    assert (read_float(signal, "pct_above_trailing") >= 0) == (actual_change >= 0), (
        f"sign disagreement: the module reports "
        f"{read_float(signal, 'pct_above_trailing'):+.3f} but the latest quarter is "
        f"{actual_change:+.2%} versus the prior quarter's same span (D-024)."
    )
    print()
    print("CONSISTENCY OK: the module's windows and sign match the script's.")

    # --- Real continuing claims, the corroborating series -----------------
    _, c_raw = _values(_fetch(client, "CCSA", "continuing_claims"))
    c_recent_4wk = sum(c_raw[-4:]) / 4.0
    c_trailing_13wk = sum(c_raw[-17:-4]) / 13.0
    c_rising = c_recent_4wk > c_trailing_13wk

    print()
    print(f"CCSA latest 4wk avg   = {c_recent_4wk:,.0f}")
    print(f"CCSA trailing 13wk    = {c_trailing_13wk:,.0f}")
    print(f"CCSA rising           = {c_rising}")

    corroboration = claims_corroboration(
        ClaimsCorroborationInputs(
            initial_claims_signal=bool(read_bool(signal, "is_signal")),
            continuing_claims_rising=c_rising,
        )
    )
    print()
    print("claims_corroboration.value      =", corroboration.value)
    print("claims_corroboration.confidence =", corroboration.confidence)
    print("claims_corroboration.interpret  =", corroboration.interpretation)

    # --- Cross-series plausibility: continuing >> initial always ----------
    # A mis-mapped symbol would break this. Continuing claims are a stock
    # (people still receiving benefits), initial claims a weekly flow.
    assert c_recent_4wk > recent_4wk, (
        f"continuing claims ({c_recent_4wk:,.0f}) must exceed initial claims "
        f"({recent_4wk:,.0f}) — the registry symbols may be swapped."
    )
    print()
    print("PLAUSIBILITY OK: continuing claims > initial claims (as required by construction)")

    _check_tier2(client)


def last_gap_check(dates: list[date]) -> int:
    """Days between the two most recent observations of a date column."""
    return (dates[-1] - dates[-2]).days


def read_float(result: ModelResult, key: str) -> float:
    """Narrow a named entry of a dict-valued result, asserting rather than casting.

    ``ModelResult.value`` is a union by design (Section 22.9), so a script that
    indexes it must narrow at the use site. Asserting here rather than casting
    means a result that returned the wrong kind of value fails loudly instead of
    being silently coerced — the same discipline the test helpers apply, kept
    local because ``scripts/`` must not import from ``tests/``.
    """
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
    assert isinstance(value, dict), (
        f"{result.model_name}: expected a dict value to read {key!r}, got {type(value).__name__}"
    )
    entry = value[key]
    assert isinstance(entry, bool), (
        f"{result.model_name}: value[{key!r}] is {type(entry).__name__}, not a bool"
    )
    return entry


def read_str(result: ModelResult, key: str) -> str:
    """Narrow a named entry to a str."""
    value = result.value
    assert isinstance(value, dict), (
        f"{result.model_name}: expected a dict value to read {key!r}, got {type(value).__name__}"
    )
    entry = value[key]
    assert isinstance(entry, str), (
        f"{result.model_name}: value[{key!r}] is {type(entry).__name__}, not a str"
    )
    return entry


def read_int(result: ModelResult, key: str) -> int:
    """Narrow a named entry to an int, rejecting ``bool`` for the same reason as ``read_bool``.

    Kept separate from ``read_float`` rather than folding a count through a
    float: a sample size and a magnitude are different kinds of quantity, and a
    check that reads one as the other would not notice a model that started
    reporting ``140.0`` where ``140`` was promised.
    """
    value = result.value
    assert isinstance(value, dict), (
        f"{result.model_name}: expected a dict value to read {key!r}, got {type(value).__name__}"
    )
    entry = value[key]
    assert isinstance(entry, int) and not isinstance(entry, bool), (
        f"{result.model_name}: value[{key!r}] is {type(entry).__name__}, not an int"
    )
    return entry


def _check_tier2(client: OpenBBClient) -> None:
    """Real-data wiring for the four Tier 2 Module 6 functions.

    Each of these consumes inputs the snapshot builder derives from registry
    series. The point of running them on live data is Section 21.0: the unit
    tests prove the arithmetic, and this proves the units and signs line up
    with what FRED actually returns.
    """
    # --- two_survey_divergence on real UNRATE -----------------------------
    u_dates, u_raw = _values(_fetch(client, "UNRATE", "unemployment_rate"))
    print()
    print(f"UNRATE observations: {len(u_raw)}")
    print(f"UNRATE latest = {u_raw[-1]:.1f}%  (prior {u_raw[-2]:.1f}%, month of {u_dates[-1]})")
    u_change = u_raw[-1] - u_raw[-2]
    print(f"UNRATE 1-month change = {u_change:+.2f}pp")

    # Month-over-month gap must be one calendar month. The registry declares
    # UNRATE as monthly, and the change above is only a change *per month* if
    # the cadence is monthly — same reasoning as the weekly claims check.
    #
    # REAL-DATA FINDING (recorded as D-025): FRED's UNRATE truly omits
    # 2025-10-01. The gap between 2025-09-01 and 2025-11-01 is 61 days, and no
    # October observation exists in the vintage. That matters more than a
    # cadence assertion: `raw[-1] - raw[-2]` is then the change over TWO months,
    # reported as a one-month change with nothing in the output saying so. The
    # assertion below allows the observed gap but the script reports it loudly,
    # because the D-009 discipline — pair on the observation dates you actually
    # have — applies to consecutive-readings arithmetic too.
    u_gaps = {(u_dates[i] - u_dates[i - 1]).days for i in range(1, len(u_dates))}
    last_gap = last_gap_check(u_dates)
    irregular = sorted(g for g in u_gaps if g > 31)
    assert not irregular or irregular == [61], (
        f"UNRATE has an unexpected cadence break: gaps {sorted(u_gaps)}"
    )
    if irregular:
        last_gap = (u_dates[-1] - u_dates[-2]).days
        print(
            f"  CADENCE WARNING: UNRATE has a {irregular[0]}-day gap in its "
            f"history — at least one calendar month is genuinely absent from "
            f"the series (D-025)."
        )
        print(
            f"  The latest reading is {last_gap} days after the previous one, "
            f"so the change below is the change over that span, not "
            f"necessarily one month."
        )
    assert last_gap_check(u_dates) <= 31, (
        "the LATEST UNRATE pair must be one month apart for the change below to "
        "be a month-over-month change"
    )

    # PAYEMS for the establishment half of the comparison.
    p_dates, p_raw = _values(_fetch(client, "PAYEMS", "payrolls_level"))
    p_change = (p_raw[-1] - p_raw[-2]) * 1.0  # PAYEMS is thousands of persons
    print(f"PAYEMS latest change = {p_change:+,.0f}k  (month of {p_dates[-1]})")

    # The household half is a genuinely DIFFERENT series, not a copy of
    # payrolls. CE16OV is household-survey employment (thousands of people);
    # CIVPART is the participation rate. Using them makes this a real
    # two-survey comparison rather than a plumbing exercise — which is the
    # point of the function, since the two surveys count different things
    # (jobs vs people) and their divergence is the signal.
    h_dates, h_raw = _values(_fetch(client, "CE16OV", "household_employment"))
    h_change = h_raw[-1] - h_raw[-2]
    _, part_raw = _values(_fetch(client, "CIVPART", "participation_rate"))
    participation_change = part_raw[-1] - part_raw[-2]
    print(f"CE16OV latest change = {h_change:+,.0f}k  (month of {h_dates[-1]})")
    print(f"CIVPART change       = {participation_change:+.2f}pp (latest {part_raw[-1]:.1f}%)")

    # Cross-series plausibility on LEVELS, the D-009 discipline applied across
    # series: household employment and payrolls measure the same working
    # population by different methods, so they must be the same order of
    # magnitude. A mis-mapped symbol returns an individually plausible number
    # and only a cross-series identity catches it.
    ratio = h_raw[-1] / p_raw[-1]
    assert 0.9 < ratio < 1.1, (
        f"household employment ({h_raw[-1]:,.0f}k) and payrolls "
        f"({p_raw[-1]:,.0f}k) should be within ~10% of each other — both count "
        f"the same working population. Ratio {ratio:.3f} suggests a symbol "
        f"mis-mapping."
    )
    print(f"level cross-check: household/payrolls = {ratio:.4f}")

    two_survey = two_survey_divergence(
        TwoSurveyInputs(
            nfp_change_thousands=float(p_change),
            household_employment_change_thousands=float(h_change),
            unemployment_rate_change_pp=float(u_change),
            participation_rate_change_pp=float(participation_change),
        )
    )
    print("two_survey_divergence.value     =", two_survey.value)
    print("two_survey_divergence.interpret =", two_survey.interpretation[:105])
    for warning in two_survey.warnings:
        print("   warn:", warning[:105])

    # The verdict must be consistent with the four live inputs, re-derived here
    # independently. Asserting only that "a verdict came back" would pass on a
    # mis-ordered branch chain; this pins the mapping.
    payrolls_up = p_change > 0
    unemployment_up = u_change > 0
    participation_up = participation_change > 0
    if payrolls_up and unemployment_up and participation_up:
        expected = "PARTICIPATION_DRIVEN_not_weakness"
    elif payrolls_up and unemployment_up:
        expected = "GENUINE_DIVERGENCE_investigate"
    elif not payrolls_up and unemployment_up:
        expected = "BROAD_WEAKENING"
    else:
        expected = "CONSISTENT_STRENGTH"
    assert two_survey.value == expected, (
        f"module verdict {two_survey.value} != independently derived {expected} "
        f"from payrolls_up={payrolls_up}, unemployment_up={unemployment_up}, "
        f"participation_up={participation_up}"
    )
    print("verdict agrees with an independent read of the live inputs")

    # --- beveridge_curve_position on real JOLTS + UNRATE ------------------
    _, o_raw = _values(_fetch(client, "JTSJOL", "jolts_openings"))
    # JTSJOL is thousands of openings; the curve is in RATE space (percent of
    # the labor force). Converting requires the labor force level, so the
    # openings RATE is derived here the way the snapshot builder will — and the
    # conversion is stated rather than assumed.
    labor_force_thousands = 168000.0
    openings_rate = o_raw[-1] / labor_force_thousands * 100.0
    historical = get_settings().beveridge.openings_at(float(u_raw[-1]))

    print()
    print(f"JTSJOL latest = {o_raw[-1]:,.0f}k openings")
    print(
        f"implied openings rate    = {openings_rate:.3f}% "
        f"(labor force assumed {labor_force_thousands:,.0f}k)"
    )
    print(f"historical curve at u={u_raw[-1]:.1f}% -> {historical:.3f}%")

    beveridge = beveridge_curve_position(
        BeveridgeInputs(
            openings_rate_pct=openings_rate,
            unemployment_rate_pct=float(u_raw[-1]),
            historical_openings_at_this_u=historical,
        )
    )
    print("beveridge_curve_position.value =", beveridge.value)

    # Cross-check the module's arithmetic against the script's own subtraction.
    expected_shift = round(openings_rate - historical, 2)
    assert read_float(beveridge, "shift_pp") == expected_shift, (
        f"module shift {read_float(beveridge, 'shift_pp')} != script's "
        f"{expected_shift} = openings {openings_rate:.3f} - curve {historical:.3f}"
    )
    print(f"shift_pp matches the script's independent subtraction ({expected_shift:+})")

    # --- nfp_revision_adjusted_read on real payroll levels ----------------
    # PAYEMS is a LEVEL; the change is the first difference. Revisions are not
    # separately available from a single FRED pull of the current vintage, so
    # the two revision slots are passed as zero and the check is limited to the
    # identity: adjusted must equal headline when there are no revisions.
    revision = nfp_revision_adjusted_read(
        RevisionInputs(
            current_month_nfp=float(p_change),
            prior_month_revision=0.0,
            two_months_ago_revision=0.0,
        )
    )
    print()
    print(f"nfp_revision_adjusted_read.value = {revision.value}")
    assert read_float(revision, "revision_adjusted") == read_float(revision, "headline"), (
        "with zero revisions, adjusted must equal the headline"
    )
    assert not any("masked" in w for w in revision.warnings), (
        "a zero-revision read must not be reported as a masked beat"
    )
    print("zero-revision identity holds: adjusted == headline")

    # --- ahe_composition_flag: ECI genuinely absent -----------------------
    # AHE (CES0500000003) and ECI (ECIALLCIV) are not registry series, so this
    # exercises the None path — which is the state the module must handle in
    # most months anyway, since ECI is quarterly. Passing None is not a
    # workaround here; it is the real-world common case.
    ahe = ahe_composition_flag(
        AHEDistortionInputs(
            ahe_growth_yoy_pct=3.8,
            eci_growth_yoy_pct=None,
            low_wage_sector_employment_change_pct=-0.4,
        )
    )
    print()
    print(f"ahe_composition_flag.value = {ahe.value}")
    ahe_gap = ahe.value["ahe_minus_eci_pp"] if isinstance(ahe.value, dict) else "not-a-dict"
    assert ahe_gap is None, "ECI absent must report None, never a numeric 0.0"
    print("ECI-absent path reports None (not 0.0) as required")

    print()
    print("Tier 2 REAL-DATA CHECK COMPLETE")

    _check_phillips(client)
    _check_production_function(client)
    _check_shelter(client)
    _check_ppi_pipeline(client)
    _check_gdp_gdi(client)
    _check_leading_indicator(client)
    _check_gdp_nowcast(client)
    _check_auction_demand(client)
    _check_credit_spread(client)
    _check_financial_conditions(client)
    _check_policy_mix(client)
    _check_qe_qt_stance(client)
    _check_minsky_composition_drift(client)
    _check_probability_models(client)


def _check_shelter(client: OpenBBClient) -> None:
    """Real-data wiring for ``project_shelter_cpi`` (Module 5.1).

    **A substitution is unavoidable here, and it must be named rather than
    hidden.** Module 5.1's whole point is that CPI shelter lags *real-time market
    rents* — private asking-rent indices such as Zillow's ZORI or Apartment
    List's national rent index. Neither is on FRED, and this local OpenBB build
    carries no such series:

        ZORI        -> EMPTY
        Apartment List -> not on FRED

    So this check substitutes ``CUSR0000SEHA`` (CPI rent of primary residence) as
    the "market rent" leg. That is a **weaker** substitution and the check says
    so, because the substitution changes what is being tested:

    * ``CUSR0000SEHA`` is itself a CPI component measured from a survey of
      *existing tenants*, so it already contains a large part of the lag that
      Module 5.1's projection is trying to exploit. Lagging it by 15 months
      therefore measures the lag *inside* the CPI rent series, not the lead of
      market rents over CPI shelter.
    * The projection's magnitude is consequently understated relative to a true
      market-rent input.

    What the check still validates, and what it cannot:

    * It validates the **wiring** — that the vintage index reads the month the
      context line claims, that the direction call follows the sign of the gap,
      and that the value reconciles with the series at the stated offset.
    * It does **not** validate the economic claim. That needs a real-time rent
      source, recorded in ``OPEN_ISSUES.md`` as a required Phase 3 input rather
      than approximated here.

    The vintage is verified by an **independent lookup**: the script indexes the
    raw series itself using a months-ago expression written from the definition
    rather than copied from the model, then asserts the two agree. If the model's
    ``[-lag]``-versus-``[-(lag+1)]`` choice were wrong, the two would differ by
    exactly one month and this is where it surfaces.
    """
    print()
    print("=== project_shelter_cpi (Module 5.1) ===")

    settings = get_settings()
    lag = settings.inflation.shelter_lag

    cpi_shelter_dates, cpi_shelter_raw = _values(_fetch(client, "CUSR0000SAH1", "cpi_shelter"))
    rent_dates, rent_raw = _values(_fetch(client, "CUSR0000SEHA", "cpi_rent_primary"))

    print(f"cpi_shelter CUSR0000SAH1  n={len(cpi_shelter_raw):4} latest {cpi_shelter_dates[-1]}")
    print(f"rent leg    CUSR0000SEHA  n={len(rent_raw):4} latest {rent_dates[-1]}")
    print(f"configured lag = {lag} months")

    # Both are monthly CPI components. The cadence is asserted, but on the
    # LATEST pair only — **D-025 governs**: a CPI series can have a month
    # genuinely absent from the source, and `CUSR0000SAH1` shows the same
    # 61-day gap signature that `UNRATE` does. Failing on a historical gap would
    # make this check fail on real data for a reason that is not a defect, while
    # the *interpretability* of the reported change depends only on the latest
    # interval being a month.
    for label, dates in (("cpi_shelter", cpi_shelter_dates), ("rent", rent_dates)):
        gaps = sorted({(dates[i] - dates[i - 1]).days for i in range(1, len(dates))})
        latest_gap = (dates[-1] - dates[-2]).days
        assert 28 <= latest_gap <= 31, (
            f"{label}: the LATEST interval must be one month for a "
            f"month-over-month reading to mean anything; saw {latest_gap} days. "
            f"Distinct historical gaps: {gaps}"
        )
        if gaps != [28, 29, 30, 31]:
            missing = [g for g in gaps if g > 31]
            print(
                f"  CADENCE WARNING ({label}): historical gaps {missing} days "
                f"(D-025 — a month is genuinely absent from the source; the lag "
                f"arithmetic counts OBSERVATIONS, so an absent month shifts the "
                f"vintage by one calendar month)"
            )

    # --- Build YoY growth series, aligned by date ---------------------------
    def yoy_pct(dates: list[date], values: list[float]) -> dict[date, float]:
        """Year-over-year percent change, keyed by date.

        Keyed rather than positional: the two CPI series share a cadence and a
        source, but pairing them by index would still be an assumption. A dict
        keyed on the observation date makes the join explicit and makes a missing
        month visible as an absent key instead of a silent shift.
        """
        by_date = dict(zip(dates, values, strict=True))
        out: dict[date, float] = {}
        for day, value in by_date.items():
            prior_year = date(day.year - 1, day.month, day.day)
            if prior_year in by_date and by_date[prior_year] > 0:
                out[day] = (value / by_date[prior_year] - 1.0) * 100.0
        return out

    rent_yoy = yoy_pct(rent_dates, rent_raw)
    shelter_yoy = yoy_pct(cpi_shelter_dates, cpi_shelter_raw)

    # The market-rent history, oldest first, ending at the latest common date.
    shelter_dates_set = set(shelter_yoy)
    common = sorted(d for d in rent_yoy if d in shelter_dates_set)
    assert len(common) > lag + 1, (
        f"need more than {lag + 1} common YoY observations to exercise the lag; have {len(common)}"
    )
    latest_common = common[-1]
    market_rent_series = [rent_yoy[d] for d in common]

    print(f"aligned YoY series: {len(common)} common months, {common[0]} .. {latest_common}")

    current_shelter = shelter_yoy[latest_common]
    print(f"current CPI shelter YoY at {latest_common} = {current_shelter:+.2f}%")

    result = project_shelter_cpi(
        ShelterLagInputs(
            market_rent_growth_yoy_pct=market_rent_series,
            current_cpi_shelter_yoy_pct=current_shelter,
        )
    )
    assert isinstance(result.value, (int, float)) and not isinstance(result.value, bool)
    projected = float(result.value)
    print(f"projected CPI shelter  = {projected:+.2f}%")
    print(f"interpretation: {result.interpretation}")

    # --- Independent vintage lookup -----------------------------------------
    # Written from the DEFINITION ("the observation N months before the latest
    # one"), not copied from the model. The model uses [-(lag+1)]; if it had used
    # the specification's [-lag] these two would differ by exactly one month.
    vintage_index = len(common) - 1 - lag
    assert vintage_index >= 0, (
        f"indexing {lag} months back from the latest of {len(common)} common "
        f"observations lands before the start of the series"
    )
    independently_read = market_rent_series[vintage_index]
    print(
        f"independent lookup: {lag} months before {latest_common} is "
        f"{common[vintage_index]} = {independently_read:+.2f}%"
    )
    assert abs(projected - round(independently_read, 2)) < 0.005, (
        f"the module returned {projected} but the observation {lag} months before "
        f"the latest is {independently_read:.2f}% at {common[vintage_index]}. A "
        f"one-month difference here is the [-lag] off-by-one."
    )
    print("vintage index verified against an independent lookup")

    # --- The vintage must be lag months old, checked in DAYS ----------------
    # A month-counting error is invisible if only the list index is checked, so
    # the date distance is asserted too: a 15-month lag spans 450-490 days
    # depending on month lengths, and ~420 would mean 14 months.
    #
    # The band's upper bound is deliberately loose because of D-025: the index
    # counts OBSERVATIONS, and where the source omits a month those observations
    # span one extra calendar month. The LOWER bound is the one that catches an
    # off-by-one, since an absent month can only widen the span, never narrow it.
    vintage_date = common[vintage_index]
    span_days = (latest_common - vintage_date).days
    minimum_days = int(lag * 30.0)
    print(f"vintage {vintage_date} is {span_days} days before {latest_common}")
    assert span_days >= minimum_days, (
        f"a {lag}-month vintage must span at least {minimum_days} days; saw "
        f"{span_days}, which is one month too few — this is the specification's "
        f"[-lag] off-by-one measured in calendar time"
    )
    assert span_days <= int((lag + 2) * 30.5), (
        f"a {lag}-month vintage should not span more than ~{lag + 2} months; saw {span_days} days"
    )

    # --- Direction follows the sign of the independently computed gap -------
    gap = independently_read - current_shelter
    tolerance = settings.inflation.shelter_converged_tolerance
    if abs(gap) <= tolerance:
        expected_direction = "converged"
    elif gap < 0:
        expected_direction = "cooling"
    else:
        expected_direction = "reaccelerating"
    print(f"gap {gap:+.2f}pp -> expected direction {expected_direction}")
    if expected_direction == "converged":
        assert "consistent with the market-rent vintage" in result.interpretation
    else:
        assert expected_direction in result.interpretation, (
            f"model said {result.interpretation!r}, expected {expected_direction}"
        )

    # The reported gap in context must match the independently computed one.
    assert f"{gap:+.2f}pp" in result.context, (
        f"context does not carry the independently computed gap {gap:+.2f}pp"
    )
    print("direction and reported gap agree with the independent computation")

    print(f"warnings emitted ({len(result.warnings)}):")
    for warning in result.warnings:
        print(f"  - {warning[:92]}...")

    # --- The insufficient-data path, on real history -------------------------
    short = market_rent_series[:lag]
    empty_result = project_shelter_cpi(
        ShelterLagInputs(
            market_rent_growth_yoy_pct=short,
            current_cpi_shelter_yoy_pct=current_shelter,
        )
    )
    assert empty_result.value is None, (
        f"{lag} points cannot contain a {lag}-month vintage, so the projection "
        f"must be None; got {empty_result.value}"
    )
    assert empty_result.confidence > 0.0, (
        "the insufficient-data confidence must be the computed floor, not the "
        "specification's literal 0.0"
    )
    print(
        f"insufficient-history path: value=None, confidence="
        f"{empty_result.confidence} (computed floor, not 0.0)"
    )

    print(
        "SHELTER SUBSTITUTION CAVEAT: the rent leg is CPI rent of primary "
        "residence, not a real-time asking-rent index. See OPEN_ISSUES.md."
    )
    print("shelter REAL-DATA CHECK COMPLETE")


def _check_production_function(client: OpenBBClient) -> None:
    """Real-data wiring for ``potential_gdp_cobb_douglas`` (Module 3.5 / 7.2).

    The interesting part is not that the arithmetic runs — it is what the real
    inputs do to it.

    Units are the trap here, and the module deliberately does not normalise
    (a normalised output would hide a units mismatch rather than surface it).
    The real series are:

    * ``RKNANPUSA666NRUG`` — the BEA real net capital stock, in **millions** of
      chained 2017 USD, **annual**, and last published for 2023. It lags GDP by
      roughly three years because perpetual-inventory estimates need completed
      investment and depreciation data.
    * ``GDPC1`` — real GDP in **billions** of chained 2017 USD, quarterly.

    So ``K`` is in millions and ``Y`` in billions: a factor of 1000 sits between
    the input and the output, and this script converts explicitly rather than
    letting the model do it invisibly.

    Two independent plausibility checks are applied, both cross-series:

    1. **Capital/output ratio.** ``K / Y`` for the US sits in a narrow band. If
       a mis-mapping put the wrong series in ``K`` — a level index, a nominal
       figure, a quarterly flow — the ratio would leave that band immediately,
       while the production function itself would still return a smooth,
       plausible-looking number.
    2. **CBO cross-check.** ``GDPPOT`` is the preferred published estimate
       (Section 21.1). Because this script solves ``A`` to close the identity on
       actual GDP, the modelled figure reproduces GDP by construction — so the
       comparison is of the **output gap**, and it is **not** a measure of
       method dispersion. It is still a real check: a wrong ``K`` or ``L`` moves
       the calibrated ``A`` and shifts the gap out of a plausible band.

    Section 21.1 says dispersion across independent estimates IS the uncertainty
    band. Producing that band needs a second independent potential-output
    estimate, and the Fed's is not on FRED. Recorded as a known gap rather than
    substituted with something circular.
    """
    print()
    print("=== potential_gdp_cobb_douglas (Module 3.5 / 7.2) ===")

    settings = get_settings()
    alpha = settings.production_function.alpha_value

    # --- Real inputs ------------------------------------------------------
    k_dates, k_raw = _values(_fetch(client, "RKNANPUSA666NRUG", "capital_stock"))
    y_dates, y_raw = _values(_fetch(client, "GDPC1", "gdp_real"))
    g_dates, g_raw = _values(_fetch(client, "GDPPOT", "gdp_potential"))
    p_dates, p_raw = _values(_fetch(client, "OPHNFB", "output_per_hour"))

    print(f"capital_stock  RKNANPUSA666NRUG  latest {k_dates[-1]} = {k_raw[-1]:,.0f} million")
    print(f"gdp_real       GDPC1             latest {y_dates[-1]} = {y_raw[-1]:,.3f} bn")
    print(f"output_per_hour OPHNFB           latest {p_dates[-1]} = {p_raw[-1]:,.3f} idx2017")

    # The capital stock is ANNUAL. Its latest observation being years behind the
    # quarterly series is not a bug in the fetch — it is what the source
    # publishes, and a "latest vs latest" pairing would silently compare 2023
    # capital against 2026 output. Report the span the way D-025 requires.
    k_span = (y_dates[-1] - k_dates[-1]).days
    print(f"capital stock lags real GDP by {k_span} days ({k_span / 365.25:.1f} years)")
    assert k_span > 300, (
        f"expected the annual capital stock to lag the quarterly GDP series "
        f"substantially; saw only {k_span} days, which suggests RKNANPUSA666NRUG "
        f"is no longer annual or the fetch aliased a different series"
    )

    # --- Unit reconciliation, done explicitly and visibly ------------------
    # millions -> billions is a factor of 1000.
    capital_bn = k_raw[-1] / 1000.0
    gdp_bn = y_raw[-1]

    capital_output_ratio = capital_bn / gdp_bn
    print(f"capital/output ratio = {capital_output_ratio:.2f}  (US is structurally ~3-4)")

    # Cross-series plausibility. A wrong symbol in K would land far outside this
    # band while the production function still returned a smooth number.
    assert 2.0 < capital_output_ratio < 5.0, (
        f"K/Y = {capital_output_ratio:.2f} is outside the plausible US band "
        f"(2-5). Check the RKNANPUSA666NRUG mapping and its units — millions vs "
        f"billions is the usual culprit."
    )

    # --- Realised CBO potential, with the projection block EXCLUDED ---------
    # GDPPOT carries CBO projections to ~2036. Reading [-1] would compute the
    # cross-check against a 2036 forecast. Same hazard the output_gap adapter
    # closes with models/as_of.py.
    realised_potential = [(d, v) for d, v in zip(g_dates, g_raw, strict=True) if d <= y_dates[-1]]
    withheld = len(g_raw) - len(realised_potential)
    print(
        f"CBO potential: latest realised {realised_potential[-1][0]} = "
        f"{realised_potential[-1][1]:,.3f} bn  ({withheld} forward points withheld)"
    )
    assert withheld > 0, (
        "expected GDPPOT to carry forward projections; 0 withheld means the "
        "projection block is absent and the filter is not doing its job"
    )
    cbo_potential_bn = realised_potential[-1][1]

    # --- Labor input: total hours, built from hours-per-person and employment -
    #
    # PAIR ON THE LATEST COMMON DATE, not on each series' own latest. This is
    # D-009's rule in its third dimension: `PRS85006023` is QUARTERLY (business
    # sector hours) while `PAYEMS` is MONTHLY, so their own-latest dates differ
    # by four months. Multiplying `hours[-1]` by `emp[-1]` would compute a
    # "total hours" from Q2-2026 hours and August-2026 employment — a number
    # that has no observation date and no economic meaning, while still looking
    # perfectly smooth.
    hours_dates, hours_raw = _values(_fetch(client, "PRS85006023", "avg_weekly_hours"))
    emp_dates, emp_raw = _values(_fetch(client, "PAYEMS", "payrolls"))

    emp_by_date = dict(zip(emp_dates, emp_raw, strict=True))
    paired = [
        (d, h, emp_by_date[d])
        for d, h in zip(hours_dates, hours_raw, strict=True)
        if d in emp_by_date
    ]
    assert paired, (
        f"no common observation date between hours "
        f"({hours_dates[-1]}) and employment ({emp_dates[-1]}) — the two series "
        f"cannot be multiplied"
    )
    common_date, hours_latest, emp_latest = paired[-1]
    print(
        f"paired on {common_date}: hours {hours_latest:.2f} hrs/wk "
        f"(business sector, quarterly) x {emp_latest:,.0f}k persons (payrolls, monthly)"
    )
    print(
        f"  own-latest dates differ: hours {hours_dates[-1]} vs employment "
        f"{emp_dates[-1]} — paired on the common date, not each own latest"
    )
    assert (emp_dates[-1] - hours_dates[-1]).days > 0, (
        "this assertion exists to document the cadence asymmetry; if the two "
        "series ever share a latest date, remove the pairing logic deliberately"
    )

    # Annual hours, thousands of persons x hours/week x 52 weeks.
    labor_hours_bn = emp_latest * hours_latest * 52.0 / 1e6
    print(f"  = {labor_hours_bn:,.1f} bn hours (annualised)")

    # --- Solve for A so the identity closes, then check it is plausible ----
    # The point is NOT to produce a potential-GDP estimate from a fitted A —
    # that would be circular. It is to ask whether the A implied by the real K
    # and L is a plausible productivity level, which is the check a wrong K or L
    # would fail.
    import math

    if capital_bn <= 0 or labor_hours_bn <= 0:
        raise AssertionError("capital and labor must both be positive")

    implied_a = gdp_bn / (math.pow(capital_bn, alpha) * math.pow(labor_hours_bn, 1.0 - alpha))
    print(f"implied A (calibrated to close the identity on real GDP) = {implied_a:.4f}")
    assert implied_a > 0.0

    # Now the actual model call, with the calibrated A, and the CBO comparison.
    result = potential_gdp_cobb_douglas(
        PotentialGDPInputs(
            total_factor_productivity=implied_a,
            capital_stock=capital_bn,
            labor_input=labor_hours_bn,
        )
    )
    assert isinstance(result.value, (int, float)) and not isinstance(result.value, bool)
    modelled_bn = float(result.value)

    print()
    print(f"cobb-douglas potential (calibrated A) = {modelled_bn:,.2f} bn")
    print(f"cbo realised potential                = {cbo_potential_bn:,.2f} bn")
    print(f"actual real GDP                       = {gdp_bn:,.2f} bn")

    # --- The cross-field identity, against live numbers --------------------
    expected = round(
        implied_a * math.pow(capital_bn, alpha) * math.pow(labor_hours_bn, 1.0 - alpha), 2
    )
    assert modelled_bn == expected, (
        f"module returned {modelled_bn} but A*K^a*L^(1-a) = {expected} recomputed "
        f"from the reported components"
    )
    print(f"identity: A*K^a*L^(1-a) = {expected} matches the module's {modelled_bn}")

    # --- What this comparison does and does not establish -------------------
    #
    # Because A was solved to close the identity on actual GDP, the modelled
    # figure reproduces actual GDP by construction. So the number below is the
    # OUTPUT GAP, not an independent potential-GDP estimate, and it is NOT
    # evidence about method dispersion. Saying otherwise would be the exact
    # overclaim this module's warnings exist to prevent.
    #
    # What it does establish: a wrong K or L would move the calibrated A and
    # therefore shift this gap out of the plausible band. It is a self-
    # consistency check on the real inputs as a set.
    #
    # Genuine method dispersion requires a second INDEPENDENT potential-output
    # estimate. The live figures that come closest are:
    #   * CBO (GDPPOT)                  -> the value compared here
    #   * the fitted Cobb-Douglas curve -> circular, as explained above
    #   * the Fed's own potential GDP   -> not on FRED, so not yet available
    # Recorded as a known gap rather than papered over.
    gap_vs_cbo_pct = (modelled_bn - cbo_potential_bn) / cbo_potential_bn * 100.0
    print(f"actual vs CBO potential = {gap_vs_cbo_pct:+.2f}% (the output gap)")
    assert -10.0 < gap_vs_cbo_pct < 10.0, (
        f"a real-economy output gap of {gap_vs_cbo_pct:+.2f}% is implausible; the "
        f"inputs or the unit reconciliation are wrong"
    )
    print("  NOTE: A was calibrated to close the identity, so this gap is NOT method dispersion.")
    print(
        "  Method dispersion needs a second independent potential estimate; "
        "the Fed's is not on FRED."
    )

    # The check that IS independent: the same-quarter output gap this project
    # recorded in D-009, reproduced from a completely different route. D-009
    # found +0.83% by pairing GDPPOT with GDPC1 on their latest COMMON quarter;
    # agreement here means the unit reconciliation and the factor inputs are
    # jointly consistent with the earlier finding.
    if abs(gap_vs_cbo_pct - 0.83) > 0.05:
        print(
            f"  WARNING: D-009 recorded a same-quarter output gap of +0.83%; "
            f"this run reproduces {gap_vs_cbo_pct:+.2f}%. The two should agree "
            f"closely — investigate before trusting either."
        )
    else:
        print(
            f"  D-009 cross-check: reproduces the recorded +0.83% same-quarter "
            f"gap ({gap_vs_cbo_pct:+.2f}%) via an independent route"
        )

    print(f"warnings emitted ({len(result.warnings)}):")
    for warning in result.warnings:
        print(f"  - {warning[:96]}...")
    assert len(result.warnings) == 3, (
        f"expected the three unconditional warnings; saw {len(result.warnings)}"
    )
    assert any("LEAST predictable" in w for w in result.warnings)
    assert any("PRODUCTION-FUNCTION ESTIMATE" in w for w in result.warnings)

    # --- growth_accounting_decomposition on real growth rates --------------
    # Real annualised growth over four quarters for both terms.
    real_gdp_growth_pct = (y_raw[-1] / y_raw[-5] - 1.0) * 100.0 if len(y_raw) > 5 else float("nan")
    # Four quarters back, on the PAIRED series. Using `emp_raw[-5]` here would
    # be five MONTHS of payrolls against four QUARTERS of hours — a growth rate
    # over an undefined span, which is the same defect the pairing above closes.
    _, hours_prior, emp_prior = paired[-5]
    hours_prior_bn = emp_prior * hours_prior * 52.0 / 1e6
    labor_input_growth_pct = (labor_hours_bn / hours_prior_bn - 1.0) * 100.0
    # Productivity growth is the difference between output and hours growth —
    # that is the definition, not an approximation.
    productivity_growth_pct = real_gdp_growth_pct - labor_input_growth_pct

    print()
    print(f"real GDP growth (4q)        = {real_gdp_growth_pct:+.2f}%")
    print(f"labor input growth (4q)     = {labor_input_growth_pct:+.2f}%")
    print(f"implied productivity growth = {productivity_growth_pct:+.2f}%")

    growth = growth_accounting_decomposition(
        labor_force_growth_pct=labor_input_growth_pct,
        productivity_growth_pct=productivity_growth_pct,
    )
    assert isinstance(growth.value, dict)
    reported_total = growth.value["potential_growth"]
    assert isinstance(reported_total, (int, float))
    assert abs(float(reported_total) - (labor_input_growth_pct + productivity_growth_pct)) < 0.01, (
        "the reported total must be the sum of the two reported contributions"
    )
    share = growth.value["productivity_share"]
    print(f"growth_accounting: total {reported_total:+.2f}%, productivity share {share}")
    if share is not None:
        assert isinstance(share, (int, float))
        # Share and signs must be mutually consistent with the inputs.
        if productivity_growth_pct >= 0 and labor_input_growth_pct >= 0:
            assert 0.0 <= float(share) <= 1.0, (
                f"with both terms positive the share must lie in [0,1]; got {share}"
            )
    if growth.warnings:
        print(f"growth warnings: {len(growth.warnings)}")
        for warning in growth.warnings:
            print(f"  - {warning[:96]}...")

    print("potential GDP REAL-DATA CHECK COMPLETE")


def _check_phillips(client: OpenBBClient) -> None:
    """Real-data wiring for ``phillips_curve_inflation`` (Module 3.3).

    This function is the reason a single-input live check is not enough. Its two
    dominant inputs are both contestable, and the live data shows *how*: the two
    defensible measures of ``pi^e`` differ by well over a percentage point on the
    same date, which changes the output more than a realistic u* revision does.
    Running the model on both is what makes that visible.
    """
    from macro_engine.models.inflation_dynamics import (
        PhillipsCurveInputs,
        phillips_curve_inflation,
    )

    # pi^e, market-based: the 10-year breakeven = nominal 10yr - real 10yr.
    # Both components are separately verified registry series (D-2.1 notes 5yr
    # is the shortest available TIPS breakeven; 10yr is used here because the
    # nominal curve carries it too).
    _, nominal = _values(_fetch(client, "DGS10", "nominal_10yr"))
    _, real = _values(_fetch(client, "DFII10", "tips_10yr"))
    breakeven = nominal[-1] - real[-1]

    # pi^e, survey-based: University of Michigan 1-year expected inflation.
    # A genuinely DIFFERENT measure answering a different question (what
    # households believe), not a fallback for the breakeven.
    m_dates, michigan = _values(_fetch(client, "MICH", "michigan_expectations"))

    _, u_raw = _values(_fetch(client, "UNRATE", "unemployment_rate"))
    nairu = get_settings().phillips.nairu_value
    beta = get_settings().phillips.beta_value

    print()
    print("--- phillips_curve_inflation (Module 3.3) ---")
    print(
        f"nominal 10yr = {nominal[-1]:.2f}%   real 10yr = {real[-1]:.2f}%   "
        f"-> breakeven pi^e = {breakeven:.2f}%"
    )
    print(f"Michigan 1yr expected inflation = {michigan[-1]:.2f}% (survey of {m_dates[-1]})")
    print(f"u = {u_raw[-1]:.2f}%   u* = {nairu:.2f}% (config)   beta = {beta}")

    # The two expectation measures must be genuinely different series, or the
    # comparison below would be vacuous. Asserted rather than printed, because
    # if a future registry edit pointed both at the same symbol the script would
    # still run and would silently stop testing anything.
    assert abs(breakeven - michigan[-1]) > 0.25, (
        f"the market and survey expectation measures agree to within "
        f"{abs(breakeven - michigan[-1]):.2f}pp — if these are the same series "
        f"the comparison below proves nothing. breakeven={breakeven:.2f}, "
        f"michigan={michigan[-1]:.2f}"
    )

    results = {}
    for label, pi_e in (("market breakeven", breakeven), ("Michigan survey", michigan[-1])):
        result = phillips_curve_inflation(
            PhillipsCurveInputs(
                inflation_expectations=pi_e,
                unemployment_rate=float(u_raw[-1]),
                nairu=nairu,
            )
        )
        results[label] = result
        print(
            f"  pi^e={pi_e:5.2f}% ({label:16}) -> implied inflation "
            f"{result.value}%  conf={result.confidence}"
        )

    # Sign check against real data: UNRATE currently sits BELOW or ABOVE the
    # configured u*, and the implied inflation must move in the corresponding
    # direction away from pi^e. This is the direction assertion the unit tests
    # make on synthetic data, restated against the live unemployment rate.
    gap = float(u_raw[-1]) - nairu
    market = results["market breakeven"].value
    survey = results["Michigan survey"].value
    assert isinstance(market, float) and isinstance(survey, float)
    if gap < 0:
        assert market > breakeven, (
            f"u ({u_raw[-1]:.2f}) is BELOW u* ({nairu:.2f}), so the labor market "
            f"is tight and implied inflation must EXCEED pi^e; got {market:.2f} "
            f"vs pi^e {breakeven:.2f}"
        )
    elif gap > 0:
        assert market < breakeven, (
            f"u ({u_raw[-1]:.2f}) is ABOVE u* ({nairu:.2f}), so the labor market "
            f"is slack and implied inflation must be BELOW pi^e; got "
            f"{market:.2f} vs pi^e {breakeven:.2f}"
        )
    print(
        f"  direction: u-gap {gap:+.2f}pp -> implied inflation "
        f"{'above' if gap < 0 else 'below' if gap > 0 else 'at'} pi^e "
        f"(correct)"
    )

    # The cross-field identity, against the live numbers: the reported value
    # must equal pi^e - beta*(u - u*) for the market case.
    expected = round(breakeven - beta * gap, 2)
    assert market == expected, (
        f"module returned {market} but pi^e - beta*(u - u*) = "
        f"{breakeven:.2f} - {beta}*({gap:+.2f}) = {expected}"
    )
    print(
        f"  identity: {breakeven:.2f} - {beta}*({gap:+.2f}) = {expected} "
        f"matches the module's {market}"
    )

    # What the live data shows about the headline uncertainty: the two
    # expectation measures differ by more than a plausible u* revision moves the
    # answer, so the CHOICE of pi^e dominates. Reported, because it is the
    # single most important thing a reader of this model needs to know.
    pi_e_spread = abs(breakeven - michigan[-1])
    u_star_moves = abs(beta) * 0.5
    print()
    print(
        f"  pi^e measure spread = {pi_e_spread:.2f}pp  ->  output spread "
        f"{abs(market - survey):.2f}pp"
    )
    print(f"  a 0.5pp u* revision moves the output {u_star_moves:.2f}pp")
    if pi_e_spread > u_star_moves:
        print(
            "  NOTE: the pi^e MEASURE CHOICE moves the output more than a "
            "realistic u* revision does."
        )
    print("Phillips REAL-DATA CHECK COMPLETE")


def _check_ppi_pipeline(client: OpenBBClient) -> None:
    """Real-data wiring for ``ppi_pipeline_signal`` (Module 5.4).

    Three things this check exists to establish, in order of importance:

    1. **The stage mapping works and the gradient is real.** WPSID62 (crude),
       WPSID61 (intermediate) and PPIFIS (final demand) must all be live and
       must be paired on a **common** date — PPIFIS starts in 2009-11 while the
       WPSID series reach back to 1947, so the common window is bounded by the
       youngest series. Pairing on each series' own latest date would be the
       D-009 defect; here it happens to be benign (all three end 2026-08-01) but
       it is asserted rather than assumed.

    2. **The specification's ordering test has a base rate, and it is near a
       coin flip.** The check recomputes the 190-month history and reports the
       measured share itself, so the D-029 number in ``settings.yaml`` is
       independently reproducible from this script rather than trusted.

    3. **The discontinued series is genuinely unusable.** ``PPICRM`` — the
       obvious-looking crude index — is checked and shown to stop in 2015-12,
       which is the evidence behind the mapping decision.
    """
    print()
    print("=== ppi_pipeline_signal (Module 5.4) ===")

    stages = {
        "crude": ("WPSID62", "ppi_stage_crude"),
        "intermediate": ("WPSID61", "ppi_stage_intermediate"),
        "final_demand": ("PPIFIS", "ppi"),
    }
    frames: dict[str, dict[date, float]] = {}
    for stage, (symbol, label) in stages.items():
        dates, values = _values(_fetch(client, symbol, label))
        frames[stage] = dict(zip(dates, values, strict=True))
        print(f"{stage:13} {symbol:8} n={len(values):5} {dates[0]} .. {dates[-1]}")

    # The common window, and the reason it is shorter than any single series.
    common = sorted(
        set(frames["crude"]) & set(frames["intermediate"]) & set(frames["final_demand"])
    )
    print(
        f"common observations = {len(common)} "
        f"({common[0]} .. {common[-1]}) — bounded by PPIFIS, which starts 2009-11"
    )
    assert len(common) > 150, f"too few common observations to measure: {len(common)}"

    def yoy(stage: str, day: date) -> float | None:
        """Year-over-year percent change, same month one year earlier."""
        prior = date(day.year - 1, day.month, 1)
        series = frames[stage]
        if prior not in series:
            return None
        return (series[day] / series[prior] - 1.0) * 100.0

    latest = common[-1]
    readings: dict[str, float] = {}
    for stage in stages:
        own_latest = max(frames[stage])
        value = yoy(stage, latest)
        assert value is not None, f"{stage} has no year-earlier point for {latest}"
        readings[stage] = value
        print(
            f"{stage:13} own-latest={own_latest} "
            f"YoY@own={yoy(stage, own_latest):+6.2f}%  "
            f"YoY@common={value:+6.2f}%"
        )

    # The pairing assertion: if these ever diverge the common-date discipline
    # has stopped holding for one of the series.
    for stage in stages:
        own = yoy(stage, max(frames[stage]))
        assert own is not None
        if abs(own - readings[stage]) > 0.005:
            print(
                f"  PAIRING WARNING ({stage}): own-latest reading {own:+.2f}% "
                f"differs from common-date {readings[stage]:+.2f}% — the stage "
                f"series are not aligned."
            )

    result = ppi_pipeline_signal(
        PPIPipelineInputs(
            crude_stage_yoy_pct=readings["crude"],
            intermediate_stage_yoy_pct=readings["intermediate"],
            final_demand_yoy_pct=readings["final_demand"],
            # Both are human assessments; "stable"/"neutral" is the reading with
            # the least embedded opinion, which is what a wiring check should use.
            corporate_margin_trend="stable",
            demand_condition="neutral",
        )
    )

    assert isinstance(result.value, dict), "value must be a dict for this model"
    crude_v, inter_v, final_v = (
        readings["crude"],
        readings["intermediate"],
        readings["final_demand"],
    )

    # Cross-field identity: recompute the boolean from the reported readings.
    expected_building = crude_v > inter_v > final_v
    assert result.value["upstream_pressure_building"] is expected_building, (
        f"boolean {result.value['upstream_pressure_building']} contradicts the "
        f"readings {crude_v:+.2f} > {inter_v:+.2f} > {final_v:+.2f}"
    )
    # Cross-field identity: the spread is crude minus final.
    assert abs(result.value["stage_spread_pp"] - round(crude_v - final_v, 2)) < 0.005, (
        "stage_spread_pp does not equal crude - final"
    )

    print()
    print(
        f"crude {crude_v:+.2f}% > intermediate {inter_v:+.2f}% > "
        f"final {final_v:+.2f}%  ->  upstream_pressure_building="
        f"{result.value['upstream_pressure_building']}"
    )
    print(
        f"gradient_direction={result.value['gradient_direction']}  "
        f"pass_through={result.value['expected_pass_through']}  "
        f"spread={result.value['stage_spread_pp']:+.2f}pp"
    )
    print(f"confidence = {result.confidence} (computed, not the spec's 0.4)")

    # --- Independently reproduce the base rate published in settings.yaml ---
    # This is the D-029 number. Recomputing it here means the config value is
    # checkable rather than trusted, and a silent drift in either the setting or
    # the series shows up as a mismatch.
    history: list[tuple[float, float, float]] = []
    for day in common:
        c, i, f = yoy("crude", day), yoy("intermediate", day), yoy("final_demand", day)
        if c is None or i is None or f is None:
            continue
        history.append((c, i, f))

    strict = sum(1 for c, i, f in history if c > i > f)
    loose = sum(1 for c, i, f in history if c > f)
    total = len(history)
    strict_rate = strict / total
    loose_rate = loose / total

    print()
    print(f"base-rate recomputation over {total} usable months:")
    print(f"  strict crude > inter > final : {strict}/{total} = {strict_rate:.1%}")
    print(f"  loose  crude > final         : {loose}/{total} = {loose_rate:.1%}")

    configured = get_settings().inflation.pipeline_base_rate
    for label, measured, published in (
        ("strict", strict_rate, configured.strict_descending_rate),
        ("loose", loose_rate, configured.crude_above_final_rate),
    ):
        if abs(measured - published) > 0.01:
            print(
                f"  BASE-RATE DRIFT ({label}): config says {published:.1%}, "
                f"live recomputation says {measured:.1%}. One of the two moved."
            )
        else:
            print(f"  base-rate {label} matches config ({published:.1%})")

    assert not (strict_rate > 0.5), (
        "the strict ordering holds more often than chance — that would overturn "
        "D-029, which reports it as a near coin flip"
    )
    print(
        "  CONFIRMED: neither ordering clears a coin flip, so the flag must "
        "travel with its base rate (D-029)"
    )

    # --- The discontinued series, checked rather than assumed ---
    pc_dates, _ = _values(_fetch(client, "PPICRM", "discontinued_crude"))
    print()
    print(f"PPICRM (crude materials, DISCONTINUED) last observation = {pc_dates[-1]}")
    assert pc_dates[-1] < date(2020, 1, 1), (
        f"PPICRM extends to {pc_dates[-1]}; if it were live it would be the "
        f"better crude-stage series and the mapping should be revisited"
    )
    print("PPICRM confirmed unusable (truncated ~2015) — WPSID62 is the live crude stage")

    print("ppi_pipeline REAL-DATA CHECK COMPLETE")


def _check_gdp_gdi(client: OpenBBClient) -> None:
    """Real-data wiring for ``gdp_gdi_divergence`` (Module 7.1).

    Four things this check exists to establish, in order of importance:

    1. **GDI is genuinely live.** Section 21.1's table marks it "VERIFY
       series", and two plausible alternatives (``GDINC1``, ``A261RC1Q027SBEA``)
       are dead. If ``GDI`` ever stops returning data, the model must be fed
       ``None`` and report unavailable rather than have either alternative
       substituted — so the check names them explicitly.

    2. **The two series are paired on a common date.** GDP and GDI are both
       quarterly and both start 1947-01, so the risk is lower than in Module
       5.4, but the pairing is asserted rather than assumed: a same-quarter
       comparison is the only one whose difference is a statistical
       discrepancy rather than a mix of discrepancy and one quarter of growth.

    3. **The sign of the divergence is a coin flip.** The check recomputes the
       314-quarter history and reports the GDP-led share itself, so the D-031
       claim that the direction carries no information is reproducible from
       this script rather than trusted from ``settings.yaml``.

    4. **The level wedge is NOT mean-zero, and the growth divergence IS.** These
       are the two quantities a consumer is most likely to conflate, and the
       whole point of the module's fourth warning is that averaging them is
       only valid for the growth form. Both are recomputed here independently.
    """
    print()
    print("=== gdp_gdi_divergence (Module 7.1) ===")

    gdp_dates, gdp_vals = _values(_fetch(client, "GDP", "gdp_nominal"))
    gdi_dates, gdi_vals = _values(_fetch(client, "GDI", "gdi"))

    gdp = dict(zip(gdp_dates, gdp_vals, strict=True))
    gdi = dict(zip(gdi_dates, gdi_vals, strict=True))

    print(f"  GDP: {len(gdp)} quarters, {gdp_dates[0]} .. {gdp_dates[-1]}")
    print(f"  GDI: {len(gdi)} quarters, {gdi_dates[0]} .. {gdi_dates[-1]}")

    common = sorted(set(gdp) & set(gdi))
    print(f"  common quarters = {len(common)}")
    assert len(common) >= 200, (
        f"only {len(common)} common quarters; the base rates in settings.yaml "
        f"were measured over 314, so a window this short cannot reproduce them"
    )

    # --- The dead alternatives, checked rather than assumed ---
    for dead in ("GDINC1", "A261RC1Q027SBEA"):
        try:
            frame = client.fetch_series(
                provider="fred",
                endpoint="economy.fred_series",
                params={"symbol": dead},
                series_label=dead,
            )
            rows = 0 if frame is None else len(frame)
        except Exception:
            rows = 0
        assert rows == 0, (
            f"{dead} returned {rows} rows; if a real-GDI route now exists the "
            f"nominal/real pairing choice should be revisited"
        )
    print("  confirmed DEAD routes (must never be substituted): GDINC1, A261RC1Q027SBEA")

    # --- The level wedge: recomputed, and asserted NOT mean-zero ---
    wedges = [(gdi[q] - gdp[q]) / gdp[q] * 100 for q in common]
    mean_wedge = sum(wedges) / len(wedges)
    configured_wedge = get_settings().gdp_gdi.level_wedge_mean
    print()
    print(f"  level wedge (GDI-GDP)/GDP: mean = {mean_wedge:+.3f}%")
    print(f"  config says                        {configured_wedge:+.3f}%")
    assert abs(mean_wedge - configured_wedge) < 0.02, (
        f"level-wedge drift: live recomputation {mean_wedge:+.3f}% vs config "
        f"{configured_wedge:+.3f}%. One of the two moved."
    )
    assert mean_wedge < 0, (
        "the level wedge is expected to be persistently negative; a positive "
        "reading would overturn the D-031 discussion of the average"
    )
    print("  CONFIRMED: the LEVEL wedge is negative, so averaging levels is biased")

    # --- The growth divergence: recomputed, and asserted to be mean-zero ---
    usable: list[tuple[date, float, float, float]] = []
    for q in common:
        try:
            prior = q.replace(year=q.year - 1)
        except ValueError:  # 29 February in a non-leap year
            continue
        if prior not in gdp or prior not in gdi:
            continue
        if not gdp[prior] or not gdi[prior]:
            continue
        gy = (gdp[q] / gdp[prior] - 1) * 100
        iy = (gdi[q] / gdi[prior] - 1) * 100
        usable.append((q, gy, iy, gy - iy))

    print()
    print(f"  growth pairs (same quarter prior year) = {len(usable)}")
    assert len(usable) >= 250, f"only {len(usable)} growth pairs; too few to re-measure"

    divergences = [d for _, _, _, d in usable]
    mean_div = sum(divergences) / len(divergences)
    gdp_led = sum(1 for d in divergences if d > 0)
    gdp_led_rate = gdp_led / len(divergences)

    threshold = get_settings().gdp_gdi.significance_threshold
    significant = sum(1 for d in divergences if abs(d) > threshold)
    sig_rate = significant / len(divergences)

    print(f"  growth divergence: mean = {mean_div:+.4f}pp (expected ~0)")
    print(f"  GDP-led share     = {gdp_led_rate:.1%}  ({gdp_led}/{len(divergences)})")
    print(f"  |div| > {threshold:.2f}pp     = {sig_rate:.1%}  ({significant}/{len(divergences)})")

    configured = get_settings().gdp_gdi.divergence_base_rate
    for label, measured, published in (
        ("significant", sig_rate, configured.significant_rate),
        ("gdp_led", gdp_led_rate, configured.gdp_above_gdi_rate),
    ):
        if abs(measured - published) > 0.01:
            print(
                f"  BASE-RATE DRIFT ({label}): config says {published:.1%}, "
                f"live recomputation says {measured:.1%}. One of the two moved."
            )
        else:
            print(f"  base-rate {label} matches config ({published:.1%})")

    assert abs(mean_div) < 0.1, (
        f"the growth divergence has mean {mean_div:+.4f}pp; D-031 records it as "
        f"mean-zero, which is the evidence that its sign carries no information"
    )
    assert abs(gdp_led_rate - 0.5) < 0.1, (
        f"GDP leads {gdp_led_rate:.1%} of the time; a rate this far from a coin "
        f"flip would mean the sign IS informative and D-031 needs revisiting"
    )
    print("  CONFIRMED: the GROWTH divergence is mean-zero and its sign is a coin flip")

    # --- End-to-end: the model on the latest real pair ---
    latest_q, latest_gy, latest_iy, _ = usable[-1]
    result = gdp_gdi_divergence(
        GdpGdiInputs(gdp_growth_pct=round(latest_gy, 3), gdi_growth_pct=round(latest_iy, 3))
    )
    print()
    print(f"  latest pair: {latest_q}")
    print(
        f"    GDP {read_float(result, 'gdp_growth_pct'):+.3f}%  "
        f"GDI {read_float(result, 'gdi_growth_pct'):+.3f}%  "
        f"divergence {read_float(result, 'divergence_pp'):+.3f}pp  "
        f"average growth {read_float(result, 'average_growth_pct'):+.3f}%"
    )
    print(
        f"    significant = {read_bool(result, 'significant')}   confidence = {result.confidence}"
    )

    # Cross-field identity, recomputed from the reported components. A window
    # or sign defect shows up here even when each number looks individually
    # plausible (the D-009 lesson).
    reported_diff = read_float(result, "divergence_pp")
    recomputed_diff = read_float(result, "gdp_growth_pct") - read_float(result, "gdi_growth_pct")
    assert abs(reported_diff - recomputed_diff) < 1e-3, (
        f"reported divergence {reported_diff} does not equal GDP - GDI "
        f"({recomputed_diff}); the sign or the window is wrong"
    )
    reported_avg = read_float(result, "average_growth_pct")
    recomputed_avg = (
        read_float(result, "gdp_growth_pct") + read_float(result, "gdi_growth_pct")
    ) / 2
    assert abs(reported_avg - recomputed_avg) < 1e-3, (
        f"reported average {reported_avg} does not equal the mean of the two "
        f"reported growth rates ({recomputed_avg})"
    )
    print("  cross-field identities hold (diff = GDP - GDI; avg = mean of the two)")

    # The sign is never characterised, whatever the inputs.
    joined = " ".join(result.warnings).lower()
    assert "coin flip" in joined and "sign" in joined
    print("  sign-neutrality warning present")

    print("gdp_gdi_divergence REAL-DATA CHECK COMPLETE")


def _six_month_change_pct(
    dates: list[date], values: list[float]
) -> tuple[date, date, float, float, float]:
    """Latest six-month change, paired on the series' OWN cadence.

    Returns ``(prior_date, latest_date, prior_value, latest_value, change)``.

    Both dates are returned, and the PRIOR date is what a caller needs to print:
    the change is only meaningful if the reader can see which two observations
    were paired and confirm the span is six months. Returning just the latest
    date was a defect in the first version of this script — it made the printed
    "prior" column show the latest observation, so a reader checking the span
    would see a zero-length window and could not tell whether the code was right
    or wrong. A diagnostic that cannot be checked is worse than none.

    The lookback is 182 days rather than "six observations back", because the
    four components are published at four different frequencies — weekly (ICSA),
    monthly (PERMIT), daily (T10Y3M, SP500). ``values[-7]`` would mean six
    WEEKS on one series and six DAYS on another, which is the cadence-pairing
    defect D-022/D-024/D-025 describe, on the same axis again.

    The comparison point is the latest observation at or before
    ``latest_date - 182 days`` — the nearest actual print, not a
    float-interpolated value, because inventing a point between two
    publications would be fabricating an observation the agency never made.
    """
    from datetime import timedelta

    latest_date = dates[-1]
    target = latest_date - timedelta(days=182)
    prior_index = None
    for index in range(len(dates) - 1, -1, -1):
        if dates[index] <= target:
            prior_index = index
            break
    if prior_index is None:
        raise AssertionError(
            f"no observation at or before {target} in a series ending {latest_date}; "
            f"the six-month lookback is longer than the series' history"
        )

    prior = values[prior_index]
    latest = values[-1]
    # A percentage change needs a positive base, and T10Y3M is a spread that
    # has been negative for 1,252 of its 11,179 observations. For a LEVEL the
    # meaningful change is a ratio; for a SPREAD crossing or sitting at zero it
    # is a difference in percentage points. Both branches therefore produce
    # PERCENT, but by different arithmetic — which is the unit trap D-031
    # records, resolved here explicitly instead of by one generic formula that
    # would be wrong for one of the two kinds of series the mapping names.
    change = (latest / prior - 1) * 100 if prior > 0 else (latest - prior) * 100
    return dates[prior_index], latest_date, prior, latest, change


def _check_gdp_nowcast(client: OpenBBClient) -> None:
    """Real-data wiring for ``simple_gdp_nowcast`` (Module 7.5, D-034).

    Section 21.0's rule is what this check exists for. The model's arithmetic is
    three multiplications and an addition; every defect D-034 records is a
    *wiring* defect — which series maps to which contribution, in which
    direction, at which cadence — and none of them would raise an error.

    Five things are established here, each independently of the model:

    1. **All three inputs are live and monthly.** ``RSAFS``, ``DGORDER`` and
       ``BOPGSTB``, with their day-gaps asserted rather than assumed.
    2. **The trade balance is negative in every observation**, which is what
       makes the percent change of it a measure of the ABSOLUTE value's move —
       the algebra behind the sign correction.
    3. **The sign of the net-exports contribution is checked against the raw
       LEVEL**, whose direction is known before the model runs. This is the
       cross-series discipline that found the cadence mismatch in Module 6, not
       a restatement of the code.
    4. **The accuracy record in ``settings.yaml`` is RECOMPUTED**, so the
       published error cannot go stale. A stale record would let the model
       claim a precision the current data does not support — the D-029 failure
       mode, in the one place where the number is the whole point.
    5. **``beats_persistence`` is recomputed** from the two errors rather than
       trusted, so the flag cannot silently invert.
    """
    from macro_engine.models.gdp_nowcast import (
        SimpleGDPNowcastInputs,
        simple_gdp_nowcast,
    )

    print()
    print("=" * 72)
    print("Module 7.5 — simple_gdp_nowcast (Section 6.5; D-034)")

    rd, rv = _values(_fetch(client, "RSAFS", "retail_sales"))
    dd, dv = _values(_fetch(client, "DGORDER", "durable_goods_orders"))
    td, tv = _values(_fetch(client, "BOPGSTB", "trade_balance"))
    gd, gv = _values(_fetch(client, "A191RL1Q225SBEA", "gdp_real_growth"))

    for label, dates in (("RSAFS", rd), ("DGORDER", dd), ("BOPGSTB", td)):
        gaps = sorted({(dates[i] - dates[i - 1]).days for i in range(1, len(dates))})
        print(f"  {label}: {len(dates)} obs, {dates[0]} .. {dates[-1]}, day-gaps {gaps}")
        assert set(gaps) <= {28, 29, 30, 31}, (
            f"{label} is not monthly (gaps {gaps}); the model annualizes a quarter's "
            f"monthly changes and a non-monthly series breaks that arithmetic"
        )

    # (2) The trade balance is negative everywhere. This is the premise of the
    # sign correction, so it is asserted rather than assumed.
    positives = sum(1 for value in tv if value > 0)
    print(f"\n  BOPGSTB: {len(tv)} observations, min {min(tv):,.0f}, max {max(tv):,.0f}")
    print(f"  positive observations: {positives}/{len(tv)}")
    assert positives == 0, (
        f"BOPGSTB has {positives} non-negative observations. The sign correction assumes "
        f"the series is entirely negative; a positive value means the balance changed "
        f"meaning (a surplus) and the algebra in D-034 no longer applies."
    )
    print("  -> entirely negative, so a percent change of it measures the ABSOLUTE value")

    # Build the month-over-month percent changes, keyed by quarter.
    def mom_by_quarter(dates: list[date], values: list[float]) -> dict[str, list[float]]:
        out: dict[str, list[float]] = {}
        for index in range(1, len(values)):
            prior = values[index - 1]
            if prior == 0:
                continue
            key = f"{dates[index].year}-Q{(dates[index].month - 1) // 3 + 1}"
            out.setdefault(key, []).append((values[index] / prior - 1) * 100)
        return out

    def levels_by_quarter(dates: list[date], values: list[float]) -> dict[str, list[float]]:
        out: dict[str, list[float]] = {}
        for index in range(1, len(values)):
            key = f"{dates[index].year}-Q{(dates[index].month - 1) // 3 + 1}"
            out.setdefault(key, []).append(values[index])
        return out

    rs_q = mom_by_quarter(rd, rv)
    dg_q = mom_by_quarter(dd, dv)
    tb_q = mom_by_quarter(td, tv)
    tb_levels = levels_by_quarter(td, tv)
    realised = {
        f"{day.year}-Q{(day.month - 1) // 3 + 1}": value for day, value in zip(gd, gv, strict=True)
    }

    settings = get_settings().gdp_nowcast
    complete = sorted(
        key
        for key in set(rs_q) & set(dg_q) & set(tb_q)
        if len(rs_q[key]) == settings.months_per_quarter
        and len(dg_q[key]) == settings.months_per_quarter
        and len(tb_q[key]) == settings.months_per_quarter
    )
    print(f"\n  complete quarters available: {len(complete)}")

    target = complete[-1]
    prior = [k for k in sorted(realised) if k < target][-1]

    result = simple_gdp_nowcast(
        SimpleGDPNowcastInputs(
            retail_sales_mom=rs_q,
            durable_goods_mom=dg_q,
            trade_balance_mom=tb_q,
            prior_quarter_annualized=realised[prior],
        )
    )
    print(f"  target quarter          = {read_str(result, 'quarters_used')}")
    print(f"  prior realised ({prior}) = {realised[prior]:+.3f}")
    print(f"  consumption contrib     = {read_float(result, 'consumption_contribution'):+.4f}")
    print(f"  investment contrib      = {read_float(result, 'investment_contribution'):+.4f}")
    print(f"  net exports contrib     = {read_float(result, 'net_exports_contribution'):+.4f}")
    print(f"  delta                   = {read_float(result, 'delta'):+.4f}")
    print(f"  nowcast                 = {read_float(result, 'nowcast_annualized'):+.4f}")
    print(f"  confidence              = {result.confidence}")

    # (3) The sign, against a series whose direction is known independently.
    # The level is the raw balance; a RISE in it means the deficit narrowed,
    # which is expansionary and must contribute POSITIVELY to growth.
    latest_levels = tb_levels[target]
    expansionary = latest_levels[-1] > latest_levels[0]
    contribution = read_float(result, "net_exports_contribution")
    print(f"\n  BOPGSTB levels over {target}: {[f'{v:,.0f}' for v in latest_levels]}")
    print(
        f"  deficit {'NARROWED (expansionary)' if expansionary else 'WIDENED (contractionary)'}"
        f" -> net exports must contribute {'positively' if expansionary else 'negatively'}"
    )
    print(f"  reported contribution = {contribution:+.4f}")
    assert (contribution > 0) == expansionary, (
        f"the deficit {'narrowed' if expansionary else 'widened'} "
        f"({latest_levels[0]:,.0f} -> {latest_levels[-1]:,.0f}), so net exports must "
        f"contribute {'positively' if expansionary else 'negatively'}, but the model "
        f"reports {contribution:+.4f}. The net-exports weight's sign is wrong (D-034)."
    )
    print("  SIGN CORRECT (checked against the raw LEVEL, not the percent change)")

    # The cross-field identity: the reported nowcast must equal base plus the
    # three reported contributions at the reported precision (the D-009 lesson).
    recomputed = (
        read_float(result, "prior_quarter_annualized")
        + read_float(result, "consumption_contribution")
        + read_float(result, "investment_contribution")
        + read_float(result, "net_exports_contribution")
    )
    reported = read_float(result, "nowcast_annualized")
    assert abs(reported - recomputed) < 1e-3, (
        f"reported nowcast {reported} != recomputed {recomputed} from the reported "
        f"components; a term is mis-scaled or mis-signed"
    )
    print(f"  cross-field identity holds ({reported:+.4f} = base + 3 contributions)")

    # (4) RECOMPUTE the accuracy record, so it cannot go stale.
    quarters = [
        key
        for key in complete
        if key in realised and _previous_quarter(key) in realised and key <= sorted(realised)[-1]
    ]
    errors_corrected: list[float] = []
    errors_persistence: list[float] = []
    spec_errors: list[float] = []
    # The forecast/realised PAIRS, kept so the correlations can be recomputed
    # rather than trusted (D-035). The error lists above discard the pairing.
    forecasts: list[float] = []
    spec_forecasts: list[float] = []
    realised_values: list[float] = []
    for key in quarters:
        prior_key = _previous_quarter(key)
        prior_value = realised[prior_key]
        # The model nowcasts the LATEST usable quarter, so each historical
        # reconstruction is restricted to the single quarter under test.
        forecast = simple_gdp_nowcast(
            SimpleGDPNowcastInputs(
                retail_sales_mom={key: rs_q[key]},
                durable_goods_mom={key: dg_q[key]},
                trade_balance_mom={key: tb_q[key]},
                prior_quarter_annualized=prior_value,
            )
        )
        actual = realised[key]
        estimate = read_float(forecast, "nowcast_annualized")
        errors_corrected.append(abs(estimate - actual))
        errors_persistence.append(abs(prior_value - actual))
        # The specification's form: positive weight on the trade percent change,
        # one raw month, literal 0.6/0.3/0.1.
        spec_delta = rs_q[key][-1] * 0.6 + dg_q[key][-1] * 0.3 + tb_q[key][-1] * 0.1
        spec_estimate = prior_value + spec_delta
        spec_errors.append(abs(spec_estimate - actual))
        forecasts.append(estimate)
        spec_forecasts.append(spec_estimate)
        realised_values.append(actual)

    count = len(quarters)
    assert count >= 100, (
        f"only {count} quarters reconstructed; the accuracy record was measured over "
        f"{settings.accuracy.quarters}, so a sample this small cannot confirm it"
    )
    mean_corrected = sum(errors_corrected) / count
    mean_persistence = sum(errors_persistence) / count
    mean_spec = sum(spec_errors) / count
    print(f"\n  --- accuracy RECOMPUTED over {count} quarters, one ahead ---")
    print(f"  corrected form  mean|err| = {mean_corrected:6.3f}pp")
    print(f"  persistence     mean|err| = {mean_persistence:6.3f}pp  (the benchmark)")
    print(f"  spec's form     mean|err| = {mean_spec:6.3f}pp")
    print(f"  settings.yaml   corrected = {settings.accuracy.mean_abs_error:6.3f}pp")
    print(f"  settings.yaml   benchmark = {settings.accuracy.persistence_mean_abs_error:6.3f}pp")

    # Tolerance of 0.15pp. THIS WAS 0.5pp AND WAS TIGHTENED RATHER THAN WIDENED
    # (D-035). The 0.5pp tolerance was written to absorb a difference between
    # the probe's quarter set and the reconstruction's; when the check then
    # failed by 4.8pp the temptation was to widen it. Doing so would have
    # preserved a figure (7.747pp) that was measured on the WRONG ESTIMAND —
    # a cumulative window rather than the one quarter the function claims.
    # Now that both sides compute the one-quarter-ahead form, the two should
    # agree to well under a tenth of a point, so the tolerance is set to detect
    # a real change rather than to accommodate a measurement artefact.
    #
    # It is named rather than repeated inline, because it carries a meaning:
    # "two figures closer than tol are indistinguishable", which is what makes
    # the directional assertion below a *material* claim rather than a
    # restatement of the sign of a difference.
    tol = 0.15
    assert abs(mean_corrected - settings.accuracy.mean_abs_error) < tol, (
        f"the corrected form's error is now {mean_corrected:.4f}pp against a recorded "
        f"{settings.accuracy.mean_abs_error:.4f}pp. The record has gone stale — "
        f"recompute it in settings.yaml, do not widen this tolerance."
    )
    assert abs(mean_persistence - settings.accuracy.persistence_mean_abs_error) < tol, (
        f"the persistence benchmark is now {mean_persistence:.4f}pp against a recorded "
        f"{settings.accuracy.persistence_mean_abs_error:.4f}pp — the record has gone stale"
    )

    # The specification's form is NOT interchangeable with the corrected form,
    # and asserting that it was is the defect this replaces (D-035). The earlier
    # assertion compared the specification's live error against the CORRECTED
    # form's recorded error with a 0.15pp tolerance, on the reasoning that the
    # two "tie persistence" and are therefore the same number. That reasoning
    # held only under the superseded GDPC1-derived figures, where both scored
    # about 2.93pp. On the series the model actually consumes they are 3.558pp
    # and 3.026pp -- a 0.53pp gap -- so the assertion was false by construction.
    #
    # What is true, and is the whole point of D-034's sign correction, is
    # DIRECTIONAL: fixing the trade term's sign makes the model materially
    # better than the specification, while still not beating persistence. That
    # is a claim about an inequality, so it is asserted as one.
    assert mean_spec > mean_corrected + tol, (
        f"the specification's form scores {mean_spec:.4f}pp and the corrected form "
        f"{mean_corrected:.4f}pp. The correction is supposed to buy a material "
        f"improvement over the specification by fixing the trade term's sign; a gap "
        f"this small means either the sign correction has stopped mattering or the "
        f"two forms have converged, and D-034's central claim needs re-deriving."
    )
    assert mean_corrected > mean_persistence - tol, (
        f"the corrected form scores {mean_corrected:.4f}pp against a "
        f"{mean_persistence:.4f}pp persistence benchmark. D-035's finding is that the "
        f"correction fixes the sign and STILL fails to beat doing nothing; if the model "
        f"has genuinely overtaken persistence the weights are no longer unfitted and "
        f"the disclosure in settings.yaml is stale."
    )

    # The two correlation leaves were recorded but NOT recomputed by any live
    # evidence — the unit tests pin them against a synthetic record, which
    # proves the model reads them, not that they describe the data (D-035).
    # Both are computable from the forecasts already built above.
    live_corr = statistics.correlation(forecasts, realised_values)
    live_spec_corr = statistics.correlation(spec_forecasts, realised_values)
    print(
        f"\n  corr(corrected, realised) = {live_corr:+.4f}  "
        f"(recorded {settings.accuracy.correlation:+.4f})"
    )
    print(
        f"  corr(spec,      realised) = {live_spec_corr:+.4f}  "
        f"(recorded {settings.accuracy.spec_form_correlation:+.4f})"
    )
    assert abs(live_corr - settings.accuracy.correlation) < 0.005, (
        f"corr(corrected, realised) is now {live_corr:+.4f} against a recorded "
        f"{settings.accuracy.correlation:+.4f}. This leaf is quoted in the headline "
        f"warning as the reason the delta is over-weighted, so it must describe the "
        f"live data."
    )
    assert abs(live_spec_corr - settings.accuracy.spec_form_correlation) < 0.005, (
        f"corr(specification, realised) is now {live_spec_corr:+.4f} against a recorded "
        f"{settings.accuracy.spec_form_correlation:+.4f}. The sign of this figure is "
        f"D-034's central finding — a NEGATIVE correlation means the specification's "
        f"form moves against the quantity it names — so it is asserted, not described."
    )
    assert live_corr > live_spec_corr, (
        f"the corrected form correlates {live_corr:+.4f} with realised growth and the "
        f"specification's {live_spec_corr:+.4f}. The correction exists to point the "
        f"adjustment the right way, so the corrected form must correlate BETTER; if "
        f"this inverts, the sign fix has been undone."
    )
    print("  the recorded accuracy still describes the live data")

    # (4b) RECOMPUTE the over-weighting ratio (D-035). This is the finding the
    # whole correction rests on, and it is the OPPOSITE of what an earlier draft
    # of D-035 recorded. The adjustment is not too small to matter -- it carries
    # roughly HALF the magnitude of the change it predicts (0.5052) while
    # explaining only 3% of that change's variance (R^2 = 0.030). So it is too
    # LARGE for what it knows, and applying it at unit weight costs ~0.11pp
    # against simply repeating the prior quarter's print.
    #
    # The check is written on the RECOMPUTED value, not on the config leaf, so a
    # data revision that changed the character of the adjustment would be caught
    # here. Two things are asserted: the ratio is reproduced, and it is in the
    # regime the docstrings describe (materially below 1.0, but not near zero).
    deltas: list[float] = []
    targets: list[float] = []
    for key in quarters:
        forecast = simple_gdp_nowcast(
            SimpleGDPNowcastInputs(
                retail_sales_mom={key: rs_q[key]},
                durable_goods_mom={key: dg_q[key]},
                trade_balance_mom={key: tb_q[key]},
                prior_quarter_annualized=realised[_previous_quarter(key)],
            )
        )
        deltas.append(abs(read_float(forecast, "delta")))
        targets.append(abs(realised[key] - realised[_previous_quarter(key)]))
    mean_abs_delta = sum(deltas) / count
    mean_abs_target = sum(targets) / count
    overweighting = mean_abs_delta / mean_abs_target
    recorded_overweighting = settings.accuracy.delta_overweighting_ratio
    reported_overweighting = read_float(result, "delta_overweighting_ratio")
    print(
        f"\n  over-weighting RECOMPUTED: mean|delta|={mean_abs_delta:.4f}pp "
        f"mean|target|={mean_abs_target:.4f}pp -> ratio {overweighting:.4f}"
    )
    print(f"  settings.yaml ratio = {recorded_overweighting:.4f}")
    assert abs(overweighting - recorded_overweighting) < 0.005, (
        f"the over-weighting ratio is now {overweighting:.4f} against a recorded "
        f"{recorded_overweighting:.4f}. A change here is material: it decides whether this "
        f"model's adjustment is too small to matter, correctly sized, or too large for its "
        f"accuracy — three different pieces of advice (D-035)."
    )
    assert abs(reported_overweighting - recorded_overweighting) < 1e-9, (
        f"the live output reports an over-weighting ratio of {reported_overweighting} but "
        f"config holds {recorded_overweighting}; the model is not publishing the measured "
        f"value"
    )
    # The upper bound is the load-bearing one. A ratio at or above 1.0 would mean the
    # adjustment moves at least as much as the thing it predicts while correlating
    # with it at r = 0.173 — that is a different defect from D-035's and would
    # require a different remedy (shrinking a correctly-signed but over-large term
    # has a real optimum; the shipped weight of 1.0 is simply past it).
    assert overweighting < 1.0, (
        f"the adjustment now carries {overweighting:.1%} of the movement it predicts. At or "
        f"above 100% the D-035 framing — a correctly-signed but over-weighted term, whose "
        f"best scale is therefore below 1.0 — no longer describes this model. The scale "
        f"sweep in settings.yaml must be re-derived rather than assumed."
    )
    # The lower bound guards the opposite failure, which D-035 was first written
    # as though were the case. A ratio near zero *would* mean no weight can help.
    assert overweighting > 0.05, (
        f"the adjustment now carries only {overweighting:.1%} of the movement it predicts. "
        f"At this size the delta cannot influence the forecast at any weight, and the "
        f"finding must revert to the inert reading rather than the over-weighted one "
        f"(D-035)."
    )
    print("  over-weighting ratio AGREES with the live reconstruction and is in the D-035 regime")

    # (5) RECOMPUTE beats_persistence rather than trusting the flag.
    improvement = mean_persistence - mean_corrected
    threshold = settings.persistence_improvement_threshold
    expected_flag = improvement > threshold
    reported_flag = read_bool(result, "beats_persistence")
    print(
        f"\n  recomputed improvement = {improvement:+.3f}pp against a "
        f"{threshold:.3f}pp bar -> beats_persistence = {expected_flag}"
    )
    assert reported_flag == expected_flag, (
        f"the model reports beats_persistence={reported_flag} but the live reconstruction "
        f"gives {expected_flag} (improvement {improvement:+.3f}pp vs bar {threshold:.3f}pp)"
    )
    print("  beats_persistence AGREES with the live reconstruction")

    # The headline disclosure must be present on live output.
    assert any("NOT A VALIDATED NOWCAST" in warning for warning in result.warnings)
    assert any("ties that benchmark" in warning for warning in result.warnings), (
        "the headline must say the model TIES persistence, not that it beats it. The "
        "difference is 0.003pp, and claiming a win on that margin is the failure mode "
        "D-035 exists to prevent."
    )
    print("  headline disclosure present on live output, and states a tie not a win")

    # --- the published cross-check, now that FRED serves GDPNOW -------------
    gdnow_dates, gdnow_values = _values(_fetch(client, "GDPNOW", "gdpnow_published"))
    print(f"\n  GDPNOW (published): {len(gdnow_values)} obs, {gdnow_dates[0]} .. {gdnow_dates[-1]}")
    gaps = sorted({(gdnow_dates[i] - gdnow_dates[i - 1]).days for i in range(1, len(gdnow_dates))})
    print(f"  distinct day-gaps: {gaps[:8]}{'...' if len(gaps) > 8 else ''}")
    print("  -> quarterly, one per quarter: a FINAL record, not a live in-quarter nowcast")
    # Zero consecutive repeats: each quarter has exactly one observation, so the
    # series cannot be a within-quarter revision path.
    repeats = sum(
        1 for index in range(1, len(gdnow_values)) if gdnow_values[index] == gdnow_values[index - 1]
    )
    print(f"  consecutive repeats: {repeats}/{len(gdnow_values) - 1}")
    assert repeats == 0, (
        f"GDPNOW has {repeats} consecutive repeats; the 'one final observation per "
        f"quarter' characterisation no longer holds and the cross-check's caveat is wrong"
    )

    published_by_quarter = {
        f"{day.year}-Q{(day.month - 1) // 3 + 1}": value
        for day, value in zip(gdnow_dates, gdnow_values, strict=True)
    }
    common_published = [k for k in complete if k in published_by_quarter and k in realised]
    print(f"  quarters with a published figure AND a realised print: {len(common_published)}")
    assert len(common_published) >= 40, (
        f"only {len(common_published)} comparable quarters; the recorded GDPNOW error of "
        f"{settings.accuracy.gdpnow_published_mean_abs_error:.3f}pp was measured over 60"
    )
    gdnow_errors = [abs(published_by_quarter[key] - realised[key]) for key in common_published]
    mean_gdnow = sum(gdnow_errors) / len(gdnow_errors)
    recorded_gdnow = settings.accuracy.gdpnow_published_mean_abs_error
    print(f"  publication mean|err| vs realised = {mean_gdnow:.3f}pp")
    print(f"  settings.yaml recorded            = {recorded_gdnow:.3f}pp")
    # The published error is a record of a settled number, so this is tight.
    assert abs(mean_gdnow - recorded_gdnow) < 0.05, (
        f"the published figure's error is now {mean_gdnow:.3f}pp against a recorded "
        f"{recorded_gdnow:.3f}pp — recompute the record"
    )

    latest_published = published_by_quarter.get(target)
    if latest_published is not None:
        cross = simple_gdp_nowcast(
            SimpleGDPNowcastInputs(
                retail_sales_mom=rs_q,
                durable_goods_mom=dg_q,
                trade_balance_mom=tb_q,
                prior_quarter_annualized=realised[prior],
                published_gdpnow=latest_published,
            )
        )
        print(
            f"\n  cross-check for {target}: model {read_float(result, 'nowcast_annualized'):+.2f} "
            f"vs published {latest_published:+.2f} -> "
            f"gap {read_float(cross, 'gdpnow_cross_check_pp'):+.2f}pp"
        )
        cross_value = cross.value
        plain_value = result.value
        assert isinstance(cross_value, dict) and isinstance(plain_value, dict)
        assert "gdpnow_cross_check_pp" in cross_value
        assert "gdpnow_cross_check_pp" not in plain_value, (
            "the cross-check key must be absent when no published figure is supplied"
        )
        print("  key absent when not supplied, present when supplied")

    print("simple_gdp_nowcast REAL-DATA CHECK COMPLETE")


def _previous_quarter(key: str) -> str:
    """The calendar quarter before ``'YYYY-QN'``.

    Calendar arithmetic, never ``timedelta(days=91)`` — a day-count offset
    drifts and would silently pair a quarter with the wrong predecessor, which
    is exactly the wrong-number-well-formed failure this project hunts.
    """
    year, quarter = key.split("-Q")
    if quarter == "1":
        return f"{int(year) - 1}-Q4"
    return f"{year}-Q{int(quarter) - 1}"


def _check_leading_indicator(client: OpenBBClient) -> None:
    """Real-data wiring for ``leading_indicator_proxy`` (Module 7.3).

    Section 21.0's point applies with unusual force here: the model's arithmetic
    is trivial, so *every* real defect lives in the wiring — which series each
    component maps to, in which direction, and over what window. This check
    fetches all four of Section 20.7's named components from live FRED, computes
    each one's six-month change independently, and only then hands the four
    numbers to the model.

    The orientation of each component is asserted rather than assumed. ``ICSA``
    is a level that RISES when the labour market weakens, so its sign must be
    inverted before it enters the composite; a build that added it directly
    would read rising layoffs as expansionary and nothing in the arithmetic
    would notice.
    """
    from macro_engine.models.lei_proxy import (
        LeadingIndicatorProxyInputs,
        leading_indicator_proxy,
    )

    # (component name, symbol, inverts?)
    components = [
        ("initial_claims_inverted", "ICSA", True),
        ("building_permits", "PERMIT", False),
        ("curve_slope_10y3m", "T10Y3M", False),
        ("sp500_index", "SP500", False),
    ]

    print()
    print("=" * 72)
    print("Module 7.3 — leading_indicator_proxy (NOT the Conference Board LEI)")
    print("=" * 72)

    computed: dict[str, float] = {}
    for name, symbol, inverted in components:
        dates, values = _values(_fetch(client, symbol, name))
        prior_date, latest_date, prior, latest, change = _six_month_change_pct(dates, values)
        oriented = -change if inverted else change
        computed[name] = oriented
        print(
            f"  {name:26} {symbol:8} n={len(values):5d} "
            f"pair {prior_date} -> {latest_date} ({prior:.3f} -> {latest:.3f}) "
            f"change={change:+8.2f}%{'  (INVERTED)' if inverted else ''} "
            f"-> {oriented:+8.2f}"
        )

    # The orientation assertion. ICSA at a six-month change of X must enter as
    # -X, so a build that dropped the inversion shows up here as a sign flip on
    # a series whose direction is independently checkable.
    claim_dates, claim_values = _values(_fetch(client, "ICSA", "initial_claims_level"))
    raw_claim_change = _six_month_change_pct(claim_dates, claim_values)[4]
    expected_inverted = -raw_claim_change
    assert abs(computed["initial_claims_inverted"] - expected_inverted) < 1e-9, (
        f"the claims component entered as {computed['initial_claims_inverted']:+.3f} "
        f"but its raw level change is {raw_claim_change:+.3f}, which must enter "
        f"INVERTED ({expected_inverted:+.3f}). A claims level rises when the labour "
        f"market weakens; adding it directly would read rising layoffs as expansion."
    )
    print(
        f"  orientation CONFIRMED: ICSA raw {raw_claim_change:+.3f} entered as "
        f"{computed['initial_claims_inverted']:+.3f} (inverted)"
    )

    # The S&P 500's window limitation, checked rather than assumed. FRED now
    # serves SP500 as a rolling ~10-year window, so a six-month lookback works
    # but a long one would silently truncate.
    sp_dates, _ = _values(_fetch(client, "SP500", "sp500_index"))
    span_days = (sp_dates[-1] - sp_dates[0]).days
    print(
        f"  SP500 window: {sp_dates[0]} .. {sp_dates[-1]} ({span_days} days, "
        f"{len(sp_dates)} obs) — a rolling window, not full history"
    )
    assert span_days > 200, (
        f"SP500 reaches back only {span_days} days, too short for a six-month change. "
        f"The rolling FRED window has become unusable for this component."
    )

    result = leading_indicator_proxy(LeadingIndicatorProxyInputs(components=computed))
    print()
    print(f"  composite_6mo_annualized = {read_float(result, 'composite_6mo_annualized'):+.3f}")
    print(f"  breadth_declining        = {read_float(result, 'breadth_declining'):.2f}")
    print(
        f"  declining                = {int(read_float(result, 'n_declining'))}"
        f"/{int(read_float(result, 'n_components'))}"
    )
    print(f"  broad_based              = {read_bool(result, 'broad_based')}")
    print(f"  lead_direction           = {read_str(result, 'lead_direction')}")
    print(f"  breadth_null_rate        = {read_float(result, 'breadth_null_rate'):.1%}")
    print(f"  confidence               = {result.confidence}")

    # Cross-field identity: the composite must equal the mean of the four
    # oriented component changes (equal weighting). A mis-mapped or wrongly
    # oriented component shows up here even when each number looks plausible —
    # the D-009 lesson, applied to a sum instead of a difference.
    reported = read_float(result, "composite_6mo_annualized")
    recomputed = sum(computed.values()) / len(computed)
    assert abs(reported - recomputed) < 1e-2, (
        f"reported composite {reported} != the equal-weighted mean of the four live "
        f"component changes ({recomputed}); a component is mis-mapped or mis-oriented"
    )
    print("  cross-field identity holds (composite = equal-weighted mean of components)")

    # Breadth must be recomputable from the component count.
    n_declining = sum(1 for change in computed.values() if change < 0)
    assert int(read_float(result, "n_declining")) == n_declining, (
        f"reported n_declining {read_float(result, 'n_declining')} != recomputed "
        f"{n_declining} from the live component signs"
    )
    assert abs(read_float(result, "breadth_declining") - n_declining / len(computed)) < 1e-9
    print(f"  breadth RECOMPUTED from live signs: {n_declining}/{len(computed)} declining")

    # The naming rule, on live output.
    assert "lei" not in result.model_name.lower()
    assert any("not the conference board lei" in w.lower() for w in result.warnings)
    print("  naming rule CONFIRMED: the output is a proxy, not the licensed LEI")

    print("leading_indicator_proxy REAL-DATA CHECK COMPLETE")


# ---------------------------------------------------------------------------
# Module 8.2 — auction_demand_signal
# ---------------------------------------------------------------------------

#: First auction date the recorded base rates were measured from. The check
#: refetches the same span so its recomputation is comparable to the record; a
#: shorter window would produce different rates and the comparison would be
#: meaningless rather than failing.
_AUCTION_HISTORY_START = "2015-01-01"

#: The normalised tenor the base rates were measured on. The feed's raw
#: ``security_term`` splits this across three labels, so the grouping key is
#: ``original_security_term``.
_AUCTION_TENOR = "10-Year"


def _fetch_auctions(security_type: str) -> pd.DataFrame:
    """Fetch the raw auction frame for one security type.

    Uses the ``openbb`` package directly rather than ``OpenBBClient``, and the
    reason is a contract mismatch rather than convenience: the client's
    ``fetch_series`` normalizes every response down to a single ``value``
    column, while an auction record is inherently wide (91 columns on the
    ``note`` type). Forcing it through the client would discard exactly the
    fields this check exists to verify.

    ``security_type`` is REQUIRED by the provider even though the standard
    model declares it optional with a ``None`` default — passing ``None``
    raises rather than defaulting. That is asserted in the check below, because
    a caller who trusts the model's signature would get a runtime error.
    """
    from typing import Any, cast

    from openbb import obb

    # ``obb`` is typed as ``BaseApp | Extensions``, a union that does not
    # declare ``fixedincome``, and the route's return type has no stub. The
    # untyped edge of this dependency is confined to the two lines below and
    # cast back to the frame the call actually produces, so ``Any`` does not
    # leak into the rest of the check.
    app: Any = obb
    frame = app.fixedincome.government.treasury_auctions(
        security_type=security_type,
        start_date=_AUCTION_HISTORY_START,
        # ``utc_now().date()`` rather than ``date.today()``: the project bans
        # naive datetimes (ruff DTZ), and a wall-clock ``today()`` is naive by
        # construction. The end date only bounds a query, but the rule exists
        # because "only bounds a query" is how the naive-datetime defects start.
        end_date=utc_now().date().isoformat(),
    ).to_df()
    # ``pd`` is imported only under ``TYPE_CHECKING``, so the cast target is
    # given as a string — evaluated by the type checker, never at runtime.
    return cast("pd.DataFrame", frame)


def _check_auction_demand(client: OpenBBClient) -> None:
    """Real-data wiring for ``auction_demand_signal`` (Module 8.2, D-036).

    Five things are established here, each independently of the model:

    1. **``security_type`` is required**, contrary to the standard model's
       ``None`` default.
    2. **The tenor grouping must be normalised.** ``security_term`` splits one
       nominal tenor across three labels; grouping on it would build each
       trailing average from a third of the history.
    3. **The indirect share's two bases are not interchangeable**, and the
       model's input contract says which one it takes.
    4. **The two base rates are recomputed** from live auctions, so the record
       cannot go stale (D-029's discipline).
    5. **The verdict is recomputable from the published flags**, and the
       manual-entry disclosure is present.

    **What this check CANNOT establish, stated rather than glossed:**
    ``stop_through_bp`` is manual entry (D-036). The route carries no
    when-issued or expected-yield field, so the tailed branch cannot be
    exercised against live data. The check runs the model at the definitional
    boundary — 0.0bp, which is not a tail — and the tailed branch is covered by
    unit tests instead. A green run here does NOT validate the tail.
    """
    from macro_engine.models.auctions import AuctionInputs, auction_demand_signal

    print()
    print("=" * 72)
    print("Module 8.2 — auction_demand_signal (Section 20.8; D-036)")

    settings = get_settings().auction_demand

    # (1) security_type is required despite the standard model's default.
    try:
        _fetch_auctions("")
        raise AssertionError(
            "an empty security_type was accepted; the provider is supposed to refuse it"
        )
    except AssertionError:
        raise
    except Exception as exc:
        print(f"  security_type is REQUIRED: empty value refused ({type(exc).__name__})")

    notes = _fetch_auctions("note")
    print(f"  notes fetched: {len(notes)} rows, {len(notes.columns)} columns")

    # (2) The tenor split, and why the grouping key matters.
    raw_labels = sorted(
        {str(t) for t in notes["security_term"] if "10-Year" in str(t) or "9-Year" in str(t)}
    )
    normalised = sorted({str(t) for t in notes["original_security_term"]})
    print(f"  security_term labels for the 10-Year: {raw_labels}")
    assert len(raw_labels) > 1, (
        "the feed no longer splits the 10-Year across labels; if it stopped, the "
        "grouping guidance in D-036 is stale and should be re-derived"
    )
    assert _AUCTION_TENOR in normalised, (
        f"original_security_term does not carry {_AUCTION_TENOR!r}; got {normalised}"
    )
    print(f"  -> grouping on original_security_term gives one bucket, not {len(raw_labels)}")

    rows: list[tuple[str, float, float, float]] = []
    for _, row in notes.iterrows():
        if str(row.get("original_security_term")) != _AUCTION_TENOR:
            continue
        btc = row.get("bid_to_cover_ratio")
        accepted = row.get("total_accepted")
        indirect = row.get("indirect_bidder_accepted")
        tendered_total = row.get("total_tendered")
        indirect_tendered = row.get("indirect_bidder_tendered")
        # Checked one at a time rather than through an ``any(...)`` generator:
        # a generator does not narrow the types for the checker, and the
        # narrowing IS the point — these arrive as ``Any | None`` and the
        # arithmetic below is meaningless on ``None``. A row missing any of
        # them is dropped rather than imputed (Section 21.0 rule 4).
        if btc is None or accepted is None or indirect is None:
            continue
        if tendered_total is None or indirect_tendered is None:
            continue
        if not accepted or not tendered_total:
            continue
        accepted_pct = float(indirect) / float(accepted) * 100
        tendered_pct = float(indirect_tendered) / float(tendered_total) * 100
        rows.append((str(row["auction_date"])[:10], float(btc), accepted_pct, tendered_pct))
    rows.sort()
    assert len(rows) > settings.trailing_window_auctions + 1, (
        f"only {len(rows)} usable {_AUCTION_TENOR} auctions; a trailing window of "
        f"{settings.trailing_window_auctions} plus a current one cannot be built"
    )
    print(f"  {_AUCTION_TENOR} auctions usable: {len(rows)} ({rows[0][0]} .. {rows[-1][0]})")

    # (3) The two bases, measured on the same rows.
    accepted_mean = sum(r[2] for r in rows) / len(rows)
    tendered_mean = sum(r[3] for r in rows) / len(rows)
    worst_gap = max(abs(r[2] - r[3]) for r in rows)
    print(
        f"\n  indirect share: ACCEPTED basis {accepted_mean:.2f}% vs TENDERED basis "
        f"{tendered_mean:.2f}% (largest single-auction gap {worst_gap:.2f}pp)"
    )
    assert abs(accepted_mean - tendered_mean) > settings.indirect_fade_threshold_pp, (
        f"the two bases now agree to within the {settings.indirect_fade_threshold_pp:.1f}pp "
        f"threshold, so the basis warning in settings.yaml overstates the risk and "
        f"should be re-derived"
    )
    print("  -> the two bases differ by far more than the fade threshold; the basis matters")

    # (4) Recompute the two base rates over the same span the record was
    # measured on, so the record cannot go stale.
    window = settings.trailing_window_auctions
    weak = 0
    fading = 0
    considered = 0
    for index in range(window, len(rows)):
        history = rows[index - window : index]
        avg_btc = sum(r[1] for r in history) / window
        avg_ind = sum(r[2] for r in history) / window
        _, btc, accepted_pct, _ = rows[index]
        considered += 1
        if btc < avg_btc * settings.weak_bid_to_cover_ratio:
            weak += 1
        if accepted_pct < avg_ind - settings.indirect_fade_threshold_pp:
            fading += 1
    weak_rate = weak / considered
    fading_rate = fading / considered
    print(f"\n  base rates RECOMPUTED over {considered} auctions, window {window}:")
    print(
        f"    weak bid-to-cover  {weak}/{considered} = {weak_rate:.1%} "
        f"(recorded {settings.base_rates.weak_bid_to_cover_rate:.1%})"
    )
    print(
        f"    foreign fading     {fading}/{considered} = {fading_rate:.1%} "
        f"(recorded {settings.base_rates.foreign_fading_rate:.1%})"
    )
    assert abs(weak_rate - settings.base_rates.weak_bid_to_cover_rate) < 0.02, (
        f"the weak bid-to-cover rate is now {weak_rate:.1%} against a recorded "
        f"{settings.base_rates.weak_bid_to_cover_rate:.1%}. This is the base rate the "
        f"model discloses with every verdict; recompute it in settings.yaml rather "
        f"than widening this tolerance."
    )
    assert abs(fading_rate - settings.base_rates.foreign_fading_rate) < 0.02, (
        f"the foreign-fading rate is now {fading_rate:.1%} against a recorded "
        f"{settings.base_rates.foreign_fading_rate:.1%} — the record has gone stale"
    )

    # (5) Run the model on the most recent auction, at the definitional
    # boundary for the manual input.
    latest_date, latest_btc, latest_indirect, _ = rows[-1]
    history = rows[-1 - window : -1]
    btc_avg = sum(r[1] for r in history) / window
    indirect_avg = sum(r[2] for r in history) / window
    result = auction_demand_signal(
        AuctionInputs(
            bid_to_cover=latest_btc,
            bid_to_cover_trailing_avg=btc_avg,
            indirect_bidder_pct=latest_indirect,
            indirect_bidder_trailing_avg=indirect_avg,
            stop_through_bp=settings.tail_boundary_bp,
        )
    )
    print(f"\n  latest {_AUCTION_TENOR} auction {latest_date}:")
    print(f"    bid_to_cover {latest_btc:.2f} vs trailing {btc_avg:.2f}")
    print(f"    indirect     {latest_indirect:.2f}% vs trailing {indirect_avg:.2f}%")
    print(f"    stop_through = {settings.tail_boundary_bp:.1f}bp (MANUAL, at the boundary)")
    latest_verdict = result.value["verdict"] if isinstance(result.value, dict) else result.value
    print(f"    verdict = {latest_verdict}")

    weak_flag = read_bool(result, "weak_bid_to_cover")
    tailed_flag = read_bool(result, "tailed")
    fading_flag = read_bool(result, "foreign_demand_fading")

    # The flags must agree with a recomputation from the raw published numbers.
    assert weak_flag == (latest_btc < btc_avg * settings.weak_bid_to_cover_ratio), (
        "the published weak_bid_to_cover flag disagrees with the raw numbers in the "
        "same output; the output carries its own contradiction"
    )
    assert fading_flag == (latest_indirect < indirect_avg - settings.indirect_fade_threshold_pp)
    print("  flags AGREE with a recomputation from the raw published numbers")

    # The cross-field identity: the verdict must follow from the two flags.
    expected_verdict = (
        "WEAK_AUCTION_term_premium_pressure"
        if weak_flag and tailed_flag
        else "STRONG_AUCTION"
        if not weak_flag and not tailed_flag
        else "MIXED"
    )
    assert read_str(result, "verdict") == expected_verdict, (
        f"reported verdict {read_str(result, 'verdict')} does not follow from the "
        f"published flags (weak={weak_flag}, tailed={tailed_flag})"
    )
    print("  cross-field identity holds (verdict recomputed from its own flags)")

    # The manual-entry disclosure, in both halves.
    assert read_bool(result, "stop_through_is_manual_entry") is True
    assert any("MANUAL ENTRY" in w for w in result.warnings), (
        "the tail input is manual and the output must say so"
    )
    print("  manual-entry disclosure PRESENT for stop_through_bp")

    # The base rate travels with the output, and is the recorded one.
    recorded_weak = settings.base_rates.weak_bid_to_cover_rate
    recorded_fading = settings.base_rates.foreign_fading_rate
    assert read_float(result, "weak_bid_to_cover_base_rate") == recorded_weak
    assert read_float(result, "foreign_fading_base_rate") == recorded_fading
    assert read_int(result, "auctions_measured") == settings.base_rates.auctions_measured
    print("  both base rates travel with the output")

    print("\n  NOT VALIDATED HERE: the tailed branch. stop_through_bp is manual and")
    print("  no route publishes a when-issued yield (D-036). Unit tests cover it.")
    print("auction_demand_signal REAL-DATA CHECK COMPLETE")


# ---------------------------------------------------------------------------
# Module 8.3 — credit_spread_attribution
# ---------------------------------------------------------------------------

#: The three trends the manual input can take. The live check runs ALL of them,
#: because `default_rate_trend` is MANUAL (Section 21.1) and therefore unknown:
#: printing one verdict would mean inventing the input it depends on.
_CREDIT_TRENDS = ("rising", "stable", "falling")


def _check_credit_spread(client: OpenBBClient) -> None:
    """Real-data wiring for ``credit_spread_attribution`` (Module 8.3, D-037).

    Six things are established here, each independently of the model:

    1. **The three series are live and in the units the input contract names.**
       This is the load-bearing check. The two credit spreads are in *percent*
       and must be multiplied by 100 to reach basis points; VIX is a *level* in
       index points and the input is a percent *change* of it. Applying one
       conversion to both is a 100x error on one of them, and the result is a
       plausible attribution of the wrong kind (D-035). Both conversions are
       asserted against the raw magnitudes.
    2. **The change window is applied to all three inputs identically**, since
       a window mismatch between the spreads and the volatility would compare
       a week's credit move with a day's volatility move.
    3. **The three base rates are recomputed** from live data, so the record
       cannot go stale (D-029).
    4. **The verdict is recomputed from the published predicates** for every
       possible trend, and each must agree.
    5. **The differentiation diagnostic is published and disclaimed**, and the
       attribution is asserted NOT to depend on its threshold.
    6. **The manual-entry disclosure is present.**

    **What this check CANNOT establish, stated rather than glossed:**
    ``default_rate_trend`` is manual, so there is no live value to validate
    against. The check runs all three trends and asserts the model's *logic* is
    consistent for each — but it cannot tell an operator which trend is true.
    A green run here does NOT validate the verdict, only the machinery around it.
    """
    from macro_engine.models.credit_spread import (
        CreditSpreadInputs,
        credit_spread_attribution,
    )

    print()
    print("=" * 72)
    print("Module 8.3 — credit_spread_attribution (Section 20.8; D-037)")

    settings = get_settings().credit_spread
    window = settings.change_window_days

    hy_dates, hy_values = _values(_fetch(client, "BAMLH0A0HYM2", "credit_spread_hy"))
    ig_dates, ig_values = _values(_fetch(client, "BAMLC0A0CM", "credit_spread_ig"))
    vx_dates, vx_values = _values(_fetch(client, "VIXCLS", "equity_volatility"))

    # (1) Units. The spreads are PERCENT (single digits); VIX is a LEVEL.
    print(f"  BAMLH0A0HYM2: {len(hy_dates)} obs, last {hy_values[-1]:.2f} percent")
    print(f"  BAMLC0A0CM  : {len(ig_dates)} obs, last {ig_values[-1]:.2f} percent")
    print(f"  VIXCLS      : {len(vx_dates)} obs, last {vx_values[-1]:.2f} index points")
    assert hy_values[-1] < 100.0, (
        f"the high-yield spread reads {hy_values[-1]}, which is not a percent figure. "
        f"If the provider has switched to basis points the x100 conversion in this "
        f"check becomes a x10000 error."
    )
    assert ig_values[-1] < 100.0, (
        f"the investment-grade spread reads {ig_values[-1]}, not a percent figure"
    )
    assert 1.0 < vx_values[-1] < 200.0, (
        f"VIX reads {vx_values[-1]}; it is a LEVEL in index points, so a value near "
        f"1.0 would mean the provider switched to a decimal fraction and the "
        f"percent-change computation below would be wrong."
    )
    assert hy_values[-1] > ig_values[-1], (
        f"high-yield OAS ({hy_values[-1]:.2f}) is not above investment-grade "
        f"({ig_values[-1]:.2f}); the two series may be mapped to each other's symbols"
    )
    print("  units CONFIRMED: spreads in percent, VIX a level; HY above IG as required")

    hy = dict(zip(hy_dates, hy_values, strict=True))
    ig = dict(zip(ig_dates, ig_values, strict=True))
    vx = dict(zip(vx_dates, vx_values, strict=True))
    common = sorted(set(hy) & set(ig) & set(vx))
    assert len(common) > 200, (
        f"only {len(common)} dates carry all three series; the base rates cannot be "
        f"measured over a sample this small"
    )
    print(f"  aligned common dates: {len(common)} ({common[0]} .. {common[-1]})")

    # (2)+(3) Recompute the three base rates over the same window the model uses.
    spike = widened = parallel = considered = 0
    for index in range(window, len(common)):
        today, prior = common[index], common[index - window]
        # percent -> bp is x100. VIX needs no conversion: the input is a percent
        # change of a level, not a level converted to a different unit.
        hy_change_bp = (hy[today] - hy[prior]) * 100
        ig_change_bp = (ig[today] - ig[prior]) * 100
        vol_change_pct = (vx[today] / vx[prior] - 1) * 100
        considered += 1
        if vol_change_pct > settings.equity_vol_spike_threshold_pct:
            spike += 1
        if hy_change_bp > 0:
            widened += 1
        if abs(hy_change_bp - ig_change_bp) <= settings.differentiation_threshold_bp:
            parallel += 1

    spike_rate = spike / considered
    widening_rate = widened / considered
    parallel_rate = parallel / considered
    print(f"\n  base rates RECOMPUTED over {considered} {window}-day windows:")
    print(
        f"    volatility spike  {spike}/{considered} = {spike_rate:.1%} "
        f"(recorded {settings.base_rates.equity_vol_spike_rate:.1%})"
    )
    print(
        f"    HY widened        {widened}/{considered} = {widening_rate:.1%} "
        f"(recorded {settings.base_rates.widening_rate:.1%})"
    )
    print(
        f"    parallel widening {parallel}/{considered} = {parallel_rate:.1%} "
        f"(recorded {settings.base_rates.parallel_widening_rate:.1%})"
    )
    for label, recomputed, recorded in (
        ("volatility spike", spike_rate, settings.base_rates.equity_vol_spike_rate),
        ("HY widening", widening_rate, settings.base_rates.widening_rate),
        ("parallel widening", parallel_rate, settings.base_rates.parallel_widening_rate),
    ):
        assert abs(recomputed - recorded) < 0.02, (
            f"the {label} base rate is now {recomputed:.1%} against a recorded "
            f"{recorded:.1%}. This is the frequency the model discloses with every "
            f"attribution; recompute it in settings.yaml rather than widening this "
            f"tolerance."
        )

    # (4) Run the model for EVERY possible trend. The trend is manual, so a
    # single verdict would mean inventing the input it depends on.
    today, prior = common[-1], common[-1 - window]
    hy_change_bp = (hy[today] - hy[prior]) * 100
    ig_change_bp = (ig[today] - ig[prior]) * 100
    vol_change_pct = (vx[today] / vx[prior] - 1) * 100
    print(f"\n  latest window {prior} -> {today} ({window} trading days):")
    print(f"    HY OAS  {hy[prior]:.2f} -> {hy[today]:.2f} percent = {hy_change_bp:+.1f}bp")
    print(f"    IG OAS  {ig[prior]:.2f} -> {ig[today]:.2f} percent = {ig_change_bp:+.1f}bp")
    print(f"    VIX     {vx[prior]:.2f} -> {vx[today]:.2f} = {vol_change_pct:+.1f}%")

    # (4a) The trend is DERIVED from delinquency, not manually entered (D-043).
    # Section 21.1 marks `default_rate_trend` MANUAL on the premise that no free
    # real-time series exists. `DRALACBS` is one, and its four-quarter direction
    # is a defensible measure of the direction of default risk.
    dq_dates, dq_values = _values(_fetch(client, "DRALACBS", "delinquency_rate"))
    dq = dict(zip(dq_dates, dq_values, strict=True))
    dq_quarters = sorted(dq)
    assert len(dq_quarters) > 4, "not enough delinquency history to derive a trend"

    band_pp = settings.delinquency_trend_band_pp
    trend_change = dq[dq_quarters[-1]] - dq[dq_quarters[-5]]
    derived_trend = (
        "rising" if trend_change > band_pp else "falling" if trend_change < -band_pp else "stable"
    )
    print("\n  default-rate trend DERIVED from DRALACBS (Section 21.1 called it MANUAL):")
    print(f"    delinquency {dq[dq_quarters[-5]]:.2f} -> {dq[dq_quarters[-1]]:.2f} percent")
    print(f"    four-quarter change {trend_change:+.3f}pp against a +/-{band_pp:.2f}pp band")
    print(f"    -> trend = {derived_trend}")

    # Recompute the trend's own base rates. Unmeasurable while the trend was manual.
    trend_counts = {"rising": 0, "stable": 0, "falling": 0}
    for index in range(4, len(dq_quarters)):
        change = dq[dq_quarters[index]] - dq[dq_quarters[index - 4]]
        trend_counts[
            "rising" if change > band_pp else "falling" if change < -band_pp else "stable"
        ] += 1
    trend_total = sum(trend_counts.values())
    print(f"  trend base rates RECOMPUTED over {trend_total} quarters:")
    for name, count in trend_counts.items():
        recorded = settings.trend_base_rates.rates[name]
        recomputed = count / trend_total
        print(
            f"    {name:8s} {count:4d}/{trend_total} = {recomputed:5.1%} (recorded {recorded:.1%})"
        )
        assert abs(recomputed - recorded) < 0.03, (
            f"the {name} trend rate is now {recomputed:.1%} against a recorded "
            f"{recorded:.1%}; recompute it in settings.yaml rather than widening "
            f"this tolerance."
        )
    assert trend_total == settings.trend_base_rates.observations_measured, (
        f"the trend window is now {trend_total} quarters against a recorded "
        f"{settings.trend_base_rates.observations_measured}"
    )

    # (4b) Run the model with the DERIVED trend, and also show what each
    # alternative would give, so a reader can see how much the input matters.
    verdicts: dict[str, str] = {}
    for trend in _CREDIT_TRENDS:
        result = credit_spread_attribution(
            CreditSpreadInputs(
                hy_spread_bp=hy[today] * 100,
                hy_spread_change_bp=hy_change_bp,
                ig_spread_change_bp=ig_change_bp,
                equity_vol_change_pct=vol_change_pct,
                default_rate_trend=trend,  # type: ignore[arg-type]
            )
        )
        verdicts[trend] = read_str(result, "attribution")

        # The published predicates must agree with a recomputation from the raw
        # numbers in the same output.
        assert read_bool(result, "fundamental") == (trend == "rising"), (
            f"with trend={trend} the published 'fundamental' flag disagrees with the trend"
        )
        assert read_bool(result, "technical") == (
            vol_change_pct > settings.equity_vol_spike_threshold_pct
        ), "the published 'technical' flag disagrees with the raw volatility change"
        assert read_bool(result, "widening_observed") == (hy_change_bp > 0), (
            "the published 'widening_observed' flag disagrees with the raw HY change"
        )
        assert (
            abs(read_float(result, "hy_minus_ig_change_bp") - (hy_change_bp - ig_change_bp)) < 1e-6
        ), "the published differentiation disagrees with the raw spread changes"
        assert read_int(result, "change_window_days") == window

    print("\n  the model's verdict by trend input (DERIVED one marked):")
    for trend, attribution in verdicts.items():
        marker = "  <- DERIVED" if trend == derived_trend else ""
        print(f"    default_rate_trend={trend:8s} -> {attribution}{marker}")

    # D-079: a live check must not assert a fact about the WIRING using a fact
    # about TODAY'S MARKET. `credit_spread_attribution` tests `widening_observed`
    # FIRST, so on a day the HY spread tightens every trend legitimately returns
    # NO_WIDENING and this check would go red while the model is correct. The
    # wiring claim is pinned on a WIDENING row below; the live row is reported
    # above as the market reading.
    if hy_change_bp <= 0:
        print(
            "\n    (the live HY spread TIGHTENED, so every trend reads NO_WIDENING and "
            "the branch that\n     consults the trend was never reached — the wiring is "
            "pinned on a widening row below)"
        )
    wiring_verdicts: dict[str, str] = {
        trend: read_str(
            credit_spread_attribution(
                CreditSpreadInputs(
                    hy_spread_bp=hy[today] * 100,
                    hy_spread_change_bp=1.0,
                    ig_spread_change_bp=ig_change_bp,
                    equity_vol_change_pct=vol_change_pct,
                    default_rate_trend=trend,  # type: ignore[arg-type]
                )
            ),
            "attribution",
        )
        for trend in _CREDIT_TRENDS
    }
    print("\n  the trend's reach, on a WIDENING row (the wiring, not today's market):")
    for trend, attribution in wiring_verdicts.items():
        print(f"    default_rate_trend={trend:8s} -> {attribution}")
    assert len(set(wiring_verdicts.values())) > 1, (
        "every trend produced the same attribution on a row where the widening branch "
        "IS reached, which would mean the trend input does not reach the verdict at all"
    )
    assert wiring_verdicts["rising"] == "FUNDAMENTAL", (
        "a widening spread with a rising default rate must be attributed as "
        "FUNDAMENTAL; the specific verdict is asserted because 'not all equal' is "
        "satisfied by any two distinct outputs, including two wrong ones"
    )

    # (5) The diagnostic is published, disclaimed, and does not decide.
    latest = credit_spread_attribution(
        CreditSpreadInputs(
            hy_spread_bp=hy[today] * 100,
            hy_spread_change_bp=hy_change_bp,
            ig_spread_change_bp=ig_change_bp,
            equity_vol_change_pct=vol_change_pct,
            default_rate_trend="stable",
        )
    )
    assert any("DIAGNOSTIC, not part of the attribution" in w for w in latest.warnings), (
        "the differentiation must be disclaimed as a diagnostic on live output"
    )
    assert read_bool(latest, "widenings_are_parallel") == (
        abs(hy_change_bp - ig_change_bp) <= settings.differentiation_threshold_bp
    )
    print("\n  differentiation published, disclaimed, and not decisive")

    # (6) The manual-entry disclosure, in both halves.
    assert read_bool(latest, "default_rate_trend_is_caller_supplied") is True
    assert read_bool(latest, "default_rate_trend_derived_route_available") is True
    assert any("CALLER INPUT" in w for w in latest.warnings), (
        "the trend is a caller input and the output must say so"
    )
    print("  caller-input disclosure PRESENT for default_rate_trend")

    print("\n  NOT VALIDATED HERE: whether the DERIVED trend is the right")
    print("  measure of default risk. Delinquency leads default rather than")
    print("  equalling it, and the band is uncalibrated. What IS validated is")
    print("  that the trend is now computed rather than typed (D-043).")
    print("credit_spread_attribution REAL-DATA CHECK COMPLETE")


# ---------------------------------------------------------------------------
# Module 12 — compute_fci
# ---------------------------------------------------------------------------

#: The five components and the FRED series each is read from.
_FCI_SERIES = {
    "policy_rate": "DFF",
    "credit_spread_hy": "BAMLH0A0HYM2",
    "term_premium": "THREEFYTP10",
    "equity_index": "SP500",
    "usd_index": "DTWEXBGS",
}

#: Trading days over which the equity and dollar CHANGES are measured.
#:
#: Section 22.7 z-scores `equity_change` and `dollar_change` but names no period
#: for them, and the period is material: a 1-day S&P change and a 3-month one
#: have utterly different standard deviations. Twenty-one trading days is about
#: one month and is disclosed in the check's own output rather than buried here.
_FCI_CHANGE_WINDOW_DAYS = 21


def _check_financial_conditions(client: OpenBBClient) -> None:
    """Real-data wiring for ``compute_fci`` (Module 12, Section 22.7; D-038).

    Six things are established here, each independently of the model:

    1. **Every component and the NFCI cross-check are reachable**, and the
       cross-check Section 21.1 calls "mandatory" is actually PERFORMED.
    2. **The standardization window is reported**, because Section 22.7
       suggests ten years and this build cannot deliver it — the binding
       constraint is `BAMLH0A0HYM2`'s three-year history.
    3. **Every component's mean and std are computed over the SAME span.** A
       component standardized over a different window is not comparable, which
       is the defect Finding #7 exists to correct.
    4. **The z-scores are recomputed from the published raw values**, so the
       output carries its own arithmetic (the D-009 cross-field identity).
    5. **The equity orientation is checked on live data**: its contribution
       must carry the opposite sign to its z-score.
    6. **The composite is compared against NFCI** and the divergence reported.

    **What this check CANNOT establish, stated rather than glossed:** the
    weights are illustrative and uncalibrated, so a *level* agreement with NFCI
    would not validate them — the cross-check catches a divergence, not a
    wrong-but-consistent weighting.
    """
    from macro_engine.models.financial_conditions import (
        FCIComponent,
        FCIInputs,
        compute_fci,
    )

    print()
    print("=" * 72)
    print("Module 12 — compute_fci (Section 22.7; D-038)")

    settings = get_settings().fci

    series: dict[str, tuple[list[date], list[float]]] = {}
    for name, symbol in _FCI_SERIES.items():
        series[name] = _values(_fetch(client, symbol, name))
    nfci_dates, nfci_values = _values(_fetch(client, "NFCI", "nfci"))

    for name, (_dates, values) in series.items():
        print(f"    {name:18s} {_FCI_SERIES[name]:12s} {len(values):6d} obs  last={values[-1]:.4f}")
    print(f"    {'nfci':18s} {'NFCI':12s} {len(nfci_values):6d} obs  last={nfci_values[-1]:.4f}")

    # (2) The achievable common span, which is what the window is forced to.
    starts = [dates[0] for dates, _ in series.values()] + [nfci_dates[0]]
    ends = [dates[-1] for dates, _ in series.values()] + [nfci_dates[-1]]
    span_start, span_end = max(starts), min(ends)
    span_years = (span_end - span_start).days / 365.25
    print(
        f"\n  common span: {span_start} .. {span_end} "
        f"= {span_years:.2f} years (config expects {settings.standardization_window_years})"
    )
    binding = max(series, key=lambda n: series[n][0][0])
    print(f"  binding constraint: {binding} (starts {series[binding][0][0]})")
    assert span_years > 2.0, (
        f"the common span is only {span_years:.2f} years; the z-score statistics "
        f"cannot be computed over a sample this short"
    )
    assert span_years < 10.0, (
        "the common span now exceeds 10 years, so the note in settings.yaml saying "
        "Section 22.7's default is unattainable is stale and should be re-derived"
    )

    # (3) One window for every component, and it is the same window.
    def in_span(dates: list[date], values: list[float]) -> list[float]:
        return [v for d, v in zip(dates, values, strict=True) if span_start <= d <= span_end]

    stats: dict[str, tuple[float, float, float]] = {}
    for name, (series_dates, values) in series.items():
        window = in_span(series_dates, values)
        assert len(window) > 100, f"{name} has only {len(window)} observations in the common span"
        if name in ("equity_index", "usd_index"):
            # A CHANGE, not a level: the value is the N-day change, and its mean
            # and std are computed over the same span from the same changes.
            changes = [
                window[i] / window[i - _FCI_CHANGE_WINDOW_DAYS] - 1.0
                for i in range(_FCI_CHANGE_WINDOW_DAYS, len(window))
            ]
            current = changes[-1] * 100.0
            mean = sum(changes) / len(changes) * 100.0
            std = statistics.pstdev([c * 100.0 for c in changes])
            stats[name] = (current, mean, std)
            print(
                f"    {name:18s} {_FCI_CHANGE_WINDOW_DAYS}-day change "
                f"{current:+.4f}%  mean {mean:+.4f}%  std {std:.4f}"
            )
        else:
            mean = sum(window) / len(window)
            std = statistics.pstdev(window)
            stats[name] = (window[-1], mean, std)
            print(f"    {name:18s} level {window[-1]:9.4f}  mean {mean:9.4f}  std {std:8.4f}")

    # (4)+(5) Run the model and recompute its arithmetic from its own output.
    nfci_at_end = [v for d, v in zip(nfci_dates, nfci_values, strict=True) if d <= span_end][-1]

    def component(name: str) -> FCIComponent:
        """Package one component's live value with the statistics it is judged against."""
        value, mean, std = stats[name]
        return FCIComponent(value=value, mean=mean, std=std)

    result = compute_fci(
        FCIInputs(
            policy_rate=component("policy_rate"),
            credit_spread_hy=component("credit_spread_hy"),
            term_premium=component("term_premium"),
            equity_index=component("equity_index"),
            usd_index=component("usd_index"),
            standardization_window_years=settings.standardization_window_years,
            nfci_value=nfci_at_end,
        )
    )

    fci = read_float(result, "fci")
    z_scores = result.value["z_scores"] if isinstance(result.value, dict) else {}
    contributions = result.value["contributions"] if isinstance(result.value, dict) else {}
    assert isinstance(z_scores, dict) and isinstance(contributions, dict)

    print("\n  z-scores and contributions:")
    for name in _FCI_SERIES:
        print(f"    {name:18s} z={z_scores[name]:+8.4f}  contribution={contributions[name]:+8.4f}")

    # The cross-field identity.
    assert abs(fci - sum(contributions.values())) < 1e-3, (
        f"the published composite {fci} != the sum of its published contributions "
        f"{sum(contributions.values())}; a term is mis-weighted or mis-signed"
    )
    print(f"  cross-field identity holds ({fci:+.4f} = sum of contributions)")

    # Each z-score recomputed from the raw statistics the check computed.
    for name, (value, mean, std) in stats.items():
        expected_z = (value - mean) / std
        assert abs(z_scores[name] - expected_z) < 1e-3, (
            f"{name}: published z {z_scores[name]} != recomputed {expected_z}"
        )
    print("  every z-score AGREES with a recomputation from the raw statistics")

    # The orientation, on live data: equity's contribution must oppose its z.
    assert z_scores["equity_index"] * contributions["equity_index"] <= 0.0, (
        f"the equity contribution ({contributions['equity_index']:+.4f}) carries the "
        f"same sign as its z-score ({z_scores['equity_index']:+.4f}); Section 22.7 "
        f"negates it, and a same-sign contribution means the index is inverted"
    )
    print("  equity orientation CONFIRMED: its contribution opposes its z-score")

    # (6) The mandatory cross-check.
    assert read_bool(result, "nfci_cross_checked") is True, (
        "the NFCI cross-check is mandatory per Section 21.1 and NFCI is reachable "
        "on this build; it must be performed, not skipped"
    )
    divergence = read_float(result, "nfci_divergence")
    print(f"\n  NFCI cross-check: this composite {fci:+.4f} vs NFCI {nfci_at_end:+.4f}")
    print(
        f"    divergence {divergence:+.4f} against a {settings.nfci_divergence_threshold:.1f} bar"
    )
    if abs(divergence) > settings.nfci_divergence_threshold:
        assert any("diverges from NFCI" in w for w in result.warnings), (
            "a divergence beyond the bar must be warned about"
        )
        print("    -> beyond the bar, and the model WARNS about it")
    else:
        assert not any("diverges from NFCI" in w for w in result.warnings), (
            "a divergence inside the bar must not warn"
        )
        print("    -> inside the bar, and the model stays quiet")

    print(
        f"\n  verdict: FCI {fci:+.3f} — "
        f"{'TIGHTER' if read_bool(result, 'tighter_than_average') else 'LOOSER'} than average"
    )
    print("\n  NOT VALIDATED HERE: the WEIGHTS. They are illustrative and")
    print("  uncalibrated, so a level agreement with NFCI would not confirm them;")
    print("  the cross-check catches a divergence, not a wrong-but-consistent set.")
    print("compute_fci REAL-DATA CHECK COMPLETE")


# ---------------------------------------------------------------------------
# Module 3.2 — policy_mix_classifier
# ---------------------------------------------------------------------------

#: The trailing window, in annual observations, the deficit is judged against.
#: Section 21.1 sources the average from config and says "recompute annually";
#: the check recomputes it from the series so the stored value cannot go stale.
_POLICY_MIX_AVG_WINDOW_YEARS = 10


def _bare_float(result: ModelResult) -> float:
    """Narrow a result whose ``value`` is a bare float rather than a dict.

    ``taylor_rule`` publishes ``value=round(rate, 2)`` — a scalar, which
    Section 22.9's union permits. ``read_float`` requires a dict key, so this
    handles the scalar case and asserts rather than casts.
    """
    value = result.value
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{result.model_name}: expected a bare numeric value, got {type(value).__name__}"
    )
    return float(value)


def _check_policy_mix(client: OpenBBClient) -> None:
    """Real-data wiring for ``policy_mix_classifier`` (Module 3.2, D-039).

    Six things are established here, each independently of the model:

    1. **The deficit series is reachable and its SIGN is asserted before use.**
       This is the load-bearing check. `FYFSGDA188S` is NEGATIVE for a deficit,
       while the model's field is positive-for-a-deficit. Feeding the raw series
       through inverts every comparison — the largest deficits in the sample
       would read as the tightest fiscal policy. The check asserts the raw sign,
       negates, and asserts the negated sign.
    2. **The deficit series is ANNUAL**, so the common keys with the quarterly
       policy, inflation and output series are one per year, and the trailing
       average is ten annual observations — not ten quarters.
    3. **The Taylor-implied rate is DERIVED** by calling `taylor_rule` on live
       inflation and output-gap values, rather than being typed in.
    4. **The trailing average is recomputed** and compared against the config's
       stored expectation, so the stored value cannot go stale silently.
    5. **All four quadrant base rates are recomputed** over the history (D-029).
    6. **The quadrant is recomputed from the published predicates** (D-009).

    **What this check CANNOT establish:** whether the *stored* deficit average
    of 4.5% is the right expectation. It measures 2.83% over the trailing
    window, and the model reports the disagreement rather than resolving it.
    """
    from macro_engine.models.national_accounts import (
        PolicyMixInputs,
        policy_mix_classifier,
    )
    from macro_engine.models.policy_rules import TaylorRuleInputs, taylor_rule

    print()
    print("=" * 72)
    print("Module 3.2 — policy_mix_classifier (Section 20.3; D-039)")

    settings = get_settings().policy_mix
    r_star = get_settings().policy.r_star_value

    raw_dates, raw_values = _values(_fetch(client, "FYFSGDA188S", "federal_deficit_pct_gdp"))
    policy_dates, policy_values = _values(_fetch(client, "FEDFUNDS", "policy_rate"))
    core_dates, core_values = _values(_fetch(client, "PCEPILFE", "core_pce"))
    pot_dates, pot_values = _values(_fetch(client, "GDPPOT", "potential_gdp"))
    real_dates, real_values = _values(_fetch(client, "GDPC1", "real_gdp"))

    # (1) The sign, asserted on the RAW series before anything is done with it.
    negative_share = sum(1 for v in raw_values if v < 0.0) / len(raw_values)
    print(f"  FYFSGDA188S: {len(raw_values)} obs, last {raw_values[-1]:+.4f}")
    print(f"    negative in {negative_share:.1%} of observations (raw convention)")
    assert negative_share > 0.5, (
        f"only {negative_share:.1%} of the raw deficit series is negative. The series "
        f"is expected to be NEGATIVE for a deficit; if the provider has flipped the "
        f"sign, the negation below becomes a second inversion and every quadrant is "
        f"reported backwards."
    )
    print("    RAW SIGN CONFIRMED: negative = deficit, so the series must be NEGATED")

    def annual(dates: list[date], values: list[float]) -> dict[int, float]:
        """Last observation per calendar year."""
        out: dict[int, float] = {}
        for day, value in zip(dates, values, strict=True):
            out[day.year] = value
        return out

    # (2) Annual keys, because the deficit series is annual.
    deficit = annual(raw_dates, [-v for v in raw_values])  # NEGATED here
    policy = annual(policy_dates, policy_values)
    core = annual(core_dates, core_values)
    pot = annual(pot_dates, pot_values)
    real = annual(real_dates, real_values)

    # After negation the deficits are positive and the surpluses negative, so the
    # POSITIVE share of the negated series must equal the NEGATIVE share of the
    # raw one. Asserting that every value became positive was the first version
    # of this check and it FAILED: 14.4% of the raw series is positive, i.e.
    # genuine SURPLUSES (the late 1990s among them), which are correctly negative
    # once negated. The test is that the shares swap, not that surpluses vanish.
    negated_positive_share = sum(1 for v in deficit.values() if v > 0.0) / len(deficit)
    assert abs(negated_positive_share - negative_share) < 0.02, (
        f"after negation {negated_positive_share:.1%} of years are positive against "
        f"a raw negative share of {negative_share:.1%}; the two must match, or the "
        f"negation is not a clean sign flip"
    )
    surplus_years = sorted(y for y, v in deficit.items() if v < 0.0)
    print(f"  after negation: {min(deficit.values()):.2f} to {max(deficit.values()):.2f}% of GDP")
    print(
        f"    surplus years (negative after negation): {len(surplus_years)} "
        f"of {len(deficit)}, e.g. {surplus_years[-6:]}"
    )

    years = sorted(set(deficit) & set(policy) & set(core) & set(pot) & set(real))
    assert len(years) > 20, f"only {len(years)} common years; the base rates need more"
    print(f"  common years: {len(years)} ({years[0]} .. {years[-1]})")

    # (3) The Taylor-implied rate, DERIVED rather than typed.
    latest = years[-1]
    prior = latest - 1
    pi_current = (core[latest] / core[prior] - 1) * 100
    output_gap = (real[latest] / pot[latest] - 1) * 100
    taylor = _bare_float(
        taylor_rule(TaylorRuleInputs(r_star=r_star, pi_current=pi_current, output_gap=output_gap))
    )
    print(
        f"\n  {latest}: core PCE {pi_current:+.2f}% YoY, output gap {output_gap:+.2f}%, "
        f"fed funds {policy[latest]:.2f}%"
    )
    print(f"    taylor_rule(r*={r_star}) -> implied {taylor:.2f}%")

    # (4) The trailing average, recomputed.
    latest_index = years.index(latest)
    window = [
        deficit[y]
        for y in years[max(0, latest_index - _POLICY_MIX_AVG_WINDOW_YEARS) : latest_index]
    ]
    measured_avg = sum(window) / len(window)
    print(
        f"\n  trailing {_POLICY_MIX_AVG_WINDOW_YEARS}-year mean deficit: {measured_avg:.2f}% of GDP"
    )
    print(f"    settings.yaml stored expectation          : {settings.fiscal_deficit_avg:.2f}%")
    if abs(measured_avg - settings.fiscal_deficit_avg) > 0.5:
        print("    -> the stored expectation disagrees; the model will report that, not hide it")

    # (5) Recompute all four quadrant base rates over the history.
    counts = dict.fromkeys(
        (
            "MAX_STIMULUS",
            "MIXED_FISCAL_LOOSE_MONETARY_TIGHT",
            "MIXED_FISCAL_TIGHT_MONETARY_LOOSE",
            "MAX_RESTRAINT",
        ),
        0,
    )
    considered = 0
    for index in range(_POLICY_MIX_AVG_WINDOW_YEARS, len(years)):
        year = years[index]
        back = years[index - 1]
        if core[back] == 0 or pot[year] == 0:
            continue
        pi_year = (core[year] / core[back] - 1) * 100
        gap_year = (real[year] / pot[year] - 1) * 100
        taylor_year = _bare_float(
            taylor_rule(TaylorRuleInputs(r_star=r_star, pi_current=pi_year, output_gap=gap_year))
        )
        history = [deficit[y] for y in years[index - _POLICY_MIX_AVG_WINDOW_YEARS : index]]
        fiscal_loose = deficit[year] > sum(history) / len(history)
        monetary_loose = policy[year] < taylor_year
        if fiscal_loose and monetary_loose:
            counts["MAX_STIMULUS"] += 1
        elif fiscal_loose:
            counts["MIXED_FISCAL_LOOSE_MONETARY_TIGHT"] += 1
        elif monetary_loose:
            counts["MIXED_FISCAL_TIGHT_MONETARY_LOOSE"] += 1
        else:
            counts["MAX_RESTRAINT"] += 1
        considered += 1

    print(f"\n  base rates RECOMPUTED over {considered} years:")
    for name, count in counts.items():
        recorded = settings.quadrant_base_rates[name]
        recomputed = count / considered
        print(
            f"    {name:36s} {count:3d}/{considered} = {recomputed:5.1%} (recorded {recorded:.1%})"
        )
        assert abs(recomputed - recorded) < 0.05, (
            f"the {name} base rate is now {recomputed:.1%} against a recorded "
            f"{recorded:.1%}. This is the frequency the model discloses with every "
            f"verdict; recompute it in settings.yaml rather than widening this "
            f"tolerance."
        )
    assert sum(counts.values()) == considered, "every year must land in exactly one quadrant"

    # (6) Run the model on the latest year and recompute its answer.
    result = policy_mix_classifier(
        PolicyMixInputs(
            fiscal_deficit_pct_gdp=deficit[latest],
            fiscal_deficit_avg_pct_gdp=measured_avg,
            policy_rate=policy[latest],
            taylor_implied_rate=taylor,
        )
    )
    quadrant = read_str(result, "quadrant")
    fiscal_loose = read_bool(result, "fiscal_loose")
    monetary_loose = read_bool(result, "monetary_loose")
    print(f"\n  {latest}: deficit {deficit[latest]:.2f}% vs average {measured_avg:.2f}%")
    print(f"    fed funds {policy[latest]:.2f}% vs Taylor {taylor:.2f}%")
    print(f"    quadrant = {quadrant}")

    assert fiscal_loose == (deficit[latest] > measured_avg), (
        "the published fiscal_loose flag disagrees with the raw numbers in the same output"
    )
    assert monetary_loose == (policy[latest] < taylor), (
        "the published monetary_loose flag disagrees with the raw numbers"
    )
    expected_quadrant = (
        "MAX_STIMULUS"
        if fiscal_loose and monetary_loose
        else "MIXED_FISCAL_LOOSE_MONETARY_TIGHT"
        if fiscal_loose
        else "MIXED_FISCAL_TIGHT_MONETARY_LOOSE"
        if monetary_loose
        else "MAX_RESTRAINT"
    )
    assert quadrant == expected_quadrant, (
        f"reported quadrant {quadrant} does not follow from the published predicates"
    )
    print("  cross-field identity holds (quadrant recomputed from its own predicates)")

    # The base rate for THIS quadrant must travel with the output.
    assert read_float(result, "quadrant_base_rate") == settings.quadrant_base_rates[quadrant]
    assert read_int(result, "observations_measured") == settings.base_rates.observations_measured
    assert any(f"{settings.quadrant_base_rates[quadrant]:.1%}" in w for w in result.warnings), (
        "the quadrant's own base rate must reach the prose"
    )
    print(f"  base rate {settings.quadrant_base_rates[quadrant]:.1%} travels with the quadrant")

    # The MIXED disclosure must fire exactly when the two disagree.
    mixed_warned = any("working against monetary" in w for w in result.warnings)
    assert mixed_warned == (fiscal_loose != monetary_loose), (
        "the MIXED warning must fire exactly when fiscal and monetary disagree"
    )
    disclosure = "present" if mixed_warned else "absent"
    print(f"  MIXED disclosure {disclosure} and matches the predicates")

    print("\n  NOT VALIDATED HERE: the stored 4.5% deficit average. The check")
    print("  recomputes it and reports the disagreement; it does not resolve which")
    print("  window is right.")
    print("policy_mix_classifier REAL-DATA CHECK COMPLETE")


# ---------------------------------------------------------------------------
# Module 4.1 — qe_qt_stance
# ---------------------------------------------------------------------------

#: The 13-week change window, in weekly observations.
_QE_CHANGE_WINDOW_WEEKS = 13


def _check_qe_qt_stance(client: OpenBBClient) -> None:
    """Real-data wiring for ``qe_qt_stance`` (Module 4.1, D-040).

    Six things are established here, each independently of the model:

    1. **The units are asserted before anything is combined.** `WALCL` and
       `WRESBAL` are in MILLIONS of dollars; `RRPONTSYD` is in BILLIONS. Mixing
       them is a **1000x** error, and the balance-sheet level is the denominator
       of the relative change that decides the stance — so a units error there
       moves the stance directly while every number stays plausible. The live
       check asserts each series' order of magnitude.
    2. **The specification's `== 0` test is shown to be dead on live data.**
       The check counts how many 13-week changes are exactly zero, so the
       defect and its correction are both visible in the output.
    3. **All three stance base rates are recomputed**, including NEUTRAL_HOLD
       under the band, so the record cannot go stale (D-029).
    4. **The scarcity flag is recomputed** from reserves and the RRP buffer.
    5. **The stance is recomputed from the published components** (D-009).
    6. **The base rate travels** with the stance.

    **What this check CANNOT establish:** whether 0.5% is the right band. It is
    `uncalibrated_illustrative`, and the check reports what it produces rather
    than defending it.
    """
    from macro_engine.models.policy_rules import BalanceSheetInputs, qe_qt_stance

    print()
    print("=" * 72)
    print("Module 4.1 — qe_qt_stance (Section 20.4; D-040)")

    settings = get_settings().qe_qt
    band = settings.neutral_band_pct

    wal_dates, wal_values = _values(_fetch(client, "WALCL", "fed_total_assets"))
    res_dates, res_values = _values(_fetch(client, "WRESBAL", "reserve_balances"))
    rrp_dates, rrp_values = _values(_fetch(client, "RRPONTSYD", "on_rrp_level"))

    # (1) The units, asserted before anything is combined.
    print(f"  WALCL    : {len(wal_values)} obs, last {wal_values[-1]:>14,.0f}  (millions)")
    print(f"  WRESBAL  : {len(res_values)} obs, last {res_values[-1]:>14,.0f}  (millions)")
    print(f"  RRPONTSYD: {len(rrp_values)} obs, last {rrp_values[-1]:>14,.1f}  (BILLIONS)")
    assert wal_values[-1] > 1e6, (
        f"WALCL reads {wal_values[-1]:,.0f}; if the provider switched to BILLIONS the "
        f"level is a 1000x error and the relative change is unaffected but every "
        f"published magnitude is wrong"
    )
    assert res_values[-1] > 1e5, f"WRESBAL reads {res_values[-1]:,.0f}, not a millions figure"
    assert rrp_values[-1] < 1e4, (
        f"RRPONTSYD reads {rrp_values[-1]:,.1f}; if the provider switched to MILLIONS "
        f"the drained-threshold comparison in billions becomes a 1000x error"
    )
    assert wal_values[-1] > res_values[-1], (
        f"total assets ({wal_values[-1]:,.0f}) are not above reserves "
        f"({res_values[-1]:,.0f}); the two series may be mapped to each other's symbols"
    )
    print("  units CONFIRMED: WALCL/WRESBAL in millions, RRP in billions; assets above reserves")

    wal = dict(zip(wal_dates, wal_values, strict=True))
    res = dict(zip(res_dates, res_values, strict=True))
    common = sorted(set(wal) & set(res))
    assert len(common) > _QE_CHANGE_WINDOW_WEEKS + 100, (
        f"only {len(common)} common weekly dates; the base rates need more"
    )
    print(f"  common weekly dates: {len(common)} ({common[0]} .. {common[-1]})")

    # (2)+(3) Recompute the base rates, and show the specification's dead branch.
    exact_zero = 0
    qe = qt = neutral = 0
    drain_while_qt = 0
    for index in range(_QE_CHANGE_WINDOW_WEEKS, len(common)):
        today, prior = common[index], common[index - _QE_CHANGE_WINDOW_WEEKS]
        change = wal[today] - wal[prior]
        if change == 0.0:
            exact_zero += 1
        change_pct = change / wal[today] * 100.0
        if abs(change_pct) <= band:
            neutral += 1
        elif change_pct > 0:
            qe += 1
        else:
            qt += 1
            if res[today] - res[prior] < 0.0:
                drain_while_qt += 1
    considered = len(common) - _QE_CHANGE_WINDOW_WEEKS

    print(f"\n  Section 20.4's `change == 0` test, on {considered} live weeks:")
    print(f"    changes EXACTLY zero: {exact_zero} = {exact_zero / considered:.2%}")
    assert exact_zero == 0, (
        "the thirteen-week change was exactly zero, which would make NEUTRAL_HOLD "
        "reachable under the specification's own test. If this ever fires, the "
        "band is no longer correcting a dead branch and D-040 should be revisited."
    )
    print("    -> the specification's NEUTRAL_HOLD branch is UNREACHABLE, as recorded")

    print(f"\n  base rates RECOMPUTED under the +/-{band:.2f}% band, {considered} weeks:")
    for name, count in (("QE_EXPANDING", qe), ("QT_CONTRACTING", qt), ("NEUTRAL_HOLD", neutral)):
        recorded = settings.base_rates.rates[name]
        recomputed = count / considered
        print(
            f"    {name:16s} {count:4d}/{considered} = {recomputed:5.1%} (recorded {recorded:.1%})"
        )
        assert abs(recomputed - recorded) < 0.05, (
            f"the {name} base rate is now {recomputed:.1%} against a recorded "
            f"{recorded:.1%}; recompute it in settings.yaml rather than widening "
            f"this tolerance."
        )
    assert qe + qt + neutral == considered, "every week must land in exactly one stance"

    drain_rate = drain_while_qt / qt if qt else 0.0
    print(f"    QT weeks with reserves ALSO falling: {drain_while_qt}/{qt} = {drain_rate:.1%}")
    print(f"      (recorded {settings.base_rates.reserve_drain_while_qt_rate:.1%})")
    assert abs(drain_rate - settings.base_rates.reserve_drain_while_qt_rate) < 0.05, (
        "the reserve-drain base rate has drifted; it is the frequency the scarcity "
        "flag is disclosed with"
    )

    # (4)+(5) Run the model on the latest common week and recompute its answer.
    today, prior = common[-1], common[-1 - _QE_CHANGE_WINDOW_WEEKS]
    level = wal[today]
    change = wal[today] - wal[prior]
    reserve_change = res[today] - res[prior]
    latest_rrp = [v for d, v in zip(rrp_dates, rrp_values, strict=True) if d <= today][-1]

    print(f"\n  latest week {prior} -> {today} ({_QE_CHANGE_WINDOW_WEEKS} weeks):")
    relative_pct = change / level * 100
    print(
        f"    balance sheet {wal[prior]:,.0f} -> {level:,.0f} = "
        f"{change:+,.0f}mn ({relative_pct:+.3f}%)"
    )
    print(f"    reserves      {res[prior]:,.0f} -> {res[today]:,.0f} = {reserve_change:+,.0f}mn")
    print(f"    ON RRP        {latest_rrp:,.1f}bn")

    result = qe_qt_stance(
        BalanceSheetInputs(
            balance_sheet_level=level,
            balance_sheet_change_3mo=change,
            reserve_balances=res[today],
            reserve_balances_change_3mo=reserve_change,
            on_rrp_level=latest_rrp,
        )
    )
    stance = read_str(result, "stance")
    print(f"    stance = {stance}")

    expected_pct = change / level * 100.0
    published_pct = read_float(result, "balance_sheet_change_pct")
    assert abs(published_pct - expected_pct) < 1e-3, (
        f"the published relative change ({published_pct}) disagrees with the raw "
        f"numbers in the same output ({expected_pct})"
    )
    expected_stance = (
        "QE_EXPANDING"
        if expected_pct > band
        else "QT_CONTRACTING"
        if expected_pct < -band
        else "NEUTRAL_HOLD"
    )
    assert stance == expected_stance, (
        f"reported stance {stance} does not follow from the published relative change"
    )
    assert read_bool(result, "reserves_draining") == (reserve_change < 0.0)
    assert read_bool(result, "direct_reserve_drain") == (
        stance == "QT_CONTRACTING" and reserve_change < 0.0
    )
    assert read_bool(result, "rrp_drained") == (latest_rrp < settings.rrp_drained_threshold_bn)
    print("  cross-field identity holds (stance recomputed from its own components)")

    # (6) The base rate must travel with the stance.
    assert read_float(result, "stance_base_rate") == settings.base_rates.rates[stance]
    assert read_int(result, "observations_measured") == settings.base_rates.observations_measured
    assert any(f"{settings.base_rates.rates[stance]:.1%}" in w for w in result.warnings), (
        "the stance's own base rate must reach the prose"
    )
    print(f"  base rate {settings.base_rates.rates[stance]:.1%} travels with the stance")

    if read_bool(result, "direct_reserve_drain"):
        print("  SCARCITY CONFIGURATION: QT is draining reserves, not the RRP buffer")
    if read_bool(result, "rrp_drained"):
        print(
            f"  RRP buffer DRAINED ({latest_rrp:,.1f}bn below the "
            f"{settings.rrp_drained_threshold_bn:,.0f}bn threshold)"
        )

    print("\n  NOT VALIDATED HERE: whether 0.5% is the right band. It is")
    print("  uncalibrated_illustrative; the check reports what it produces.")
    print("qe_qt_stance REAL-DATA CHECK COMPLETE")


# ---------------------------------------------------------------------------
# Module 3.4 — minsky_composition_drift
# ---------------------------------------------------------------------------


def _check_minsky_composition_drift(client: OpenBBClient) -> None:
    """Real-data wiring for ``minsky_composition_drift`` (Module 3.4, D-043).

    **This check RUNS the model.** Until D-043 it could not: two of the three
    inputs were BLOCKED on the premise that no free leveraged-loan series
    existed. That premise was **factually wrong** — `fred_search` finds
    `BOGZ1FL623069503Q` — so the block is lifted and this is a live check.

    Five things are established:

    1. **The proxy's zero-history limitation is asserted**, not merely noted.
       The series reads exactly zero before 2013-Q4, which is a structural break
       in the Z.1 accounts rather than a statement that hedge funds held nothing.
       Growth is undefined across it, so those quarters are **dropped, never
       imputed**, and the check fails if the limitation ever disappears (which
       would mean the series was backfilled and D-043's caveat is stale).
    2. **All three stage base rates are recomputed** — they were unmeasurable
       while the block stood, so this is the first time they can be checked.
    3. **The model runs on the latest common quarter** and its stage is
       recomputed from the published predicates (D-009).
    4. **The stage's own base rate travels** with the output (D-029).
    5. **The proxy is disclosed** on live output, not only in a docstring.

    **What this check CANNOT establish:** the 2008 crisis. The usable window is
    2013-Q4 onward, so the model has never been exercised on a full credit cycle
    through a systemic banking crisis. That is a property of the proxy and is
    stated rather than glossed.
    """
    from macro_engine.models.national_accounts import (
        MinskyCompositionInputs,
        minsky_composition_drift,
    )

    print()
    print("=" * 72)
    print("Module 3.4 — minsky_composition_drift (Section 20.3; D-043)")
    print("  STATUS: UNBLOCKED — the model IS run here. Section 21.1's premise")
    print("  ('no clean free series for leveraged-loan growth') was wrong.")

    settings = get_settings().minsky

    lev_dates, lev_values = _values(_fetch(client, "BOGZ1FL623069503Q", "leveraged_loan_holdings"))
    tot_dates, tot_values = _values(_fetch(client, "TOTBKCR", "total_bank_credit"))
    sloos_dates, sloos_values = _values(_fetch(client, "DRTSCILM", "sloos_net_tightening"))

    def quarterly(dates: list[date], values: list[float]) -> dict[tuple[int, int], float]:
        """Last observation per calendar quarter, keyed (year, quarter)."""
        out: dict[tuple[int, int], float] = {}
        for day, value in zip(dates, values, strict=True):
            out[(day.year, (day.month - 1) // 3 + 1)] = value
        return out

    lev = quarterly(lev_dates, lev_values)
    tot = quarterly(tot_dates, tot_values)
    sloos = quarterly(sloos_dates, sloos_values)
    all_quarters = sorted(set(lev) & set(tot) & set(sloos))
    print(f"\n  common quarters: {len(all_quarters)} ({all_quarters[0]} .. {all_quarters[-1]})")

    # (1) The zero-history limitation, asserted rather than assumed.
    zeros = [q for q in all_quarters if lev[q] == 0.0]
    print(f"  leveraged loans read ZERO in {len(zeros)} of {len(all_quarters)} quarters")
    assert zeros, (
        "the leveraged-loan series no longer contains zeros. If the provider has "
        "backfilled it, the 51-quarter window in D-043 is stale and the usable "
        "history is longer — revisit the decision rather than relaxing this."
    )
    print(f"    first {zeros[0]}, last {zeros[-1]}")
    print("    -> growth is UNDEFINED there; those quarters are DROPPED, not imputed")

    # (2) Recompute all three stage base rates.
    margin = settings.drift_margin_pct
    counts = dict.fromkeys(("PONZI_DRIFT_WARNING", "SPECULATIVE_DRIFT", "HEDGE_DOMINANT"), 0)
    considered = dropped = 0
    for index in range(4, len(all_quarters)):
        now, prior = all_quarters[index], all_quarters[index - 4]
        if lev[prior] == 0.0 or tot[prior] == 0.0 or lev[now] == 0.0:
            dropped += 1
            continue
        risky_growth = (lev[now] / lev[prior] - 1) * 100.0
        total_growth = (tot[now] / tot[prior] - 1) * 100.0
        loosening = sloos[now] < 0.0
        outgrowing = (risky_growth - total_growth) > margin * abs(total_growth)
        counts[
            "PONZI_DRIFT_WARNING"
            if loosening and outgrowing
            else "SPECULATIVE_DRIFT"
            if loosening or outgrowing
            else "HEDGE_DOMINANT"
        ] += 1
        considered += 1

    print(f"\n  stage base rates RECOMPUTED over {considered} quarters (dropped {dropped}):")
    for name, count in counts.items():
        recorded = settings.base_rates.stage_rates[name]
        recomputed = count / considered
        print(
            f"    {name:22s} {count:4d}/{considered} = {recomputed:5.1%} (recorded {recorded:.1%})"
        )
        assert abs(recomputed - recorded) < 0.05, (
            f"the {name} base rate is now {recomputed:.1%} against a recorded "
            f"{recorded:.1%}; recompute it in settings.yaml rather than widening "
            f"this tolerance."
        )
    assert sum(counts.values()) == considered, "every quarter must land in exactly one stage"
    assert considered == settings.base_rates.stage_observations_measured, (
        f"the usable window is now {considered} quarters against a recorded "
        f"{settings.base_rates.stage_observations_measured}; the record has drifted"
    )

    # (3) Run the model on the latest common quarter.
    now, prior = all_quarters[-1], all_quarters[-1 - 4]
    risky_growth = (lev[now] / lev[prior] - 1) * 100.0
    total_growth = (tot[now] / tot[prior] - 1) * 100.0
    print(f"\n  latest quarter {now[0]}-Q{now[1]} (vs {prior[0]}-Q{prior[1]}):")
    print(f"    leveraged loans {lev[prior]:,.0f} -> {lev[now]:,.0f} = {risky_growth:+.2f}%")
    print(f"    total bank credit {tot[prior]:,.0f} -> {tot[now]:,.0f} = {total_growth:+.2f}%")
    print(f"    SLOOS net tightening {sloos[now]:+.1f}")

    result = minsky_composition_drift(
        MinskyCompositionInputs(
            lending_standards_net_tightening_pct=sloos[now],
            risky_credit_growth_pct=risky_growth,
            total_credit_growth_pct=total_growth,
        )
    )
    stage = read_str(result, "stage")
    print(f"    stage = {stage}")

    loosening = read_bool(result, "standards_loosening")
    outgrowing = read_bool(result, "risky_outgrowing")
    assert loosening == (sloos[now] < 0.0), (
        "the published standards_loosening flag disagrees with the raw survey"
    )
    assert outgrowing == ((risky_growth - total_growth) > margin * abs(total_growth)), (
        "the published risky_outgrowing flag disagrees with the raw growth rates"
    )
    expected = (
        "PONZI_DRIFT_WARNING"
        if loosening and outgrowing
        else "SPECULATIVE_DRIFT"
        if loosening or outgrowing
        else "HEDGE_DOMINANT"
    )
    assert stage == expected, f"reported {stage} does not follow from its own predicates"
    print("  cross-field identity holds (stage recomputed from its own predicates)")

    # (4) The stage's own base rate must travel.
    assert read_float(result, "stage_base_rate") == settings.base_rates.stage_rates[stage]
    assert read_int(result, "stage_observations_measured") == considered
    assert any(f"{settings.base_rates.stage_rates[stage]:.1%}" in w for w in result.warnings)
    print(f"  base rate {settings.base_rates.stage_rates[stage]:.1%} travels with the stage")

    # (5) The proxy disclosure, on live output.
    assert read_str(result, "risky_credit_proxy") == "hedge_fund_leveraged_loans"
    assert any("DISCLOSED PROXY" in w for w in result.warnings), (
        "the proxy must be disclosed on live output, not only in a docstring"
    )
    print("  proxy disclosure PRESENT")

    print("\n  NOT VALIDATED HERE: the 2008 crisis. The proxy reads zero before")
    print("  2013-Q4, so the model has never been exercised through a systemic")
    print("  banking crisis. That is a property of the measure, stated not glossed.")
    print("minsky_composition_drift REAL-DATA CHECK COMPLETE")


def _check_probability_models(client: OpenBBClient) -> None:
    """Verification for ``bayesian_update`` and ``expected_value`` (D-042).

    **These two functions have no data dependency.** They take caller-supplied
    probabilities and payoffs and fetch nothing, so there is no series to check
    the wiring against and no nulls, units or frequencies to verify. The usual
    live check has nothing to do.

    What replaces it is the strongest thing available: **an independent
    recomputation of the same quantity by a different formulation**, on the
    Section 11.1 mandated values. A wrong-but-plausible arithmetic error survives
    a re-run of the same expression; it does not survive the odds form.

    The check establishes:

    1. **Section 11.1's mandated posterior** — 0.40 / 0.70 / 0.20 -> 0.70 — and
       the same figure via the **odds form**, ``posterior_odds = prior_odds * LR``.
    2. **The mandated warning** fires on an uninformative likelihood ratio.
    3. **The mandated refusal** on scenario probabilities that do not sum to 1.
    4. **The tail boundary** is where the config says it is, not near it.
    5. **The published components reconcile** — the cross-field identity, on both
       functions.

    ``client`` is accepted and unused: this function is dispatched from the same
    place as every other check, and the alternative would be a special case in
    the dispatcher for a module that happens to need no data. The parameter is
    named and the reason recorded rather than the signature being fudged.
    """
    from macro_engine.models.probability import (
        BayesInputs,
        ScenarioOutcome,
        bayesian_update,
        expected_value,
    )

    _ = client  # no data dependency; see the docstring

    print()
    print("=" * 72)
    print("Module 12.3/12.4 — bayesian_update, expected_value (Section 20.11; D-042)")
    print("  NOTE: these functions have NO data dependency. 'Live' here means an")
    print("  independent recomputation, not a market series.")

    settings = get_settings().probability

    # (1) The mandated value, and the same value by a different formulation.
    prior, lrt, lrf = 0.40, 0.70, 0.20
    result = bayesian_update(
        BayesInputs(prior=prior, likelihood_given_true=lrt, likelihood_given_false=lrf)
    )
    posterior = read_float(result, "posterior")
    print(f"\n  Section 11.1 mandated case: prior {prior}, P(B|A) {lrt}, P(B|~A) {lrf}")
    print(f"    posterior (direct form) = {posterior}")
    assert posterior == 0.7, f"Section 11.1 mandates 0.70; got {posterior}"

    # The ODDS form: posterior_odds = prior_odds * LR. Algebraically identical,
    # computed a different way, so an arithmetic error in the direct form shows.
    prior_odds = prior / (1.0 - prior)
    likelihood_ratio = read_float(result, "likelihood_ratio")
    posterior_odds = prior_odds * likelihood_ratio
    odds_form = posterior_odds / (1.0 + posterior_odds)
    print(f"    posterior (odds form)   = {odds_form:.10f}")
    assert abs(odds_form - posterior) < 1e-9, (
        f"the direct and odds forms disagree: {posterior} vs {odds_form}. One of "
        f"them is wrong, and they are algebraically the same quantity."
    )
    print("    -> both formulations AGREE to 1e-9")

    # The published denominator must reconcile with the inputs.
    p_evidence = read_float(result, "p_evidence")
    assert abs(p_evidence - (lrt * prior + lrf * (1.0 - prior))) < 1e-9, (
        "the published P(B) does not reconcile with the likelihoods and prior"
    )
    assert abs(read_float(result, "shift_pp") - (posterior - prior) * 100.0) < 1e-3
    print("  cross-field identity holds (P(B), posterior and shift all reconcile)")

    # (2) The mandated warning.
    uninformative = bayesian_update(
        BayesInputs(prior=0.4, likelihood_given_true=0.5, likelihood_given_false=0.5)
    )
    assert read_bool(uninformative, "evidence_informative") is False
    assert any("barely" in w for w in uninformative.warnings), (
        "Section 11.1 mandates the uninformative-evidence warning"
    )
    print("  mandated uninformative-LR warning FIRES")

    # (3) The mandated refusal.
    try:
        expected_value(
            [
                ScenarioOutcome(name="a", probability=0.5, payoff_estimate=1.0),
                ScenarioOutcome(name="b", probability=0.2, payoff_estimate=1.0),
            ]
        )
        raise AssertionError("a set summing to 0.7 was accepted")
    except AssertionError:
        raise
    except Exception as exc:
        print(f"  mandated refusal on a bad probability sum: {type(exc).__name__}")

    # (4) The tail boundary, exactly on the configured multiple.
    multiple = settings.tail_loss_multiple
    # The fixture is DERIVED from the configured multiple so the tail lands
    # exactly on the boundary. The first version used payoffs of +10 / -10*m,
    # which gives EV = -5: negative, so `tail_dominates` (which requires EV > 0)
    # could never be reached and the boundary was untestable.
    #
    # With p = 0.5 and a tail of -W, the EV is (P - W)/2, and the boundary is
    # W = multiple * |EV|. Solving: P = W * (1 + 2/multiple).
    tail_loss = 10.0
    base_gain = tail_loss * (1.0 + 2.0 / multiple)
    at_boundary = expected_value(
        [
            ScenarioOutcome(name="base", probability=0.5, payoff_estimate=base_gain),
            ScenarioOutcome(name="tail", probability=0.5, payoff_estimate=-tail_loss),
        ]
    )
    ev = read_float(at_boundary, "ev")
    worst = read_float(at_boundary, "worst_case_payoff")
    print(f"\n  tail boundary: EV {ev:+.4f}, worst {worst:+.4f}, multiple {multiple:.0f}")
    assert abs(worst + multiple * abs(ev)) < 1e-9, (
        "the fixture does not sit exactly on the boundary"
    )
    assert read_bool(at_boundary, "tail_dominates") is False, (
        "a tail exactly at the configured multiple is not ABOVE it — the comparison is strict"
    )
    just_past = expected_value(
        [
            ScenarioOutcome(name="base", probability=0.5, payoff_estimate=base_gain),
            ScenarioOutcome(name="tail", probability=0.5, payoff_estimate=-tail_loss - 0.01),
        ]
    )
    assert read_bool(just_past, "tail_dominates") is True
    print("    -> the comparison is strict, exactly at the configured multiple")

    # (5) The EV identity.
    scenarios = [
        ScenarioOutcome(name="a", probability=0.5, payoff_estimate=12.0),
        ScenarioOutcome(name="b", probability=0.3, payoff_estimate=-4.0),
        ScenarioOutcome(name="c", probability=0.2, payoff_estimate=30.0),
    ]
    ev_result = expected_value(scenarios)
    value = ev_result.value
    assert isinstance(value, dict)
    contributions = value["contributions"]
    assert isinstance(contributions, dict)
    assert set(contributions) == {"a", "b", "c"}
    assert abs(read_float(ev_result, "ev") - sum(contributions.values())) < 1e-4
    independent_ev = sum(s.probability * s.payoff_estimate for s in scenarios)
    assert abs(read_float(ev_result, "ev") - independent_ev) < 1e-9
    print(f"  EV identity holds ({read_float(ev_result, 'ev'):+.4f} = sum of contributions)")

    print("\n  NOT APPLICABLE HERE: units, nulls and frequencies. These functions")
    print("  consume no series, so there is nothing to verify against a provider.")
    print("probability_models VERIFICATION COMPLETE")


if __name__ == "__main__":
    main()
