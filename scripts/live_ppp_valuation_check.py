"""Live wiring check: a real spot rate + a FETCHED PPP leg -> Section 20.9's
``ppp_valuation``.

Not a test. This directory holds operator scripts, deliberately excluded from
the default test run because they hit the network. Run with::

    uv run python scripts/live_ppp_valuation_check.py

Section 21.0: unit tests prove the arithmetic, this proves the WIRING — the
units, the sign, the horizon discipline, and whether the numbers that come out
are the numbers the specification says should come out.

The two live legs, and what changed at D-117
-------------------------------------------
Until D-117 ``ppp_valuation`` took a **LIVE spot rate** and a **MANUAL PPP
conversion factor**: Section 21.1 marked ``ppp_implied_rate`` BLOCKED -> MANUAL
on the premise *"no clean free API"*. **That premise was measured false** (the
D-043 FALSE-BLOCK class) — the World Bank REST API is reachable — so BOTH legs
are now fetched, and this check fetches both:

* ``EURUSD`` (yfinance, via the project's OpenBB client) — a real spot level.
* ``PA.NUS.PPP`` (World Bank REST, direct — NOT through OpenBB) for the euro
  leg (DEU) and the numeraire leg (USA), combined into a PPP-implied rate.

The fetched PPP leg is a **DISCLOSED VINTAGE, not a point-in-time vintage**: the
World Bank offers no point-in-time selector (measured against all four free
sources the operator named — ``docs/PLAN_ppp_source.md`` §6). The check prints
the publication date and the observation year beside the number, and confirms
the model repeats that provenance in its own ``limitations``.

What this check establishes
---------------------------

1. **The spot route returns enough observations and the level is plausible.**
   A discontinued or empty route is BLOCKED, and a spot outside a wide EUR/USD
   band is a data error rather than a market state.

2. **The FETCHED PPP legs are plausible and the ratio is the estimand.** The
   euro leg is asserted into a band, the numeraire leg is asserted to be the
   definitional 1, and the implied rate is RECOMPUTED as
   ``factor(DEU) / factor(USA)`` so the published figure is shown to be that
   ratio rather than a raw factor passed through.

3. **The deviation is recomputed from the two published levels.** The published
   ``deviation_pct`` must equal ``(spot - ppp) / ppp * 100`` recomputed here,
   and ``ratio`` must equal ``spot / ppp`` — so the two published forms are
   shown to be the same fact, not two independent claims.

4. **The sign and the label agree, BOTH directions.** Exercised by perturbing
   the PPP leg around the live spot, so the check does not depend on which side
   the market happens to be on today.

5. **The horizon gates a WARNING, not a LABEL.** The SAME inputs at a tactical
   horizon and at a long horizon must produce the SAME ``status`` and the SAME
   ``deviation_pct``, while the tactical call gains the no-tactical-timing
   warning and the long call does not.

6. **The fetched leg's provenance is disclosed.** The result's ``limitations``
   must name the fetch, the DISCLOSED-VINTAGE distinction, and the World Bank
   source — so the live output carries the same caveat the docstring makes.

Exit code is 0 on success and 1 on any failed check.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from macro_engine.config import get_settings  # noqa: E402
from macro_engine.data_layer.openbb_client import OpenBBClient  # noqa: E402
from macro_engine.data_layer.world_bank_client import (  # noqa: E402
    fetch_ppp_conversion_factor,
    implied_rate_from_factors,
)
from macro_engine.models.contracts import ModelResult  # noqa: E402
from macro_engine.models.fx_carry import PPPInputs, ppp_valuation  # noqa: E402

#: The two legs of the PPP-implied EURUSD rate. DEU is the euro container (the
#: World Bank's EMU aggregate measures 0 points), USA is the definitional
#: numeraire. Kept as named constants so the check prints WHICH pair it used.
_DOMESTIC_ISO3 = "DEU"
_FOREIGN_ISO3 = "USA"

#: Plausible band for a spot EUR/USD level. Wide on purpose: the point is to
#: fail on a transposed pair or a percent-where-a-level mistake, not to pin a
#: regime.
_SPOT_BAND = (0.5, 2.0)

#: Plausible band for the euro-area PPP conversion factor. Narrower than the
#: spot band because a PPP level is a long-run average and moves far less than a
#: market rate — but still wide enough not to pin a vintage.
_PPP_BAND = (0.4, 1.5)

#: Horizons the check compares. ``_LONG_HORIZON`` must exceed the configured
#: tactical minimum by a wide margin; ``_TACTICAL_HORIZON`` must sit below it.
#: Both are asserted against the live leaf rather than assumed.
_LONG_HORIZON = 10.0
_TACTICAL_HORIZON = 0.25


def _fetch(symbols: dict[str, tuple[str, str]]) -> dict[str, pd.Series]:
    client = OpenBBClient()
    out: dict[str, pd.Series] = {}
    for label, (provider, endpoint) in symbols.items():
        frame = client.fetch_series(
            provider=provider,
            endpoint=endpoint,
            params={"symbol": label},
            series_label=label,
        )
        out[label] = frame.set_index("date")["value"].astype(float).sort_index()
    return out


def _last(series: pd.Series) -> tuple[float, str]:
    return float(series.iloc[-1]), str(series.index[-1])


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


def main() -> int:
    failures: list[str] = []

    print("=" * 78)
    print("SECTION 20.9 PPP VALUATION — LIVE WIRING CHECK")
    print("=" * 78)

    print("  fetching the LIVE leg via OpenBB:")
    raw = _fetch({"EURUSD": ("yfinance", "currency.price.historical")})

    # --- (1) the spot route returns enough observations --------------------
    print()
    print("  series (last value @ date):")
    for label, series in raw.items():
        value, date = _last(series)
        print(f"    {label:<22} n={len(series):<6} {value:>12.6f}  @ {date}")
        if len(series) < 60:
            failures.append(
                f"{label} returned only {len(series)} observations — too few to "
                f"trust; a route that is empty or discontinued is BLOCKED"
            )

    # --- (1b) the spot is a plausible LEVEL --------------------------------
    spot, spot_date = _last(raw["EURUSD"])
    print()
    print("  unit guard — the spot must read as a LEVEL, not a percent or a rate:")
    low, high = _SPOT_BAND
    status = "OK" if low < spot < high else "OUT-OF-BAND"
    print(f"    EURUSD spot      {spot:8.4f}     [{status}]  @ {spot_date}")
    if not low < spot < high:
        failures.append(
            f"EURUSD reads {spot}, outside the plausible level band {_SPOT_BAND} — "
            f"a transposed pair or a percent-where-a-level error, which would make "
            f"the deviation meaningless"
        )

    # --- (1c) the PPP legs are FETCHED from the World Bank ------------------
    print()
    print("  the PPP legs (D-117: FETCHED from the World Bank REST API, direct):")
    domestic = fetch_ppp_conversion_factor(_DOMESTIC_ISO3)
    foreign = fetch_ppp_conversion_factor(_FOREIGN_ISO3)
    plow, phigh = _PPP_BAND
    pstatus = "OK" if plow < domestic.value < phigh else "OUT-OF-BAND"
    print(f"    {domestic.vintage_label}")
    print(f"    {_DOMESTIC_ISO3} factor        {domestic.value:8.6f}     [{pstatus}]")
    if not plow < domestic.value < phigh:
        failures.append(
            f"the euro leg {domestic.value} is outside the plausible band "
            f"{_PPP_BAND} — a unit error in the fetched input"
        )
    # The USA leg is the definitional 1 (LCU per international $). Asserted,
    # not assumed: if it ever moved, the estimand would need re-deriving.
    if abs(foreign.value - 1.0) > 1e-9:
        failures.append(
            f"the numeraire leg ({_FOREIGN_ISO3}) is {foreign.value}, expected "
            f"exactly 1 — the international dollar IS the US dollar, so a "
            f"non-unit factor means the wrong series was read"
        )
    print(f"    {_FOREIGN_ISO3} factor        {foreign.value:8.6f}     [OK]")

    # The estimand is the RATIO. Recompute it from the two factors so the
    # published figure is shown to be that ratio, not a raw factor.
    ppp_implied = implied_rate_from_factors(domestic, foreign)
    print(
        f"    PPP-implied {_DOMESTIC_ISO3}/{_FOREIGN_ISO3}  {ppp_implied:8.6f}  "
        f"(= {domestic.value} / {foreign.value})"
    )

    # --- (2) the deviation is recomputed from the two published levels -----
    tactical = get_settings().fx_carry.ppp_tactical_horizon_value
    if not tactical < _LONG_HORIZON:
        failures.append(
            f"_LONG_HORIZON {_LONG_HORIZON} must exceed the configured tactical "
            f"minimum {tactical}, or the check compares two of the same case"
        )
    if not tactical > _TACTICAL_HORIZON:
        failures.append(
            f"_TACTICAL_HORIZON {_TACTICAL_HORIZON} must sit below the configured "
            f"minimum {tactical}, or the warning it expects cannot fire"
        )

    # Exercised through the MODEL's own fetch path (pair, no explicit rate), so
    # this proves the wiring a caller actually gets — not just the client.
    result = ppp_valuation(
        PPPInputs(
            spot_rate=spot,
            domestic_iso3=_DOMESTIC_ISO3,
            foreign_iso3=_FOREIGN_ISO3,
            horizon_years=_LONG_HORIZON,
        )
    )
    published_ppp = _number(result, "ppp_implied_rate")
    published_dev = _number(result, "deviation_pct")
    published_ratio = _number(result, "ratio")
    expected_dev = (spot - ppp_implied) / ppp_implied * 100.0

    print()
    print("  (2) the published deviation is recomputed from the published levels:")
    print(f"    model-fetched PPP leg   {published_ppp:.6f}   (client {ppp_implied:.6f})")
    if abs(published_ppp - ppp_implied) > 1e-9:
        failures.append(
            f"the model's fetched PPP leg {published_ppp} disagrees with the "
            f"client's {ppp_implied} — the model and this check fetched "
            f"different numbers, so at least one is not the documented route"
        )
    print(f"    spot {spot:.6f} vs PPP {published_ppp:.6f}")
    print(f"    deviation_pct     published {published_dev:+.4f}   recomputed {expected_dev:+.4f}")
    # The published field is round(x, 2); the tolerance is the rounding step
    # (5e-3), taken from the COARSER side's published precision (lesson 5cu).
    if abs(published_dev - expected_dev) > 5e-3:
        failures.append(
            f"published deviation {published_dev} disagrees with the recomputed "
            f"{expected_dev} by more than the 2-place rounding step"
        )
    if abs(published_ratio - spot / published_ppp) > 5e-7:
        failures.append(
            f"published ratio {published_ratio} disagrees with spot/ppp "
            f"{spot / published_ppp} by more than the 6-place rounding step"
        )
    print(
        f"    ratio             published {published_ratio:.6f}   "
        f"recomputed {spot / published_ppp:.6f}"
    )

    # --- (3) the sign and the label agree, BOTH directions -----------------
    print()
    print("  (3) the sign and the label agree, exercised in BOTH directions:")
    # A PPP leg BELOW the live spot must read overvalued (positive deviation);
    # one ABOVE must read undervalued. The live spot fixes which is which, so
    # both are constructed around it rather than assuming a side.
    over = ppp_valuation(
        PPPInputs(spot_rate=spot, ppp_implied_rate=spot * 0.8, horizon_years=_LONG_HORIZON)
    )
    under = ppp_valuation(
        PPPInputs(spot_rate=spot, ppp_implied_rate=spot * 1.2, horizon_years=_LONG_HORIZON)
    )
    for name, res, want_label, want_sign in (
        ("leg below spot", over, "overvalued", +1),
        ("leg above spot", under, "undervalued", -1),
    ):
        label = _label(res, "status")
        dev = _number(res, "deviation_pct")
        ok = label == want_label and (dev > 0) == (want_sign > 0)
        print(
            f"    {name:<16} status={label:<12} deviation={dev:+8.4f}  [{'OK' if ok else 'FAIL'}]"
        )
        if not ok:
            failures.append(
                f"{name}: expected {want_label} with a "
                f"{'positive' if want_sign > 0 else 'negative'} deviation, got "
                f"{label} with {dev}"
            )

    # --- (4) the horizon gates a WARNING, never a LABEL --------------------
    print()
    print("  (4) the horizon gates a WARNING, NOT a label:")
    tactical_call = ppp_valuation(
        PPPInputs(
            spot_rate=spot,
            domestic_iso3=_DOMESTIC_ISO3,
            foreign_iso3=_FOREIGN_ISO3,
            horizon_years=_TACTICAL_HORIZON,
        )
    )
    same_label = _label(tactical_call, "status") == _label(result, "status")
    same_dev = _number(tactical_call, "deviation_pct") == published_dev
    tac_warns = any("tactical minimum" in w for w in tactical_call.warnings)
    long_quiet = not any("tactical minimum" in w for w in result.warnings)
    print(f"    status equal at both horizons:      {same_label}")
    print(f"    deviation equal at both horizons:   {same_dev}")
    print(f"    tactical horizon warns:             {tac_warns}")
    print(f"    long horizon silent:                {long_quiet}")
    for ok, msg in (
        (same_label, "the horizon moved the STATUS — it must gate a warning only"),
        (same_dev, "the horizon moved the DEVIATION — it must gate a warning only"),
        (tac_warns, "the tactical horizon did not warn"),
        (long_quiet, "the long horizon warned about tactical timing"),
    ):
        if not ok:
            failures.append(msg)

    # --- (5) the fetched leg's provenance is disclosed ---------------------
    print()
    print("  (5) the FETCHED leg's provenance is disclosed on the live output:")
    limitations = " | ".join(result.limitations)
    discloses = (
        "FETCHED" in limitations
        and "DISCLOSED VINTAGE" in limitations
        and "World Bank" in limitations
        and "no point-in-time selector" in limitations
    )
    print(f"    limitations name the fetch, the vintage distinction, the source: {discloses}")
    print(f"    confidence (model-specific cap):          {result.confidence}")
    if not discloses:
        failures.append(
            "the result's limitations do not disclose the FETCHED, DISCLOSED-VINTAGE "
            "PPP leg — the live output must carry the same caveat the docstring makes"
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
    print("PASS — ppp_valuation is wired correctly on live inputs")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
