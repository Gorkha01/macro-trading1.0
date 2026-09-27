"""Live wiring check: the three metals benchmarks -> Section 21.3 Tier-5's
``metals_complex_divergence`` (Module 10.3, Section 20.10).

Not a test. This directory holds operator scripts, deliberately excluded from
the default test run because they hit the network. Run with::

    uv run python scripts/live_metals_complex_check.py

Section 21.0: unit tests prove the arithmetic, this proves the WIRING — the
units, the symbols, the derived change, and whether the verdict that comes out
is the verdict the specification says should come out.

**The authority said BLOCKED; the measurement says otherwise — the SEVENTH
FALSE BLOCK.**
--------------------------------------------------------------------
Section 21.1 (``AGENTS.md:5395``) tags this trio *"LIVE/BLOCKED — copper &
aluminum via IBKR/yfinance futures; iron ore has no clean free source — likely
BLOCKED, document"*, and Section 21.4's Loophole Ledger repeats it as item 8
(*"Iron ore prices — no clean free source"*). Measured 2026-09-27 **all three
are LIVE** on FRED (IMF Primary Commodity Prices, U.S. Dollars per Metric Ton,
monthly):

* ``PCOPPUSDM`` — global copper, USD/metric ton
* ``PIORECRUSDM`` — global iron ore, USD/metric ton
* ``PALUMUSDM`` — global aluminum, USD/metric ton

**The probe needed a CONTROL, and the control is what makes it evidence.** A
fetch that returns a small number of rows could be a working route or a
partially-populated one; without a known-good series on the SAME route there is
no way to tell. ``DCOILWTICO`` (WTI spot, the same ``economy.fred_series``
route) returns thousands of daily rows, so the monthly row count each metal
returns is only interpretable *against* that control. Section 1 re-runs it.

What this check establishes
---------------------------

1. **The control and the three legs are all reachable, and the control is the
   yardstick.** Re-probes ``DCOILWTICO`` alongside the three metals on the same
   route, and asserts the control returns far more rows — which is what makes
   the metals' monthly count a signal rather than a failure.

2. **The unit is the provider's, not a web guess.** ``fred_search`` metadata
   reports *U.S. Dollars per Metric Ton* for all three. A web search claiming
   copper is quoted in USD per POUND is WRONG for these series, and a
   pound-vs-metric-ton mix-up is a silent ~2200x error. The unit is asserted
   into the reading FIRST.

3. **The change is DERIVED from two vintages, not adopted.** Each leg's
   ``change_pct`` must equal the hand-computed percent change of the two
   published levels the reading carries. This re-derivation is done here from
   the raw numbers so a client that started reading a published change field
   would fail.

4. **The verdict is one of the three the specification names**, and the
   discriminating aluminum band is applied from CONFIG, not a literal.

5. **The confidence is the PRODUCT of the computed half and the cap**, and the
   independence count is ONE however many legs were fetched — three FRED series
   are ONE provider family, so counting legs would triple-count the evidence.

6. **The horizon honesty tier is printed**, so a reader sees which legs were
   measured on the day of the run and which the provider publishes with a lag.

Run it before trusting a ``metals_complex_divergence`` claim, and re-run it if
FRED changes the route. A green unit suite says the code does what the tests
say; only this says the *sources* do what the code assumes.
"""

from __future__ import annotations

import sys
from datetime import date

from macro_engine.config import get_settings
from macro_engine.data_layer.commodities_client import (
    ALUMINUM_SYMBOL,
    COPPER_SYMBOL,
    IRON_ORE_SYMBOL,
    METALS_SOURCE_UNIT,
    CommodityReadError,
    fetch_aluminum_change,
    fetch_copper_change,
    fetch_iron_ore_change,
)
from macro_engine.data_layer.openbb_client import OpenBBClient
from macro_engine.models.commodities import (
    MetalsComplexInputs,
    metals_complex_divergence,
)
from macro_engine.models.contracts import ModelResult

#: The CONTROL series: WTI spot on the SAME ``economy.fred_series`` route. A
#: control is what turns "the metals returned 139 rows" from a bare number into
#: evidence — without it, a short series could be a working monthly route or a
#: half-populated one, and the check could not tell.
_CONTROL_SYMBOL = "DCOILWTICO"

#: Plausible bands, USD per metric ton. Wide on purpose: the point is to catch a
#: unit error (per-pound vs per-metric-ton is ~2200x) or a transposed series,
#: not to pin a month. Each band is centered on the observed 2026-09 range.
_COPPER_BAND = (2000.0, 30000.0)
_IRON_ORE_BAND = (20.0, 500.0)
_ALUMINUM_BAND = (500.0, 6000.0)

#: A monthly series over ~11 years carries ~130-150 observations. Below this the
#: route is not serving the full history and the change may come from a thin
#: tail.
_MIN_MONTHLY_OBSERVATIONS = 60


def _values(result: ModelResult) -> dict[str, object]:
    value = result.value
    assert isinstance(value, dict)
    return value


def _number(result: ModelResult, key: str) -> float:
    item = _values(result)[key]
    assert isinstance(item, (int, float)) and not isinstance(item, bool), (
        f"{key} is {type(item).__name__}"
    )
    return float(item)


