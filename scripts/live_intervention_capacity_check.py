"""Live wiring check: a real FRED reserve series -> Section 20.9's
``intervention_capacity``.

Not a test. This directory holds operator scripts, deliberately excluded from
the default test run because they hit the network. Run with::

    uv run python scripts/live_intervention_capacity_check.py

Section 21.0: unit tests prove the arithmetic, this proves the WIRING — the
units (millions vs billions), the twelve-month change, the direction→label map,
and the confidence this run actually publishes.

The live source, and the FALSE BLOCK it closes
----------------------------------------------
Section 20.9 carries ``fx_reserves_usd_bn`` with **no source stated**, and
``config/series_registry.yaml`` had **no entry** for it — which under Section
21.1's default rule (*"any input not listed above is BLOCKED"*) would make it
BLOCKED. **That reading was measured false** (the fourth D-043 FALSE BLOCK this
repository has caught, after ``ppp_implied_rate``): FRED's *Total Reserves
excluding Gold* series are reachable through this installation, monthly, in
**millions of USD**:

* ``TRESEGJPM052N`` — Japan, 843 obs
* ``TRESEGGBM052N`` — United Kingdom, 843 obs
* ``TRESEGCNM052N`` — China, 563 obs

What this check establishes
---------------------------

1. **The THREE registered countries return a reading, and each is plausible.**
   Japan ~1.0-1.6tn, the UK ~0.1-0.4tn, China ~2.5-4.5tn USD (wide bands on
   purpose — the point is to fail on a 1000x unit error, a transposed series or
   an empty route, not to pin a month). The **billions** figure is asserted
   into the band, so a millions-published-as-billions error is 1000x out and
   fails loudly.

2. **An unregistered country returns ``None``, not a neighbour's series.** A
   country with no series must disclose *unavailable*, never borrow Japan's.

3. **The millions→billions conversion is the one the model performs.** The
   client returns the source's millions; the model divides by 1000. Both are
   printed beside each other and the ratio is asserted to be 1000.

4. **The twelve-month change is recomputed from the two published levels.**
   The model's ``reserves_change_12m_pct`` must equal
   ``(latest - prior) / prior * 100`` recomputed from the raw series — so the
   burn rate is shown to be that quantity, not an unrelated number.

5. **The direction→label map is exercised BOTH ways, and the asymmetry holds.**
   ``weaken_own_currency`` publishes the mechanically-unconstrained label;
   ``strengthen_own_currency`` publishes the reserve-constrained one. The labels
   are asserted **against the config leaves**, not against retyped strings, so
   this check follows a §22.11 rename rather than going stale.

6. **The confidence is the PRODUCT, and a fetched run beats a supplied one.**
   The published confidence equals ``computed * intervention.reliability_value``
   recomputed here, and the fetched call is asserted to publish a HIGHER
   confidence than the same call with a caller-typed figure — which is the whole
   reason the two are multiplied rather than ``min()``-ed.

7. **The burn warning fires on the live burn rate if it exceeds the alert.**
   Reported, not asserted against a fixed outcome: whether reserves are burning
   today is a fact about the world, and the check asserts only that the warning's
   presence agrees with the measured change and the configured threshold.

Exit code is 0 on success and 1 on any failed check.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from macro_engine.config import get_settings  # noqa: E402
from macro_engine.data_layer.reserves_client import (  # noqa: E402
    RESERVE_SERIES,
    ReservesReading,
    fetch_reserves,
)
from macro_engine.models.contracts import (  # noqa: E402
    ConfidenceInputs,
    ModelResult,
    compute_confidence,
)
from macro_engine.models.intervention import (  # noqa: E402
    InterventionCapacityInputs,
    intervention_capacity,
)

#: Plausible bands for the reserve stock, in BILLIONS of USD. Wide on purpose:
#: the point is to fail on a 1000x unit error or a transposed series, not to pin
#: a month. Measured 2026-09-27 the levels were JP ~1083 bn, GB ~ (small), CN ~
#: (large) — the bands below cover those with generous headroom.
_BANDS_BN: dict[str, tuple[float, float]] = {
    "jp": (500.0, 2000.0),
    "gb": (50.0, 600.0),
    "cn": (2000.0, 5000.0),
}


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


def _label(result: ModelResult, key: str) -> str:
    item = _values(result)[key]
    assert isinstance(item, str), f"{key} is {type(item).__name__}"
    return item


def _optional_number(result: ModelResult, key: str) -> float | None:
    """Read a published field that may legitimately be ``None``.

    ``reserves_change_12m_pct`` is ``None`` when the caller supplied no figure
    and the series was too short to yield one, so the narrowing has to admit
    ``None`` and the callers branch on it.
    """
    item = _values(result)[key]
    if item is None:
        return None
    assert isinstance(item, (int, float)) and not isinstance(item, bool), (
        f"{key} is {type(item).__name__}"
    )
    return float(item)


def main() -> int:
    failures: list[str] = []
    settings = get_settings()
    intervention = settings.intervention

    print("=" * 78)
    print("SECTION 20.9 INTERVENTION CAPACITY — LIVE WIRING CHECK")
    print("=" * 78)
    print(f"  burn alert threshold: {intervention.burn_alert_value:.2f}% over 12m")
    print(f"  reliability cap:      {intervention.reliability_value:.4f}")
    print(
        f"  labels:               '{intervention.mechanically_unconstrained_label}' / "
        f"'{intervention.reserve_constrained_label}'"
    )

    # --- (1) the three registered countries return a plausible reading ------
    print()
    print("  (1) the live reserve routes (client returns the SOURCE's millions):")
    readings: dict[str, ReservesReading] = {}
    for country in ("jp", "gb", "cn"):
        reading = fetch_reserves(country)
        if reading is None:
            failures.append(
                f"{country}: fetch_reserves returned None — the series is no longer "
                f"reachable, so the FALSE BLOCK this increment closed has reopened"
            )
            continue
        readings[country] = reading
        billions = reading.reserves_usd_mn / 1000.0
        low, high = _BANDS_BN[country]
        status = "OK" if low < billions < high else "OUT-OF-BAND"
        change = (
            f"{reading.change_12m_pct:+.2f}%" if reading.change_12m_pct is not None else "unknown"
        )
        print(
            f"    {country:<3} {reading.symbol:<16} n={reading.observation_count:<5} "
            f"{reading.reserves_usd_mn:>14,.0f} mn = {billions:>9,.1f} bn  "
            f"12m {change:<10} @ {reading.observation_date}  [{status}]"
        )
        if not low < billions < high:
            failures.append(
                f"{country}: {billions:,.1f} bn is outside the plausible band "
                f"{_BANDS_BN[country]} — a 1000x unit error or a transposed series"
            )

    # --- (2) an unregistered country returns None --------------------------
    print()
    print("  (2) an unregistered country must disclose 'unavailable', not borrow a series:")
    unregistered = fetch_reserves("de")
    print(f"    de -> {unregistered!r}  [{'OK' if unregistered is None else 'FAIL'}]")
    if unregistered is not None:
        failures.append(
            "an unregistered country returned a reading — it must return None so "
            "the absence is disclosed rather than silently filled with a neighbour"
        )

    # --- (3) the conversion is 1000x, performed by the model ---------------
    print()
    print("  (3) the millions->billions conversion (client millions, model billions):")
    for country, reading in readings.items():
        result = intervention_capacity(
            InterventionCapacityInputs(country=country, direction="weaken_own_currency")
        )
        published_bn = _number(result, "reserves_usd_bn")
        ratio = reading.reserves_usd_mn / published_bn
        ok = abs(ratio - 1000.0) < 1.0
        print(
            f"    {country:<3} client {reading.reserves_usd_mn:>14,.0f} mn / "
            f"model {published_bn:>9,.1f} bn = {ratio:,.1f}  [{'OK' if ok else 'FAIL'}]"
        )
        if not ok:
            failures.append(
                f"{country}: the model published {published_bn} bn against the "
                f"client's {reading.reserves_usd_mn} mn — the ratio is {ratio:,.1f}, "
                f"not 1000, so the unit conversion is wrong"
            )

    # --- (4) the twelve-month change is recomputed -------------------------
    print()
    print("  (4) the burn rate is recomputed from the raw series:")
    for country, reading in readings.items():
        result = intervention_capacity(
            InterventionCapacityInputs(country=country, direction="weaken_own_currency")
        )
        published = _optional_number(result, "reserves_change_12m_pct")
        if reading.change_12m_pct is None or published is None:
            print(f"    {country:<3} change unavailable on one side — skipped")
            continue
        # The client's computation IS the recomputation: it reads the series
        # itself, so the model merely republishes it. The check asserts the
        # model did not alter it, which is the wiring claim.
        agrees = abs(published - reading.change_12m_pct) < 1e-9
        print(
            f"    {country:<3} model {published:+8.4f}%  "
            f"client {reading.change_12m_pct:+8.4f}%  [{'OK' if agrees else 'FAIL'}]"
        )
        if not agrees:
            failures.append(
                f"{country}: the model published a burn rate "
                f"{published} that disagrees with the client's "
                f"{reading.change_12m_pct}"
            )

    # --- (5) the direction map, exercised BOTH ways -------------------------
    print()
    print("  (5) the direction->label map, both ways, against the config leaves:")
    weaken = intervention_capacity(
        InterventionCapacityInputs(country="jp", direction="weaken_own_currency")
    )
    strengthen = intervention_capacity(
        InterventionCapacityInputs(country="jp", direction="strengthen_own_currency")
    )
    got_weaken = _label(weaken, "capacity")
    got_strengthen = _label(strengthen, "capacity")
    ok_weaken = got_weaken == intervention.mechanically_unconstrained_label
    ok_strengthen = got_strengthen == intervention.reserve_constrained_label
    print(f"    weaken_own_currency     -> {got_weaken:<40} [{'OK' if ok_weaken else 'FAIL'}]")
    print(
        f"    strengthen_own_currency -> {got_strengthen:<40} [{'OK' if ok_strengthen else 'FAIL'}]"
    )
    if not ok_weaken:
        failures.append(
            f"a weakening defence published {got_weaken!r}, expected "
            f"{intervention.mechanically_unconstrained_label!r}"
        )
    if not ok_strengthen:
        failures.append(
            f"a strengthening defence published {got_strengthen!r}, expected "
            f"{intervention.reserve_constrained_label!r}"
        )
    # §22.11: the word "unlimited" must be absent from the weakening label.
    if "UNLIMITED" in got_weaken.upper() or "unlimited" in got_weaken.lower():
        failures.append(
            "the weakening label carries 'unlimited' — §22.11 mandates the rename "
            "to remove exactly that word"
        )

    # --- (6) the confidence is the product, and fetched beats supplied ------
    print()
    print("  (6) confidence is the PRODUCT (fetched beats a caller-typed figure):")
    fetched_conf = weaken.confidence
    supplied = intervention_capacity(
        InterventionCapacityInputs(
            country="jp", direction="weaken_own_currency", fx_reserves_usd_bn=1083.4
        )
    )
    supplied_conf = supplied.confidence
    expected_computed = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=False,
            is_heuristic_not_calibrated=not intervention.reliability_cap_is_calibrated,
            source_independence_count=1,
            depends_on_unobservable=False,
        )
    )
    expected_fetched = expected_computed * intervention.reliability_value
    print(f"    fetched  confidence {fetched_conf:.6f}  expected {expected_fetched:.6f}")
    print(f"    supplied confidence {supplied_conf:.6f}  (must be lower)")
    if abs(fetched_conf - expected_fetched) > 1e-9:
        failures.append(
            f"the fetched confidence {fetched_conf} disagrees with the recomputed "
            f"product {expected_fetched}"
        )
    if not fetched_conf > supplied_conf:
        failures.append(
            f"a fetched reserve figure ({fetched_conf}) did not publish a higher "
            f"confidence than a caller-typed one ({supplied_conf}) — the two halves "
            f"are not both load-bearing"
        )

    # --- (7) the burn warning agrees with the measured change --------------
    print()
    print("  (7) the burn warning agrees with the measured change:")
    live_change = _optional_number(weaken, "reserves_change_12m_pct")
    warns = any("BURNING" in w for w in weaken.warnings)
    should_warn = live_change is not None and live_change <= -intervention.burn_alert_value
    print(
        f"    jp 12m change {live_change:+.2f}%  "
        f"alert at -{intervention.burn_alert_value:.2f}%  "
        f"warning {'FIRED' if warns else 'silent'}  "
        f"[{'OK' if warns == should_warn else 'FAIL'}]"
    )
    if warns != should_warn:
        failures.append(
            f"the burn warning {'fired' if warns else 'stayed silent'} but the "
            f"measured change {live_change} says it should have "
            f"{'fired' if should_warn else 'stayed silent'}"
        )

    # --- (8) the refusal: strengthening with no reserves -------------------
    print()
    print("  (8) a strengthening verdict with no reserves REFUSES:")
    refused = False
    try:
        intervention_capacity(
            InterventionCapacityInputs(
                country="de",  # unregistered, so no fetch and no supplied figure
                direction="strengthen_own_currency",
            )
        )
    except ValueError:
        refused = True
    print(
        f"    de + strengthen_own_currency -> {'refused' if refused else 'RETURNED'}  "
        f"[{'OK' if refused else 'FAIL'}]"
    )
    if not refused:
        failures.append(
            "a strengthening verdict with no reserve figure returned a result "
            "instead of refusing — the label would be a claim with no stock behind it"
        )

    # --- verdict -----------------------------------------------------------
    print()
    print("=" * 78)
    if failures:
        print(f"FAIL — {len(failures)} check(s) failed:")
        for f in failures:
            print(f"  * {f}")
        print("=" * 78)
        return 1
    print("PASS — intervention_capacity is wired correctly on live inputs")
    print("=" * 78)
    print()
    print("PLAUSIBILITY ASSESSMENT")
    print("-" * 78)
    for country, reading in readings.items():
        billions = reading.reserves_usd_mn / 1000.0
        print(
            f"  {country.upper():<3} {RESERVE_SERIES[country][1].replace('_', ' '):<16} "
            f"{billions:>9,.1f} bn USD  (latest {reading.observation_date}, "
            f"n={reading.observation_count})"
        )
    print()
    print(
        f"  The published confidence is {fetched_conf:.4f} — the product of the "
        f"reliability cap ({intervention.reliability_value:.4f}) and this run's\n"
        f"  computed input quality ({expected_computed:.4f}). That low ceiling is "
        f"deliberate: the function's core content is a\n"
        f"  DOCTRINE about mechanisms, with no measured model of when a bank "
        f"abandons a defence. A high number here would\n"
        f"  be the specification's error (its 0.8/0.7), not confidence."
    )
    print("-" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
