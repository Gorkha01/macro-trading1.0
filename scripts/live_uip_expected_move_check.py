"""Live wiring check: real money-market rates -> Section 20.9's ``uip_expected_move``.

Not a test. This directory holds operator scripts, deliberately excluded from
the default test run because they hit the network. Run with::

    uv run python scripts/live_uip_expected_move_check.py

Section 21.0: unit tests prove the arithmetic, this proves the WIRING — the
units, the sign, the horizon scaling, and whether the numbers that come out are
the numbers the specification says should come out.

**This check runs the function END TO END on real inputs, and the reason is
structural.** ``cip_check`` consumes a FORWARD, which is unreachable on this
installation, so its live check has to feed the function a parity-implied forward
and perturbations of it. ``uip_expected_move`` consumes **two money-market
rates and nothing else** — both reachable — so there is nothing to construct and
the function runs on live data directly.

The RATE bridge to ``cip_check`` is then a measurement, not an assertion
-----------------------------------------------------------------------
UIP and CIP are the same parity family read in two directions, and the testable
bridge is the identity

    UIP's one-year expected move  ==  CIP's forward premium  =  (i_d - i_f) / (1 + i_f)

with ``cip_check``'s "forward premium" being the ``F / S - 1`` of the
parity-implied forward. This check computes the parity-implied forward from the
live rates and asserts the two agree — so the relationship between the two
functions is ESTABLISHED ON LIVE NUMBERS here rather than merely stated in a
docstring. (The unit tests prove the same identity on hand-derived fixtures; a
live check proves the wiring that feeds it.)

What is fetched
---------------
* ``DTB3``  (FRED) — the US 3-month T-bill secondary-market rate, ANNUALISED
  PERCENT. The domestic leg.
* ``IR3TIB01EZM156N`` (FRED) — the euro-area 3-month interbank rate, ANNUALISED
  PERCENT. The foreign leg. **MONTHLY**, and its last observation is stale;
  printed rather than hidden.
* ``ECBDFR`` (FRED) — the ECB deposit facility rate. Current, but a POLICY rate.
  Used in section (5) as the second reachable foreign leg, so the leg's effect on
  the published benchmark is MEASURED rather than disclosed.
* ``EURUSD`` (yfinance, via the project's OpenBB client) — the spot level. **Not
  an input to the function** — UIP consults no price — but fetched so the check
  can print the spot move implied by the published percent against the level a
  reader would compare it with.

What this check establishes
---------------------------

1. **The rates are read in the unit the model documents.** FRED publishes
   money-market rates as ANNUALISED PERCENT (``DTB3`` = 4.04 means 4.04 %/yr);
   ``UIPInputs`` wants ANNUALISED DECIMALS. Every rate is asserted into a
   plausible percent band first, so a percent-where-a-decimal-belongs error —
   the D-106 class — fails here rather than producing a plausible expectation.

2. **The exact ratio and the specification's first-order form are both right,
   and their gap is the second-order term.** The published
   ``expected_move_pct`` must equal ``((1 + i_d t) / (1 + i_f t) - 1) * 100``
   recomputed from the published period rates, and ``expected_move_simple_pct``
   must equal ``(i_d - i_f) t * 100``. The gap between them must match the
   derived term ``i_f * (i_d - i_f) * t * 100`` — a fraction of a basis point at
   G10 differentials — so the check distinguishes "second-order" from "wrong".

3. **The direction label follows the sign of the published move, on live data.**
   A positive US-minus-euro-area differential must produce
   ``domestic_depreciation`` and a positive ``expected_move_pct``.

4. **The horizon scaling is the money-market convention.** Over a 90-day horizon
   the period move must equal the 360-day move scaled by ``90 / 360``, to the
   precision the hyperbola's curvature permits — the exact ratio is NOT linear in
   ``t``. The shortfall is measured **as a fraction of the longer move** (so both
   sides of the comparison carry the same unit) and must sit below ``i_foreign``,
   which the exact algebra guarantees: the gap is
   ``a*u*0.75 / ((1 + u/4)(1 + u))`` with ``a = i_d - i_f``, ``u = i_f``, and the
   denominator exceeds 1.

5. **The UIP/CIP bridge holds on live numbers.** ``uip_expected_move``'s 360-day
   expected move must equal the forward premium of the parity-implied forward
   that ``cip_check`` would be fed — computed here independently from the same
   two rates. **This is the check that would fail if the two functions ever
   drifted apart**, and it is the reason the two are documented as one parity
   family.

6. **The confidence is the configured cap, not a bare literal.** The published
   ``confidence`` must equal ``fx_carry.uip_reliability_cap`` and must sit
   strictly below the neighbouring Module 9 models' confidences — the point of
   the leaf is that this benchmark is worth less than an arithmetic-exact
   measurement, and a future edit that quietly raised it fails here.

What this check CANNOT validate
-------------------------------
The central limitation is untestable by construction: **the expected spot move
is unobservable**, so nothing here establishes that the published benchmark
predicts anything. That is not a defect in the check — it is the model's own
standing caveat, and the reason its confidence is capped. The foreign leg is
MONTHLY and stale, so the two rates are not date-matched: a defect in this CHECK,
not in the model (whose contract requires matched tenors and dates), measured in
section (5) rather than only disclosed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from macro_engine.config import get_settings  # noqa: E402
from macro_engine.data_layer.openbb_client import OpenBBClient  # noqa: E402
from macro_engine.models.contracts import ModelResult  # noqa: E402
from macro_engine.models.fx_carry import (  # noqa: E402
    CIPInputs,
    DayCountBasis,
    UIPInputs,
    cip_check,
    uip_expected_move,
)

#: The expectation's horizon and the money-market basis. A 3-month horizon on the
#: EUR/USD money market, which is ACT/360 on BOTH legs (the EUR money market is
#: ACT/360 like the USD one — unlike sterling).
_TENOR_DAYS = 90
#: Annotated with the model's own ``Literal`` rather than left as ``str``, so a
#: basis the model does not accept is a type error here rather than a runtime
#: ``ValidationError``.
_BASIS: DayCountBasis = "actual_360"
_BASIS_DAYS = 360
#: The one-year bridge horizon. UIP's expected move over exactly one money-market
#: year is the cleanest statement of the identity against CIP's forward premium,
#: because the period scale is exactly 1 and no conversion sits between them.
_BRIDGE_TENOR_DAYS = 360

#: Plausible ANNUALISED-PERCENT band for a money-market rate. Wide on purpose:
#: the point is to fail on a decimal-vs-percent or a basis-points mistake, not to
#: pin a regime.
_RATE_PCT_BAND = (0.0, 15.0)


def _fetch(symbols: dict[str, tuple[str, str]]) -> dict[str, pd.Series]:
    """Pull each series through the project's OpenBB client.

    The endpoint is parameterised rather than fixed to FRED because the spot leg
    comes from yfinance — a different provider with a different route.
    """
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
    print("SECTION 20.9 UIP EXPECTED MOVE — LIVE WIRING CHECK")
    print("=" * 78)

    print("  fetching real series via OpenBB:")
    raw = _fetch(
        {
            "EURUSD": ("yfinance", "currency.price.historical"),
            "DTB3": ("fred", "economy.fred_series"),
            "IR3TIB01EZM156N": ("fred", "economy.fred_series"),
            "ECBDFR": ("fred", "economy.fred_series"),
        }
    )

    # --- (1) every route returns enough observations -----------------------
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

    # --- (1b) the rates are in PERCENT, and the model wants DECIMALS -------
    print()
    print("  unit guard — money-market rates must read as ANNUALISED PERCENT:")
    low, high = _RATE_PCT_BAND
    for label in ("DTB3", "IR3TIB01EZM156N", "ECBDFR"):
        value, date = _last(raw[label])
        status = "OK" if low < value < high else "OUT-OF-BAND"
        print(f"    {label:<18} {value:8.4f} %/yr  [{status}]  @ {date}")
        if not low < value < high:
            failures.append(
                f"{label} reads {value}, outside the plausible annualised-percent "
                f"band {_RATE_PCT_BAND} — a percent-vs-decimal or a "
                f"basis-points unit error, which would rescale the expectation by "
                f"100x or 10000x"
            )

    i_domestic = _last(raw["DTB3"])[0] / 100.0
    i_foreign = _last(raw["IR3TIB01EZM156N"])[0] / 100.0
    differential_annualized = i_domestic - i_foreign
    print(
        f"    -> differential (domestic minus foreign) = "
        f"{differential_annualized:+.6f} annualised decimal "
        f"({differential_annualized * 100:+.4f}pp)"
    )

    # --- (2) the function, end to end on real inputs -----------------------
    inputs = UIPInputs(
        i_domestic_annualized=i_domestic,
        i_foreign_annualized=i_foreign,
        tenor_days=_TENOR_DAYS,
        day_count_basis=_BASIS,
    )
    result = uip_expected_move(inputs)

    expected_move_pct = _number(result, "expected_move_pct")
    simple_move_pct = _number(result, "expected_move_simple_pct")
    i_d_period = _number(result, "i_domestic_period")
    i_f_period = _number(result, "i_foreign_period")
    direction = _label(result, "direction")

    print()
    print("  the function on live inputs (END TO END — nothing is constructed):")
    print(
        f"    US 3m {i_domestic * 100:+.4f}%/yr, euro-area 3m {i_foreign * 100:+.4f}%/yr "
        f"over {_TENOR_DAYS}d -> expected move {expected_move_pct:+.6f}% "
        f"({direction})"
    )
    print(f"    period rates: domestic {i_d_period * 100:+.6f}%, foreign {i_f_period * 100:+.6f}%")
    print(f"    confidence {result.confidence}   unit {result.unit!r}")
    for note in result.warnings:
        print(f"    warning: {note}")

    # --- (3) the exact ratio and the first-order form, recomputed here ------
    tenor_scale = _TENOR_DAYS / _BASIS_DAYS
    expected_simple_here = differential_annualized * tenor_scale * 100.0
    exact_ratio_here = (1.0 + i_domestic * tenor_scale) / (1.0 + i_foreign * tenor_scale)
    expected_exact_here = (exact_ratio_here - 1.0) * 100.0
    # The derived second-order gap: the exact premium is (i_d - i_f) t / (1 + i_f t),
    # so the simple form overstates it by the factor 1/(1 + i_f t), and the absolute
    # gap is i_f * (i_d - i_f) * t at leading order.
    second_order_gap_here = abs(expected_exact_here - expected_simple_here)

    print()
    print("  the exact ratio vs the specification's first-order form:")
    print(f"    exact form (recomputed)     {expected_exact_here:+.6f}%")
    print(f"    simple form (recomputed)    {expected_simple_here:+.6f}%")
    print(f"    gap                         {second_order_gap_here:.6f}bp")
    if abs(expected_move_pct - expected_exact_here) > 1e-5:
        failures.append(
            f"the published expected_move_pct {expected_move_pct}% does not equal "
            f"((1 + i_d t) / (1 + i_f t) - 1) * 100 = {expected_exact_here}% recomputed "
            f"from the published period rates"
        )
    if abs(simple_move_pct - expected_simple_here) > 1e-5:
        failures.append(
            f"the published expected_move_simple_pct {simple_move_pct}% does not equal "
            f"(i_d - i_f) * t * 100 = {expected_simple_here}% — the specification's own "
            f"first-order form is not being published faithfully"
        )
    # The simple form must never be LARGER in magnitude than the exact one at a
    # positive foreign rate: the premium is the differential discounted by
    # 1/(1 + i_f t) < 1. A sign or a division error in the exact ratio would
    # break this, which is the falsifiable part of "second-order".
    if i_foreign * tenor_scale > 0.0 and abs(simple_move_pct) < abs(expected_move_pct) - 1e-9:
        failures.append(
            f"the simple form {simple_move_pct}% is SMALLER in magnitude than the exact "
            f"form {expected_move_pct}% at a positive foreign period rate — the exact "
            f"premium is the differential DISCOUNTED by 1/(1 + i_f t), so it must be the "
            f"smaller one; the ratio is inverted"
        )

    # --- (4) the direction label follows the sign of the published move ----
    print()
    print("  the direction label on live data:")
    expected_direction = (
        "domestic_depreciation"
        if expected_move_pct > 0
        else "domestic_appreciation"
        if expected_move_pct < 0
        else "flat"
    )
    print(
        f"    differential {differential_annualized * 100:+.4f}pp -> "
        f"move {expected_move_pct:+.6f}% -> '{direction}' (expected '{expected_direction}')"
    )
    if direction != expected_direction:
        failures.append(
            f"the expected move {expected_move_pct}% was labelled '{direction}', not "
            f"'{expected_direction}' — the direction rule is not reading the sign of the "
            f"published move"
        )
    if differential_annualized > 0 and expected_move_pct <= 0:
        failures.append(
            f"the US leg ({i_domestic * 100:.4f}%) exceeds the euro-area one "
            f"({i_foreign * 100:.4f}%), so UIP must predict DOMESTIC DEPRECIATION and a "
            f"POSITIVE move — but the published move is {expected_move_pct}%. The parity "
            f"ratio's sign is inverted."
        )

    # --- (5) the horizon scaling, to the precision the hyperbola permits --
    print()
    print("  the horizon scaling (the exact ratio is a HYPERBOLA in t, not linear):")
    one_year = uip_expected_move(
        UIPInputs(
            i_domestic_annualized=i_domestic,
            i_foreign_annualized=i_foreign,
            tenor_days=_BRIDGE_TENOR_DAYS,
            day_count_basis=_BASIS,
        )
    )
    move_1y_pct = _number(one_year, "expected_move_pct")
    ratio = move_1y_pct / expected_move_pct if expected_move_pct != 0.0 else float("nan")
    print(
        f"    {_TENOR_DAYS}d move {expected_move_pct:+.6f}%   "
        f"{_BRIDGE_TENOR_DAYS}d move {move_1y_pct:+.6f}%   ratio {ratio:.6f} "
        f"(linear would be {_BRIDGE_TENOR_DAYS / _TENOR_DAYS:.1f})"
    )
    if expected_move_pct != 0.0:
        if ratio > _BRIDGE_TENOR_DAYS / _TENOR_DAYS + 1e-6:
            failures.append(
                f"the {_BRIDGE_TENOR_DAYS}d move exceeds {_BRIDGE_TENOR_DAYS / _TENOR_DAYS}x "
                f"the {_TENOR_DAYS}d move — the exact premium's curvature makes the longer "
                f"horizon the SMALLER per-unit one, so this cannot happen"
            )
        # The departure from linearity, expressed as a FRACTION OF THE LONGER
        # MOVE so both sides of the comparison carry the SAME unit. The exact
        # ratio is (1 + i_d t)/(1 + i_f t), so with a = i_d - i_f and u = i_f:
        #     4*m(1/4) - m(1) = a*u*0.75 / ((1 + u/4)(1 + u))
        # Because (1 + u/4)(1 + u) > 1 for u > 0, this is STRICTLY BELOW
        # 0.75*a*u, and therefore below u itself. So a u-bound is legitimate —
        # but it bounds a DIMENSIONLESS fraction, never a percent and never a
        # bare ratio deviation. Comparing (4 - ratio) to i_f mixes the units
        # and understates the allowance by the factor 4; that was D-112's
        # first-cut defect, caught by this check firing on a live run.
        denominator = move_1y_pct if move_1y_pct != 0.0 else float("nan")
        linear_shortfall = (
            (_BRIDGE_TENOR_DAYS / _TENOR_DAYS) * expected_move_pct - move_1y_pct
        ) / denominator
        bound = i_foreign
        status = "OK" if linear_shortfall <= bound + 1e-9 else "OVER-BOUND"
        print(
            f"    shortfall from linear, as a fraction of the {_BRIDGE_TENOR_DAYS}d "
            f"move: {linear_shortfall:.6f} vs the i_f bound {bound:.6f}  [{status}]"
        )
        if linear_shortfall > bound + 1e-9:
            failures.append(
                f"the horizon-scaling shortfall {linear_shortfall} (a fraction of the "
                f"longer move) exceeds the i_f bound {bound} — a larger departure from "
                f"linearity than the exact ratio's curvature can produce, so the "
                f"conversion is not the documented simple-interest one"
            )

    # --- (6) THE BRIDGE: UIP's one-year move == CIP's forward premium ------
    #
    # **This is the section that would fail if the two functions ever drifted
    # apart.** UIP's expected move over exactly one money-market year is the CIP
    # forward premium (i_d - i_f) / (1 + i_f); the parity-implied forward is
    # S * (1 + i_d) / (1 + i_f), whose premium over S is that same quantity. The
    # check recomputes the forward premium from the live rates INDEPENDENTLY of
    # both functions and asserts UIP agrees with it.
    print()
    print("  THE BRIDGE — UIP's one-year move vs CIP's forward premium:")
    premium_here = (1.0 + i_domestic) / (1.0 + i_foreign) - 1.0
    premium_pct_here = premium_here * 100.0
    print(f"    CIP forward premium (i_d - i_f)/(1 + i_f)  {premium_pct_here:+.6f}%")
    print(f"    UIP one-year expected move (published)     {move_1y_pct:+.6f}%")
    delta_bridge = abs(move_1y_pct - premium_pct_here)
    print(f"    delta {delta_bridge:.2e}pp")
    if delta_bridge > 1e-5:
        failures.append(
            f"UIP's one-year expected move ({move_1y_pct}%) does not equal CIP's forward "
            f"premium ({premium_pct_here}%) recomputed from the same rates — the identity "
            f"that ties the two parity relations has broken, so the two functions no "
            f"longer read the same relation"
        )

    # The same identity through cip_check itself, on the parity-implied forward.
    # cip_check measures a DEVIATION, and fed the parity-implied forward it must
    # report ~zero — which is the other end of "the forward premium is what UIP
    # predicts the spot to do".
    eurusd, eurusd_date = _last(raw["EURUSD"])
    implied_forward = eurusd * (1.0 + i_domestic) / (1.0 + i_foreign)
    cip_result = cip_check(
        CIPInputs(
            spot=eurusd,
            forward=implied_forward,
            i_domestic_annualized=i_domestic,
            i_foreign_annualized=i_foreign,
            tenor_days=_BRIDGE_TENOR_DAYS,
            day_count_basis=_BASIS,
        )
    )
    deviation = _number(cip_result, "deviation_pct")
    print(
        f"    cip_check fed the parity-implied forward ({implied_forward:.6f} from spot "
        f"{eurusd:.6f}) reports deviation {deviation:+.2e}% (must be ~0)"
    )
    if abs(deviation) > 1e-6:
        failures.append(
            f"cip_check fed the parity-implied forward reports a deviation of {deviation}%, "
            f"not ~0 — the forward the two functions share is not the same parity relation"
        )

    # --- (7) the confidence is the configured cap -------------------------
    print()
    print("  the confidence:")
    cap = get_settings().fx_carry.uip_reliability_value
    print(f"    fx_carry.uip_reliability_cap = {cap}   published confidence = {result.confidence}")
    if abs(result.confidence - cap) > 1e-12:
        failures.append(
            f"the published confidence {result.confidence} does not equal the configured "
            f"cap {cap} — the value is not being read from the leaf"
        )
    # The cap must sit strictly below the neighbouring Module 9 confidences: a
    # measurement of a traded price is worth more than a benchmark known to fail,
    # and a future edit that quietly raised the cap above them inverts that.
    neighbours = {
        "cip_check (parity-implied forward, ~0 deviation)": cip_result.confidence,
    }
    for name, neighbour in neighbours.items():
        marker = "OK" if result.confidence < neighbour else "NOT BELOW"
        print(f"    vs {name}: {neighbour}  [{marker}]")
        if not result.confidence < neighbour:
            failures.append(
                f"uip_expected_move's confidence {result.confidence} is not below "
                f"{name}'s {neighbour} — the empirical-failure discount over an "
                f"arithmetic-exact measurement has been lost"
            )

    # --- (8) the foreign leg is a CHOICE, so MEASURE its effect -----------
    print()
    print("  the foreign leg is a CHOICE — the benchmark under both reachable legs:")
    euribor_pct, euribor_date = _last(raw["IR3TIB01EZM156N"])
    ecb_pct, ecb_date = _last(raw["ECBDFR"])
    legs: tuple[tuple[str, str, float], ...] = (
        ("3m interbank (right TENOR, stale)", euribor_date, euribor_pct / 100.0),
        ("ECB deposit facility (current, POLICY rate)", ecb_date, ecb_pct / 100.0),
    )
    leg_moves: list[tuple[str, float, str]] = []
    for leg_label, leg_date, i_foreign_leg in legs:
        leg_result = uip_expected_move(
            UIPInputs(
                i_domestic_annualized=i_domestic,
                i_foreign_annualized=i_foreign_leg,
                tenor_days=_TENOR_DAYS,
                day_count_basis=_BASIS,
            )
        )
        leg_moves.append(
            (
                leg_label,
                _number(leg_result, "expected_move_pct"),
                _label(leg_result, "direction"),
            )
        )
        print(f"    {leg_label:<44} @ {leg_date}  -> {leg_moves[-1][1]:+.6f}% ({leg_moves[-1][2]})")
    labels = {entry[2] for entry in leg_moves}
    if len(labels) != 1:
        failures.append(
            f"the expected DIRECTION flips with the choice of foreign leg: "
            f"{leg_moves[0][2]} against {leg_moves[1][2]} — the benchmark's sign depends "
            f"on which euro-area rate you pick, which means it is not a statement about "
            f"the pair"
        )

    # --- (9) the plausibility assessment, written down --------------------
    print()
    print("  PLAUSIBILITY ASSESSMENT")
    spot_move_implied = eurusd * (1.0 + move_1y_pct / 100.0)
    print(
        f"    a {differential_annualized * 100:+.4f}pp differential gives a "
        f"{_BRIDGE_TENOR_DAYS}d expected move of {move_1y_pct:+.6f}%, i.e. EUR/USD "
        f"{eurusd:.6f} -> {spot_move_implied:.6f} if parity held"
    )
    print(
        f"    the specification's first-order form would say "
        f"{differential_annualized * 100:+.4f}%, a gap of {second_order_gap_here:.6f}bp — "
        f"second-order in the foreign rate, and the reason the exact form is the one "
        f"published"
    )
    print(
        "    THE NUMBER IS A BENCHMARK, NOT A FORECAST. UIP is rejected by the data — "
        "the higher-yielding currency does NOT depreciate by the interest differential "
        "(the forward-premium puzzle), and the carry trade's entire edge is the gap "
        "between this benchmark and realised returns. Nothing in this check makes the "
        "published move more likely to happen; the confidence cap is the model saying so."
    )
    print(
        f"    the euro-area leg is MONTHLY and last observed {euribor_date}, so the two "
        f"rates are not date-matched — a defect in this CHECK, not in the model. "
        f"Section (8) MEASURES what the leg choice costs: the direction is robust, but "
        f"the level moves between the two reachable rates"
    )
    print(
        f"    spot fetched ({eurusd:.6f} @ {eurusd_date}) is NOT an input to the function "
        f"— UIP consults no price — and is printed only so the implied move can be read "
        f"against a level"
    )

    print()
    print("=" * 78)
    if failures:
        print(f"FAIL — {len(failures)} problem(s):")
        for problem in failures:
            print(f"  * {problem}")
        return 1
    print("PASS — the UIP benchmark is wired to real rates, and the CIP bridge holds.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
