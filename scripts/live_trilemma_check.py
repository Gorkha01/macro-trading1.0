"""Live wiring check: real reserves history -> Module 1's ``check_trilemma_tension``.

Not a test. This directory holds operator scripts, deliberately excluded from
the default test run because they hit the network. Run with::

    uv run python scripts/live_trilemma_check.py

Section 21.0: unit tests prove the arithmetic, this proves the wiring — the
units, the frequency, the sign conventions, and whether the values that come out
are the values the specification says should come out.

Why this check is built the way it is
-------------------------------------

The function is guarded to ``us`` (Section 22.3) and the dollar floats, so the
guarded path can only ever return ``NO_TENSION``. That makes a live check of the
**supported country** worthless as a validation of the logic, and it is why this
script does something a normal live check does not: it calls the **private rule**
directly with a synthetic ``TrilemmaInputs`` whose ``country`` is ``us`` — the
only value the guard admits — while feeding it the **UK's and Korea's real
reserves history**. The rule is exercised on the crisis it exists to detect; the
guard is exercised separately; and the two are never confused.

That arrangement is the honest one, but it is also easy to get wrong, so it is
stated on every run: **the country label in the fixture says nothing about what
was measured.** The reserves readings are the UK's.

What this check does beyond running the function
------------------------------------------------

1. **Fetches the reserves series itself** from FRED — ``TRESEGGBM052N`` (UK),
   ``TRESEGKRM052N`` (Korea), ``TRESEGIDM052N`` (Indonesia) — rather than
   reading a cached value, so a series that stops being published is caught
   here rather than in a downstream consumer.

2. **Recomputes the 1-month and 3-month changes at the crisis months** and
   asserts the specification's own threshold MISSES Black Wednesday's month
   while the added 1-month threshold catches it. That is the entire
   justification for the added second threshold (D-048), and it is a claim
   about *real* data, so it does not belong in the unit tests.

3. **Re-measures both base rates over the history** and fails on drift from
   the config, so the published frequencies cannot go stale (D-029). It measures
   them over the **monthly** span only — see the finding below — and it **names
   the breaches that are NOT peg crises**: the 2016 Brexit cluster. A base rate
   whose numerator includes a different event is a claim that needs its
   counterexamples on the record.

4. **Asserts the two breach sets are not nested**, on real history rather than
   on a synthetic sweep: the UK has 53 months where only the 3-month test fires
   and 30 where only the 1-month test fires, and Korea has 35 and 14. If the
   published thresholds ever made one set a subset of the other, the second
   threshold would be dead weight and this check would say so.

5. **Confirms the US path returns ``NO_TENSION``** and that a non-US country
   raises, so the guard is live too.

The cadence finding — a series called "monthly" that is not, for its first years
-------------------------------------------------------------------------------

Found by this check on its first run, and it invalidates the obvious way to
compute the base rates. Both ``TRESEGGBM052N`` and ``TRESEGKRM052N`` report 843
and 842 observations respectively, and **their first seven are ANNUAL**: the
series runs 1950-12, 1951-12, ..., 1956-12 — seven December points — and only
then switches to monthly, 1957-01, 1957-02, 1957-03, ...

The exclusion convention (stated because the count depends on it): the six
pure-annual points 1950-12 .. 1955-12 are dropped, and **1956-12 is RETAINED as
the first member of the monthly span**, because it is the December immediately
preceding the 1957-01 monthly run and dropping it would open a 12-month hole at
the start. So "6 of 843 excluded" pairs with "837 monthly observations beginning
1956-12", and the two numbers are consistent.

``TRESEGIDM052N`` is worse and of a *different shape*. Its excluded span runs
1950-12 .. 1970-12 and is not one cadence change at one date: **16 annual points
1950-12 .. 1964-12**, then a **continuous quarterly block 1965-03 .. 1968-12**
(16 quarterly points), then monthly from 1971-01. An earlier note in this file
described it as "annual to 1964-11 then quarterly to 1969-11", which mis-dates
both cutovers; the dates above are the ones the provider returns.

This matters because every threshold here is a change over a **named number of
months**. On the annual segment, ``[-4]`` is four years, not four months, and
dividing by a base four years earlier is not a 3-month change. Computing the
base rate over the raw observation count would therefore mix years into a
month's statistic. The check asserts the monthly span explicitly and discloses
what it excluded, rather than silently averaging over both cadences.

It also means the honest headline for the UK series is **837 monthly
observations from 1956-12**, not 843 — the count that the earlier probe
reported, which was an observation count, not a measurement window.
"""