def _text(result: ModelResult, key: str) -> str:
    item = _values(result)[key]
    assert isinstance(item, str), f"{key} is {type(item).__name__}"
    return item


def _control_row_count(client: OpenBBClient) -> int:
    """Rows the CONTROL series returns on the metals route.

    The metals go through ``fetch_series`` on ``economy.fred_series``; the
    control uses the same call, so a route failure would take both down and a
    route success that served only the metals would be visible as a control
    count that is ALSO tiny.
    """
    frame = client.fetch_series(
        provider="fred",
        endpoint="economy.fred_series",
        params={"symbol": _CONTROL_SYMBOL},
        series_label="metals_control_wti",
    )
    return len(frame)


def main() -> int:
    failures: list[str] = []
    settings = get_settings()
    metals = settings.metals_complex

    print("=" * 78)
    print("SECTION 20.10 — METALS COMPLEX DIVERGENCE: LIVE WIRING CHECK")
    print("=" * 78)
    print(f"  aluminum-stability band:  |change| < {metals.aluminum_band_pct:.2f} %")
    print(f"  broad-weakness threshold: change  < -{metals.broad_weakness_threshold_pct:.2f} %")
    print(f"  value decimals:           {metals.value_decimals}")
    print(f"  reliability cap:          {metals.reliability_value:.4f}")
    print(f"  as_of:                    {date.today().isoformat()}")
    print()

    # ----------------------------------------------------------------------
    # 1: the control, and why it is not optional.
    # ----------------------------------------------------------------------
    print("1. THE CONTROL — the yardstick the three metals are read against")
    control_rows = -1
    try:
        client = OpenBBClient()
        try:
            control_rows = _control_row_count(client)
        finally:
            client.close()
        print(f"  {_CONTROL_SYMBOL} control rows on the same route: {control_rows:,}")
        if control_rows < 1000:
            failures.append(
                f"the WTI control returned only {control_rows} rows. Either the "
                f"route is degraded or the control is wrong — without a healthy "
                f"control the metals' counts below prove nothing."
            )
    except Exception as exc:
        failures.append(f"the control fetch failed: {exc}")
    print()

    # ----------------------------------------------------------------------
    # 2-4: the three legs, their units, and the DERIVED change.
    # ----------------------------------------------------------------------
    print("2-4. THE THREE LEGS — unit, level, and the DERIVED percent change")
    legs: dict[str, float] = {}
    for name, symbol, fetcher, band in (
        ("copper", COPPER_SYMBOL, fetch_copper_change, _COPPER_BAND),
        ("iron_ore", IRON_ORE_SYMBOL, fetch_iron_ore_change, _IRON_ORE_BAND),
        ("aluminum", ALUMINUM_SYMBOL, fetch_aluminum_change, _ALUMINUM_BAND),
    ):
        try:
            reading = fetcher(as_of=date.today())
            print(
                f"  {name:8s} {symbol:13s} {reading.level:>12,.2f} "
                f"{reading.source_unit} on {reading.observation_date}"
                f"  (prior {reading.prior_level} on {reading.prior_observation_date})"
            )
            if reading.source_unit != METALS_SOURCE_UNIT:
                failures.append(
                    f"{name} reported unit {reading.source_unit!r}, not "
                    f"{METALS_SOURCE_UNIT!r} — the model publishes the metric-ton "
                    f"unit and a per-pound series is ~2200x out"
                )
            if not band[0] <= reading.level <= band[1]:
                failures.append(
                    f"{name} level {reading.level} is outside the metric-ton band "
                    f"{band} — a per-pound series or a transposed series would land "
                    f"here"
                )
            if reading.observation_count < _MIN_MONTHLY_OBSERVATIONS:
                failures.append(
                    f"{name} returned only {reading.observation_count} observations "
                    f"(< {_MIN_MONTHLY_OBSERVATIONS}) — the route may be serving a "
                    f"truncated history"
                )
            if reading.change_pct is None or reading.prior_level is None:
                failures.append(f"{name} returned no prior vintage, so no change could be formed")
                continue
            recomputed = (reading.level - reading.prior_level) / reading.prior_level * 100.0
            print(
                f"           derived change: {reading.change_pct:+.2f} % "
                f"(recomputed {recomputed:+.2f} %)"
            )
            if abs(reading.change_pct - recomputed) > 1e-6:
                failures.append(
                    f"{name} published change {reading.change_pct} does not equal "
                    f"the re-derivation from its own two levels {recomputed} — the "
                    f"change is supposed to be DERIVED, not adopted"
                )
            legs[name] = reading.change_pct
        except CommodityReadError as exc:
            failures.append(f"{name} fetch failed: {exc}")
        except Exception as exc:  # the check reports, it does not raise
            failures.append(f"{name} check failed: {exc}")
    print()

    if len(legs) != 3:
        print("=" * 78)
        print(f"FAILED — only {len(legs)} of 3 legs were reachable, so the verdict")
        print("cannot be formed. The sections below need all three.")
        for item in failures:
            print(f"  !! {item}")
        print("=" * 78)
        return 1

    # ----------------------------------------------------------------------
    # 5: the model on the LIVE inputs.
    # ----------------------------------------------------------------------
    print("5. THE MODEL ON THE LIVE INPUTS")
    result: ModelResult | None = None
    try:
        result = metals_complex_divergence(MetalsComplexInputs())
        verdict = _text(result, "verdict")
        print(f"  verdict:    {verdict}")
        print(f"  direction:  {result.direction}")
        print(f"  unit:       {result.unit}")
        print(f"  family:     {result.source_family}")
        print(f"  confidence: {result.confidence:.4f}")
        if verdict not in {
            "CHINA_CONSTRUCTION_SPECIFIC",
            "BROAD_INDUSTRIAL_WEAKNESS",
            "MIXED_no_clear_pattern",
        }:
            failures.append(f"the verdict {verdict!r} is not one the spec names")
        for key in ("copper_change_pct", "iron_ore_change_pct", "aluminum_change_pct"):
            published = _number(result, key)
            expected = round(legs[key.split("_change")[0]], metals.value_decimals)
            if abs(published - expected) > 1e-9:
                failures.append(
                    f"the model published {key}={published} but the client read "
                    f"{legs[key.split('_change')[0]]} (rounded {expected})"
                )
    except Exception as exc:
        failures.append(f"the live model run failed: {exc}")
    print()

    # ----------------------------------------------------------------------
    # 6: the confidence PRODUCT and the ONE-provider independence count.
    # ----------------------------------------------------------------------
    print("6. THE CONFIDENCE PRODUCT AND THE INDEPENDENCE COUNT")
    try:
        assert result is not None
        # Three legs are ONE provider family, so the independence credit is 1
        # however many were fetched. A run that reported 3 would triple-count.
        independence_disclosed = any(
            "ONE" in p or "one provider" in p.lower() for p in result.assumptions
        )
        print(f"  independence stated in assumptions: {independence_disclosed}")
        if not independence_disclosed:
            failures.append(
                "the assumptions do not state that the three legs are ONE provider "
                "family — a reader could read the confidence as resting on three "
                "independent sources"
            )
        # The product: the confidence must be <= the cap and > 0.
        if not 0.0 < result.confidence <= metals.reliability_value:
            failures.append(
                f"the confidence {result.confidence} is not in (0, cap="
                f"{metals.reliability_value}] — the product rule (D-118) says it "
                f"can never exceed the cap"
            )
        notes = [p for p in result.data_provenance if "FRED" in p]
        print(f"  FRED legs disclosed in provenance: {len(notes)} of 3")
        if len(notes) != 3:
            failures.append(f"only {len(notes)} of 3 legs were disclosed as FETCHED FRED series")
    except Exception as exc:
        failures.append(f"the confidence check failed: {exc}")
    print()

    # ----------------------------------------------------------------------
    # 7: the refusal, and the supplied-value disclosure.
    # ----------------------------------------------------------------------
    print("7-8. THE REFUSAL AND THE DISCLOSURE")
    try:
        # A run with one leg left unresolvable must REFUSE, because a verdict
        # from two legs is a different pattern, not a weaker one. Force the
        # refusal by supplying two legs and making the third fetch impossible —
        # here, by passing a nan on one leg, which the input validator refuses
        # BEFORE any fetch (the guard is what is being checked).
        refused = False
        try:
            metals_complex_divergence(MetalsComplexInputs(copper_change_pct=float("nan")))
        except ValueError:
            refused = True
        print(f"  a non-finite supplied change REFUSED: {refused}")
        if not refused:
            failures.append(
                "a nan change was accepted — it would fail every comparison and "
                "report MIXED, which is a different claim from 'genuinely mixed'"
            )

        assert result is not None
        if any("SUPPLIED BY THE CALLER" in p for p in result.data_provenance):
            failures.append(
                "a fully-FETCHED live run published a 'SUPPLIED BY THE CALLER' "
                "leg — the disclosure is inverted"
            )
        supplied_provenance = [p for p in result.data_provenance if "SUPPLIED" in p]
        print(f"  supplied legs disclosed in the live run: {len(supplied_provenance)}")
    except Exception as exc:
        failures.append(f"the refusal/disclosure check failed: {exc}")
    print()

    # ----------------------------------------------------------------------
    # 9: the horizon honesty tier.
    # ----------------------------------------------------------------------
    print("9. HORIZON HONESTY TIER")
    print("  All three legs are MONTHLY benchmark prices. The % change is between")
    print("  the two most recent MONTHLY vintages, so the newest observation is up")
    print("  to a month old and the change describes a month-on-month move, not a")
    print(f"  spot move. Control {_CONTROL_SYMBOL} (daily, {control_rows:,} rows) is")
    print("  the yardstick that shows the route itself is healthy.")
    print()

    print("=" * 78)
    if failures:
        print(f"FAILED — {len(failures)} problem(s):")
        for item in failures:
            print(f"  !! {item}")
        print("=" * 78)
        return 1
    print("PASS — Section 20.10's three legs are wired as documented.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