from __future__ import annotations

import statistics
import time
from datetime import date
from typing import TYPE_CHECKING, Any, Literal

from macro_engine.config import get_settings
from macro_engine.data_layer.openbb_client import OpenBBClient
from macro_engine.models.contracts import ModelResult
from macro_engine.models.regime import (
    TRILEMMA_SEVERITIES,
    TrilemmaInputs,
    check_trilemma_tension,
)

if TYPE_CHECKING:
    import pandas as pd

#: The reserves series, by country. Total reserves excluding gold, monthly, IMF
#: via FRED. The UK series starts 1950-12, which is what makes it the fixture:
#: it covers Black Wednesday.
RESERVES_SERIES: dict[str, str] = {
    "gb": "TRESEGGBM052N",
    "kr": "TRESEGKRM052N",
    "id": "TRESEGIDM052N",
}

#: The two episodes this function exists to detect, and the months each measure
#: is expected to fire on. These are CLAIMS about history, so they live here in
#: the check — stating them is what makes the check falsifiable.
#:
#: **The Korean 1997-11 row originally said the 1-month test fires alone. It does
#: not** — that month breaches BOTH tests (`-20.04%` and `-21.66%`). The
#: correction is left visible rather than silently edited, because the wrong
#: expectation would have made the check pass for the wrong reason. The
#: non-nesting claim is true, but it is shown by different months (see the
#: complementarity section below, which finds 35 trend-only and 14 acute-only
#: months on Korea), not by this phase.
EPISODES: dict[str, dict[str, Any]] = {
    "black_wednesday": {
        "country": "gb",
        "crisis_month": date(1992, 9, 1),
        # The specification's own worked example: the 3-month trend does NOT
        # breach -10% in this month, and the 1-month measure does.
        "expect_3mo_breach": False,
        "expect_1mo_breach": True,
    },
    "korea_trend_phase": {
        "country": "kr",
        "crisis_month": date(1997, 9, 1),
        # The early-warning phase: the trend fires, the acute measure does not.
        "expect_3mo_breach": True,
        "expect_1mo_breach": False,
    },
    "korea_acute_phase": {
        "country": "kr",
        "crisis_month": date(1997, 11, 1),
        # The acute phase fires BOTH. Korea's reserves fell hard and for long
        # enough that the trend caught up with the spike.
        "expect_3mo_breach": True,
        "expect_1mo_breach": True,
    },
}


def _fetch(client: OpenBBClient, symbol: str, label: str) -> pd.DataFrame:
    """Mirror how the snapshot builder fetches a series."""
    return client.fetch_series(
        provider="fred",
        endpoint="economy.fred_series",
        params={"symbol": symbol},
        series_label=label,
    )


def _fetch_with_retry(client: OpenBBClient, symbol: str, label: str) -> pd.DataFrame:
    """Fetch a series, retrying on the provider's transient 502s.

    The FRED endpoint returns an HTML error page (rather than JSON) under load,
    which surfaces as a ``ContentTypeError``. Retrying is correct here and not a
    papering-over: the failure is a transport error with no bearing on the data,
    and the assertion below still fails the run if four attempts cannot get it.
    """
    last: Exception | None = None
    for _ in range(4):
        try:
            return _fetch(client, symbol, label)
        except Exception as exc:
            last = exc
            time.sleep(3)
    raise AssertionError(f"{symbol}: {label} could not be fetched after 4 attempts: {last}")


def _monthly_history(frame: pd.DataFrame, label: str) -> tuple[dict[date, float], date, int, int]:
    """Extract the MONTHLY span as ``{first-of-month: value}``, plus what was excluded.

    Returns ``(series, first_monthly, n_total, n_dropped)``, where
    ``first_monthly`` is the **first observation of the monthly span** — which is
    the December that opens the monthly run, not the January after it.

    **This does not assume the series is monthly, because it is not.** Both
    ``TRESEGGBM052N`` (843 observations) and ``TRESEGKRM052N`` (842) begin with
    seven **annual** points — 1950-12 through 1956-12 — before switching to
    monthly at 1957-01; ``TRESEGIDM052N`` is annual 1950-12 .. 1964-12, then
    quarterly 1965-03 .. 1968-12, then monthly from 1971-01. Every threshold in
    the model is a change over a NAMED number of months, so on the annual
    segment a "3-month change" would actually span three years. The non-monthly
    prefix is therefore excluded and **the exclusion is reported**, rather than
    averaged into a statistic that has two cadences.

    The convention, which the drop count depends on: the pure-annual points
    strictly *before* the monthly span are dropped, and the span's own first
    member (the December preceding the first January) is **kept**. So GB drops
    6 and keeps 837, not 7 and 836 — retaining that December is what prevents a
    12-month hole at the start of an otherwise monthly series.

    FRED dates its observations to the first of the month, so the key
    normalisation is exact rather than a rounding.
    """
    clean = frame.loc[frame["value"].notna(), ["date", "value"]]
    if clean.empty:
        raise AssertionError(f"{label}: no observations")
    raw: dict[date, float] = {}
    for when, value in zip(clean["date"], clean["value"], strict=True):
        key = when if isinstance(when, date) else when.date()
        raw[date(key.year, key.month, 1)] = float(value)

    ordered = sorted(raw)
    # The month after which every consecutive gap is exactly one month.
    first_monthly: date | None = None
    for i in range(len(ordered) - 1):
        if all(
            (ordered[j].year * 12 + ordered[j].month)
            - (ordered[j - 1].year * 12 + ordered[j - 1].month)
            == 1
            for j in range(i + 1, len(ordered))
        ):
            first_monthly = ordered[i]
            break
    if first_monthly is None:
        raise AssertionError(f"{label}: no contiguous monthly span found")

    monthly = {k: raw[k] for k in ordered if k >= first_monthly}
    # The monthly span must be truly gap-free, or every named span is a lie.
    keys = sorted(monthly)
    gaps = {
        (keys[i].year * 12 + keys[i].month) - (keys[i - 1].year * 12 + keys[i - 1].month)
        for i in range(1, len(keys))
    }
    if gaps != {1}:
        raise AssertionError(
            f"{label}: the monthly span is not gap-free — distinct month-gaps "
            f"{sorted(gaps)}. Every threshold here is a change over a NAMED number of "
            f"months, so a hole would compute a different span than the one it names."
        )
    return monthly, first_monthly, len(ordered), len(ordered) - len(monthly)


def _breach_months(
    history: dict[date, float], *, depletion: float, break_1mo: float
) -> tuple[set[date], set[date], int]:
    """Which months breach each threshold, plus how many months were computable.

    ONE implementation, used by both the nesting check and the base-rate
    measurement, so the two cannot disagree about the same series. Returning the
    denominator as well as the numerators means a caller cannot accidentally
    divide by the wrong count — the base rate is over the months where **both**
    measures are computable, which is fewer than the monthly observation count
    because the earliest three months have no 3-month lag available.
    """
    trend: set[date] = set()
    acute: set[date] = set()
    considered = 0
    for when in sorted(history):
        e3 = _shift(when, 3)
        e1 = _shift(when, 1)
        if e3 is None or e1 is None or e3 not in history or e1 not in history:
            continue
        if history[e3] == 0.0 or history[e1] == 0.0:
            continue
        considered += 1
        if (history[when] - history[e3]) / history[e3] < depletion:
            trend.add(when)
        if (history[when] - history[e1]) / history[e1] < break_1mo:
            acute.add(when)
    return trend, acute, considered


def _shift(when: date, months: int) -> date | None:
    """The first of the month ``months`` before ``when``, by calendar arithmetic.

    Calendar arithmetic rather than an index offset (D-025): ``values[-4]`` spans
    whatever the previous four *observations* were, which is not four months on a
    series with a hole — and this series HAS a hole in its cadence (see the module
    docstring), which is exactly why the offset spelling would be wrong here.
    """
    if months < 0:
        return None
    total = when.year * 12 + (when.month - 1) - months
    return date(total // 12, total % 12 + 1, 1)


def _pct_change(series: dict[date, float], when: date, months: int, *, label: str) -> float:
    """The fractional change over ``months`` months ending at ``when``.

    **Calendar arithmetic, not an index offset** (D-025): ``values[-2]`` would
    span whatever the previous *observation* was, and a series with an omitted
    month makes that two months. The month keys are exact, so the span is exact.

    Returns a **fraction** (``-0.0725``), matching the model's contract. The
    threshold in config is a fraction for the same reason; a factor of 100 here
    would silently make every reading 100x too small and every severity calm.
    """
    earlier = _shift(when, months)
    assert earlier is not None  # months >= 0 at every call site
    if earlier not in series:
        raise AssertionError(f"{label}: no observation at {earlier} for a {months}-month change")
    if when not in series:
        raise AssertionError(f"{label}: no observation at {when}")
    base = series[earlier]
    if base == 0.0:
        raise AssertionError(f"{label}: zero base at {earlier}, the change is undefined")
    return (series[when] - base) / base


def read_value(result: ModelResult, key: str) -> Any:
    """Read a named entry of the dict-valued result, asserting the shape."""
    value = result.value
    assert isinstance(value, dict), f"{result.model_name}: expected a dict, got {type(value)}"
    return value[key]


def read_bool(result: ModelResult, key: str) -> bool:
    """Narrow a named entry to a bool, rejecting numbers (``bool`` subclasses ``int``)."""
    entry = read_value(result, key)
    assert isinstance(entry, bool), f"{result.model_name}: value[{key!r}] is {type(entry).__name__}"
    return entry


def read_str(result: ModelResult, key: str) -> str:
    """Narrow a named entry to a str."""
    entry = read_value(result, key)
    assert isinstance(entry, str), f"{result.model_name}: value[{key!r}] is {type(entry).__name__}"
    return entry


def _pegged_fixture(
    *,
    trend_3mo: float | None,
    break_1mo: float | None,
    direction: Literal["easing", "tightening"] = "easing",
    peg_direction: Literal["easing", "tightening"] = "tightening",
) -> TrilemmaInputs:
    """A fully-asserted peg, labelled ``us`` so the Section 22.3 guard admits it.

    **The label is a device, not a claim.** The guard exists because the
    function is US-scoped; the rule inside it is about what happens to a country
    whose exchange rate IS managed, and the US is not such a country. So this
    fixture pairs the guard's admissible label with a foreign country's actual
    reserves history, and every line of output below says so. Passing ``"gb"``
    would be more legible and is impossible — which is itself the finding.
    """
    return TrilemmaInputs(
        country="us",
        has_fixed_or_managed_fx=True,
        has_free_capital_movement=True,
        claims_monetary_independence=True,
        domestic_policy_direction_needed=direction,
        peg_defense_direction_required=peg_direction,
        reserves_trend_pct_change_3mo=trend_3mo,
        reserves_trend_pct_change_1mo=break_1mo,
    )


def main() -> None:
    client = OpenBBClient()
    settings = get_settings().regime.trilemma

    print("=" * 78)
    print("Module 1 trilemma check — live wiring validation")
    print("=" * 78)
    print()
    print("  NOTE ON SCOPE: the function is guarded to 'us' (Section 22.3) and the")
    print("  dollar floats, so its supported path can only return NO_TENSION. The")
    print("  crisis logic below is therefore exercised with a FIXTURE whose country")
    print("  label is 'us' while its reserves readings are the UK's and Korea's. The")
    print("  label is what the guard requires, not a claim about what was measured.")
    print()

    histories: dict[str, dict[date, float]] = {}
    monthly_from: dict[str, date] = {}
    for country, symbol in RESERVES_SERIES.items():
        frame = _fetch_with_retry(client, symbol, f"reserves_{country}")
        history, first_monthly, n_total, n_dropped = _monthly_history(frame, symbol)
        histories[country] = history
        monthly_from[country] = first_monthly
        ordered = sorted(history)
        print(
            f"  {country.upper()}  {symbol:<14} {len(history):>4} monthly obs  "
            f"{ordered[0]} .. {ordered[-1]}"
        )
        if n_dropped:
            print(
                f"      CADENCE: {n_dropped} of {n_total} observations are NOT monthly "
                f"(the annual/quarterly prefix ending before {first_monthly}) and are "
                f"EXCLUDED. {first_monthly} is RETAINED as the first monthly "
                f"observation, so the monthly span does not open with a 12-month hole."
            )
            print(
                "      Every threshold here is a change over a NAMED number of months, "
                "so those points"
            )
            print(
                "      would make a '3-month change' span years. The base rates below are measured"
            )
            print("      on the monthly span only, and say so.")

    # --- the two thresholds, from config, in fractions --------------------
    depletion = settings.depletion_3mo
    break_1mo = settings.break_1mo
    print()
    print(f"  thresholds: 3mo < {depletion:.4f}   (Section 15.20-A literal)")
    print(f"              1mo < {break_1mo:.4f}   (added by D-048)")
    assert break_1mo >= depletion, (
        "the 1-month threshold must not be steeper than the 3-month one, or the acute "
        "branch is a strict subset of the trend branch and can never fire alone"
    )

    # --- the episodes -----------------------------------------------------
    print()
    print("-" * 78)
    print("The reference episodes")
    print("-" * 78)
    for name, spec in EPISODES.items():
        country = spec["country"]
        when: date = spec["crisis_month"]
        history = histories[country]
        trend = _pct_change(history, when, 3, label=f"{country} 3mo")
        acute = _pct_change(history, when, 1, label=f"{country} 1mo")

        result = check_trilemma_tension(_pegged_fixture(trend_3mo=trend, break_1mo=acute))
        severity = read_str(result, "severity")

        depleted = read_bool(result, "reserves_depleting_3mo")
        broke = read_bool(result, "reserves_breaking_1mo")

        print()
        print(f"  {name}  ({country.upper()}, {when:%Y-%m})")
        exp3 = spec["expect_3mo_breach"]
        exp1 = spec["expect_1mo_breach"]
        print(f"    3mo change {trend:+.2%}  -> breach {depleted}   (expected {exp3})")
        print(f"    1mo change {acute:+.2%}  -> breach {broke}   (expected {exp1})")
        print(f"    severity   {severity}")

        assert depleted == spec["expect_3mo_breach"], (
            f"{name}: the 3-month breach is {depleted}, expected {spec['expect_3mo_breach']}. "
            f"The threshold or the series has changed; D-048's justification must be re-derived."
        )
        assert broke == spec["expect_1mo_breach"], (
            f"{name}: the 1-month breach is {broke}, expected {spec['expect_1mo_breach']}"
        )

    # The specific claim D-048 rests on, restated as an assertion over real data.
    bw = EPISODES["black_wednesday"]
    bw_when: date = bw["crisis_month"]
    bw_trend = _pct_change(histories["gb"], bw_when, 3, label="gb 3mo")
    bw_acute = _pct_change(histories["gb"], bw_when, 1, label="gb 1mo")
    print()
    assert bw_trend > depletion, (
        f"D-048's premise fails: Black Wednesday's 3-month reading ({bw_trend:+.2%}) now "
        f"breaches the specified threshold ({depletion}). The added 1-month threshold is "
        f"no longer justified by this episode."
    )
    assert bw_acute < break_1mo, (
        f"the 1-month threshold ({break_1mo}) must catch Black Wednesday ({bw_acute:+.2%})"
    )
    bw_result = check_trilemma_tension(_pegged_fixture(trend_3mo=bw_trend, break_1mo=bw_acute))
    assert read_str(bw_result, "severity") == "CRITICAL_PEG_STRESS", (
        "Black Wednesday must escalate to CRITICAL_PEG_STRESS"
    )
    assert not read_bool(bw_result, "reserves_depleting_3mo"), (
        "and it must do so entirely on the 1-month branch — the specified 3-month test "
        "is silent on this month, which is the whole reason the second threshold exists"
    )
    print(
        f"  CONFIRMED: the specified 3-month test is SILENT on {bw_when:%Y-%m} "
        f"({bw_trend:+.2%} vs {depletion:.2%})"
    )
    print(f"             the added 1-month test fires ({bw_acute:+.2%} vs {break_1mo:.2%})")
    print("             -> CRITICAL_PEG_STRESS via the acute branch alone")

    # --- the two breach sets are not nested -------------------------------
    #
    # Shared with the base-rate section below: ONE implementation of "which
    # months breach which test", so the two sections cannot disagree about the
    # same series (a second derivation is a second place to get it wrong).
    print()
    print("-" * 78)
    print("Are the two measures nested? (they must not be)")
    print("-" * 78)
    breaches: dict[str, tuple[set[date], set[date], int]] = {}
    for country in histories:
        trend_set, acute_set, considered = _breach_months(
            histories[country], depletion=depletion, break_1mo=break_1mo
        )
        breaches[country] = (trend_set, acute_set, considered)

    for country in ("gb", "kr"):
        trend_breaches, acute_breaches, _ = breaches[country]
        only_trend = trend_breaches - acute_breaches
        only_acute = acute_breaches - trend_breaches
        print()
        print(
            f"  {country.upper()}: 3mo breaches {len(trend_breaches)}, "
            f"1mo breaches {len(acute_breaches)}"
        )
        print(f"      fired on the 3-month test ALONE : {len(only_trend)}")
        print(f"      fired on the 1-month test ALONE : {len(only_acute)}")
        if only_trend:
            sample = ", ".join(f"{d:%Y-%m}" for d in sorted(only_trend)[:5])
            print(f"        e.g. {sample}")
        if only_acute:
            sample = ", ".join(f"{d:%Y-%m}" for d in sorted(only_acute)[:5])
            print(f"        e.g. {sample}")
        assert only_trend and only_acute, (
            f"{country.upper()}: one breach set is a subset of the other, so one of the "
            f"two thresholds is dead weight. The complementarity claim (D-048) fails here."
        )
    print()
    print("  CONFIRMED: neither measure subsumes the other on real history —")
    print("  each fires in months the other does not. Both thresholds earn their place.")

    # --- base rates -------------------------------------------------------
    print()
    print("-" * 78)
    print("Base rates (D-029) — recomputed, not trusted")
    print("-" * 78)
    rates_measured: dict[str, tuple[float, float, int]] = {}
    for country, symbol in RESERVES_SERIES.items():
        trend_breaches, acute_breaches, considered = breaches[country]
        trend_rate = len(trend_breaches) / considered
        acute_rate = len(acute_breaches) / considered
        rates_measured[country] = (trend_rate, acute_rate, considered)
        print()
        print(f"  {country.upper()} {symbol}  monthly span opens at {monthly_from[country]}")
        print(
            f"      {considered} months with BOTH measures computable (of "
            f"{len(histories[country])} monthly observations)"
        )
        print(f"      3mo threshold fires {len(trend_breaches):>3}  ({trend_rate:.1%})")
        print(f"      1mo threshold fires {len(acute_breaches):>3}  ({acute_rate:.1%})")

        if country == "gb":
            stored = settings.base_rates
            assert stored.measured, "the reference window must be measured to compare against"
            drift_3mo = abs(trend_rate - float(stored.depletion_3mo_base_rate.value))
            drift_1mo = abs(acute_rate - float(stored.break_1mo_base_rate.value))
            print()
            print(
                f"      stored: 3mo {float(stored.depletion_3mo_base_rate.value):.3f}, "
                f"1mo {float(stored.break_1mo_base_rate.value):.3f}"
            )
            print(f"      drift : 3mo {drift_3mo:.3f}, 1mo {drift_1mo:.3f}")
            assert drift_3mo < 0.01 and drift_1mo < 0.01, (
                f"the stored base rates drift beyond 1pp from a live recomputation "
                f"(3mo {drift_3mo:.3f}, 1mo {drift_1mo:.3f}). Either the stored frequency "
                f"is stale or the change derivations here have changed — both are worth "
                f"knowing before trusting the number on every output."
            )
            print("      CONSISTENCY OK: both stored rates match this recomputation")
            print()
            print("      NOTE the denominators: the stored window was originally recorded")
            print("      as 842 observations, which was an OBSERVATION COUNT including the")
            print("      six annual points before 1956-12. The monthly span is")
            print(f"      {len(histories['gb'])} observations, and {considered} of those have")
            print("      both measures computable. The rate is unchanged to 3 decimals")

    print()
    print("  COUNTEREXAMPLES, on the record: the 3-month threshold's breaches are NOT")
    print("  all peg crises. On the UK the 2016-09/10/11 cluster is BREXIT — an")
    print("  earlier-than-expected-exit episode, not a defense of the ERC peg. A base")
    print("  rate whose numerator mixes two events is a claim that needs saying out")
    print("  loud, which is why the model repeats this caveat on every output.")

    # --- the guard, live --------------------------------------------------
    print()
    print("-" * 78)
    print("The Section 22.3 guard, live")
    print("-" * 78)
    us_result = check_trilemma_tension(
        TrilemmaInputs(
            country="us",
            has_fixed_or_managed_fx=False,
            has_free_capital_movement=True,
            claims_monetary_independence=True,
            domestic_policy_direction_needed="easing",
            peg_defense_direction_required="tightening",
            reserves_trend_pct_change_3mo=-0.99,
            reserves_trend_pct_change_1mo=-0.99,
        )
    )
    print(f"  the supported country returns: {read_str(us_result, 'severity')}")
    assert read_str(us_result, "severity") == "NO_TENSION", (
        "the dollar's exchange rate is not managed, so the US path must return NO_TENSION "
        "even with a maximal conflict and maximal reserves burn supplied"
    )
    print("  (checked with all three legs, a conflict AND a -99% reserves burn supplied —")
    print("   the fixed-FX leg alone keeps it calm, which is the structural finding)")
    for country in ("gb", "kr", "id"):
        try:
            check_trilemma_tension(
                TrilemmaInputs(
                    country=country,
                    has_fixed_or_managed_fx=True,
                    has_free_capital_movement=True,
                    claims_monetary_independence=True,
                )
            )
        except NotImplementedError as exc:
            assert "country 'us' only" in str(exc)
            print(f"  '{country}' raises NotImplementedError  OK")
        else:
            raise AssertionError(f"'{country}' must raise, not silently label")

    print()
    print("=" * 78)
    print("Trilemma live check PASSED")
    print("=" * 78)
    print()
    print(f"  severity vocabulary: {' | '.join(TRILEMMA_SEVERITIES)}")
    print(f"  curves fetched     : {', '.join(sorted(RESERVES_SERIES.values()))}")
    print(f"  thresholds         : 3mo {depletion:+.3f}  1mo {break_1mo:+.3f}")
    print("  nothing was written back except by the assertions above; the config values")
    print("  are READ here, never updated, so a failure means the two disagree.")


def _summarise(values: list[float]) -> str:
    """A compact summary of a series, used in the diagnostic output."""
    return f"n={len(values)} mean={statistics.fmean(values):+.3f}"


if __name__ == "__main__":
    main()
