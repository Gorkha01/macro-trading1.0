"""Live wiring check: real rates + a real FX volatility -> Section 6.7's ``carry_score``.

Not a test. This directory holds operator scripts, deliberately excluded from
the default test run because they hit the network. Run with::

    uv run python scripts/live_carry_score_check.py

Section 21.0: unit tests prove the arithmetic, this proves the WIRING — the
units, the sign, the floor, and whether the numbers that come out are the
numbers the specification says should come out.

**This check is stronger than D-108's, and the reason is worth stating.**
``cip_check`` consumes a FORWARD, and no route on this installation returns FX
forward points — so its live check has to feed the function a parity-implied
forward and perturbations of it. ``carry_score`` consumes a rate differential
and a volatility, **both of which are reachable**, so this check runs the
function **end to end on real inputs**.

What is fetched
---------------
* ``DTB3``  (FRED) — the US 3-month T-bill secondary-market rate, ANNUALISED
  PERCENT. The domestic leg of the differential.
* ``IR3TIB01EZM156N`` (FRED) — the euro-area 3-month interbank rate, ANNUALISED
  PERCENT. The foreign leg. **MONTHLY**, and its last observation is stale;
  printed rather than hidden.
* ``EURUSD`` (yfinance, via the project's OpenBB client) — the spot level, and
  the return series the volatility is measured from.
* ``DEXUSEU`` (FRED) — the SAME pair from an independent provider, with a much
  longer history, used as a second volatility source.

What this check establishes
---------------------------

1. **The unit conversion on the vol is the whole ballgame, and it is asserted.**
   ``realized_vol_simple`` publishes **PERCENT** (``8.2`` for 8.2 %/yr) while
   ``CarryScoreInputs.realized_vol_annualized`` wants a **DECIMAL** (``0.082``).
   The two differ by 100x and both produce a plausible score, so the check
   asserts the published percent figure lands in a plausible percent band and
   then divides by 100 — and it asserts the RESULT lands in a plausible decimal
   band. A missed conversion fails the second assertion.

2. **The model's volatility estimator and a hand computation agree.**
   ``realized_vol_simple`` (``models/risk.py``) is an independent route to the
   same quantity: sample standard deviation with ``ddof=1``, annualised by
   ``sqrt(periods_per_year)``. **A cross-check indicts whichever side is wrong,
   including the shipped one** (lesson 5b), so a disagreement here is a finding
   about the model, not about this script.

3. **Two independent spot sources give the same volatility** over the same
   recent window — yfinance's year and FRED's decades-long history. A provider
   serving the wrong pair, or an inverted quote, moves the level and usually the
   volatility with it.

4. **The sign rule holds on live data.** A positive US-minus-euro-area
   differential must produce a positive score and the ``long_domestic`` label.

5. **The floor's behaviour on live data is REPORTED, not assumed.** The shipped
   floor is 0.1 (10 %/yr) and G10 realised vol is frequently below it, so the
   check reports whether it binds and asserts the published flag matches the
   arithmetic. **When it binds the score is carry-over-the-floor**, and that is
   the honest reading of the published number.

6. **The choice of FOREIGN LEG is measured, not hidden.** No euro-area rate on
   this installation is both current and of the right tenor: the 3-month
   interbank fixing has the right TENOR but is MONTHLY and stale, and the ECB
   deposit facility rate is current but a POLICY rate. The check therefore runs
   the function under **both** and asserts the read is robust to the choice —
   same sign, same direction label. **The first version of this check used one
   leg and disclosed the mismatch in prose; a disclosure is weaker than a
   measurement**, which is why this section exists.

What this check CANNOT validate
-------------------------------
The score's central limitation is untestable here: **a symmetric realised
volatility cannot see the crash risk that makes the carry trade dangerous**, so
nothing in this script establishes that a high score is a good trade. And the
volatility window is a choice — the check reports two of them rather than
pretending one is right. **What it no longer merely discloses is the foreign
leg**, which section (4b) measures across both reachable rates.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from macro_engine.data_layer.openbb_client import OpenBBClient  # noqa: E402
from macro_engine.models.contracts import ModelResult  # noqa: E402
from macro_engine.models.fx_carry import CarryScoreInputs, carry_score  # noqa: E402
from macro_engine.models.risk import RealizedVolInputs, realized_vol_simple  # noqa: E402

_PERIODS_PER_YEAR = 252

#: The two windows the volatility is reported over. A carry-to-vol ratio should
#: use a window matched to the carry's own horizon, which for a 3-month money-
#: market differential is a quarter — 63 trading days. The 21-day figure is the
#: project's own default in ``RealizedVolInputs`` and is reported alongside so
#: the choice's effect is VISIBLE rather than hidden.
_WINDOWS: tuple[int, ...] = (21, 63)

#: Plausible ANNUALISED-PERCENT band for a money-market rate, and for a G10 FX
#: pair's annualised volatility. Wide on purpose: the point is to fail on a
#: percent-vs-decimal or a level-vs-return mistake, not to pin a regime.
_RATE_PCT_BAND = (0.0, 15.0)
_VOL_PCT_BAND = (1.0, 30.0)

#: How far the model's estimator and this script's hand computation may differ,
#: in annualised PERCENT.
#:
#: **DERIVED, not chosen — and the first draft got it wrong in a way worth
#: recording.** The initial value was ``1e-6``, on the reasoning that two
#: computations of the same arithmetic should agree to floating-point noise.
#: They do — but the MODEL does not publish its full-precision result:
#: ``realized_vol_simple`` returns ``round(vol_annualized * 100, 4)``, so its
#: published figure carries up to **half a unit in the 4th decimal = 5e-5** of
#: rounding error by construction. Measured on the first live run: the model
#: published ``3.3271`` against a hand value of ``3.3271339592040214`` — a
#: disagreement of ``3.4e-5``, which is *exactly* that rounding and nothing
#: else. The check failed on its own tolerance rather than on a defect, which is
#: the failure mode a cross-check must not have: **a bound tighter than the
#: coarser side's published precision tests the ROUNDING, not the agreement.**
#: The bound is therefore the model's own published precision, and a real
#: disagreement (a different ``ddof``, or a different annualisation base) is
#: 100x-or-nothing rather than 1e-5.
_VOL_PUBLISHED_PRECISION_PCT = 5e-5


def _fetch(symbols: dict[str, tuple[str, str]]) -> dict[str, pd.Series]:
    """Pull each series through the project's OpenBB client."""
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


def _returns(series: pd.Series) -> list[float]:
    """Simple period returns as DECIMALS, oldest first — ``RealizedVolInputs``'s contract."""
    return [float(value) for value in series.pct_change().dropna().tolist()]


def _hand_vol_pct(returns: list[float], window: int) -> float:
    """Sample stdev (``ddof=1``) of the last ``window`` returns, annualised, in PERCENT.

    Written out here rather than called from the model ON PURPOSE: the point of
    a cross-check is that the two sides are independent. ``ddof=1`` matches
    ``realized_vol_simple``'s documented choice, and the annualisation base is
    the same 252, so the two SHOULD agree to floating-point noise — and if they
    do not, one of the two is wrong.
    """
    sample = returns[-window:]
    mean = sum(sample) / len(sample)
    variance = sum((value - mean) ** 2 for value in sample) / (len(sample) - 1)
    return math.sqrt(variance) * math.sqrt(_PERIODS_PER_YEAR) * 100.0


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
    print("SECTION 6.7 CARRY SCORE — LIVE WIRING CHECK")
    print("=" * 78)

    print("  fetching real series via OpenBB:")
    raw = _fetch(
        {
            "EURUSD": ("yfinance", "currency.price.historical"),
            "DEXUSEU": ("fred", "economy.fred_series"),
            "DTB3": ("fred", "economy.fred_series"),
            "IR3TIB01EZM156N": ("fred", "economy.fred_series"),
            "ECBDFR": ("fred", "economy.fred_series"),
        }
    )

    print()
    print("  series (last value @ date):")
    for label, series in raw.items():
        value, date = _last(series)
        print(f"    {label:<18} n={len(series):<6} {value:>12.6f}  @ {date}")
        if len(series) < 60:
            failures.append(
                f"{label} returned only {len(series)} observations — too few to trust; "
                f"a route that is empty or discontinued is BLOCKED"
            )

    # --- (1) the rates are in PERCENT, and the model wants DECIMALS -------
    print()
    print("  unit guard — money-market rates must read as ANNUALISED PERCENT:")
    low, high = _RATE_PCT_BAND
    for label in ("DTB3", "IR3TIB01EZM156N", "ECBDFR"):
        value, date = _last(raw[label])
        status = "OK" if low < value < high else "OUT-OF-BAND"
        print(f"    {label:<18} {value:8.4f} %/yr  [{status}]  @ {date}")
        if not low < value < high:
            failures.append(
                f"{label} reads {value}, outside the plausible annualised-percent band "
                f"{_RATE_PCT_BAND} — a percent-vs-decimal unit error"
            )

    i_domestic = _last(raw["DTB3"])[0] / 100.0
    i_foreign = _last(raw["IR3TIB01EZM156N"])[0] / 100.0
    differential = i_domestic - i_foreign
    print(
        f"    -> differential (domestic minus foreign) = "
        f"{differential:+.6f} annualised decimal "
        f"({differential * 100:+.4f}pp)"
    )

    # --- (2) the volatility: the model's route vs a hand computation ------
    print()
    print("  volatility — the model's estimator vs a hand computation:")
    usd_returns = _returns(raw["DEXUSEU"])
    if len(usd_returns) < max(_WINDOWS):
        failures.append(
            f"only {len(usd_returns)} returns from DEXUSEU; need {max(_WINDOWS)} for the "
            f"longest window"
        )
    vol_decimal = 0.0
    for window in _WINDOWS:
        hand_pct = _hand_vol_pct(usd_returns, window)
        model = realized_vol_simple(
            RealizedVolInputs(
                returns=usd_returns,
                window=window,
                periods_per_year=_PERIODS_PER_YEAR,
            )
        )
        # `realized_vol_simple` publishes a BARE FLOAT in percent, not a dict —
        # unlike most models in this tree, and unlike `carry_score` beside it.
        # Read it as a number and say so, rather than routing it through the
        # dict accessor and dying on the type: the first draft of this check did
        # exactly that and failed on its own wiring rather than on the model's.
        raw_vol = model.value
        assert isinstance(raw_vol, (int, float)) and not isinstance(raw_vol, bool), (
            f"realized_vol_simple published {type(raw_vol).__name__}, not a number"
        )
        model_pct = float(raw_vol)
        delta = abs(model_pct - hand_pct)
        vlow, vhigh = _VOL_PCT_BAND
        status = "OK" if vlow < model_pct < vhigh else "OUT-OF-BAND"
        print(
            f"    window {window:>3}d: model {model_pct:7.4f}%  hand {hand_pct:7.4f}%  "
            f"delta {delta:.2e}pp  [{status}]"
        )
        if delta > _VOL_PUBLISHED_PRECISION_PCT:
            failures.append(
                f"at window {window} the model's realized_vol_simple published "
                f"{model_pct}% against this script's hand computation of {hand_pct}% — "
                f"a disagreement of {delta}pp, above the {_VOL_PUBLISHED_PRECISION_PCT}pp "
                f"that the model's own 4dp rounding can explain. The two are the same "
                f"arithmetic on the same numbers, so beyond that rounding one of them is "
                f"wrong: a different ddof, or a different annualisation base."
            )
        if not vlow < model_pct < vhigh:
            failures.append(
                f"the annualised volatility at window {window} reads {model_pct}%, "
                f"outside the plausible percent band {_VOL_PCT_BAND} — a "
                f"level-vs-return or a percent-vs-decimal error"
            )
        if window == max(_WINDOWS):
            vol_decimal = model_pct / 100.0

    print(
        f"    -> realized_vol_simple publishes PERCENT and the model wants a DECIMAL, "
        f"so the value fed to carry_score is {vol_decimal:.6f} "
        f"(= {vol_decimal * 100:.4f}% / 100)"
    )

    # --- (3) the second spot source, same window --------------------------
    yf_returns = _returns(raw["EURUSD"])
    shared = min(len(yf_returns), len(usd_returns))
    window = min(_WINDOWS)
    if shared < window:
        failures.append(f"only {shared} overlapping returns between the two spot sources")
    else:
        yf_pct = _hand_vol_pct(yf_returns, window)
        fr_pct = _hand_vol_pct(usd_returns, window)
        gap = abs(yf_pct - fr_pct)
        print()
        print(f"  two spot sources, same {window}-day window:")
        print(
            f"    EURUSD (yfinance) {yf_pct:7.4f}%   "
            f"DEXUSEU (FRED) {fr_pct:7.4f}%   gap {gap:.4f}pp"
        )
        # The two series are not the same dates (yfinance is the live year, FRED
        # lags by a week), so the gap is bounded by the window difference rather
        # than by an identity. A wrong pair or an inverted quote moves it by far
        # more than a few percentage points of volatility.
        if gap > 5.0:
            failures.append(
                f"the two spot sources disagree on volatility by {gap:.4f}pp "
                f"({yf_pct}% vs {fr_pct}%) — too wide for the same pair and window, "
                f"so one provider is serving a different series"
            )

    # --- (4) the function, end to end on real inputs ----------------------
    inputs = CarryScoreInputs(
        rate_differential_annualized=differential,
        realized_vol_annualized=vol_decimal,
    )
    result = carry_score(inputs)
    score = _number(result, "score")
    denominator = _number(result, "effective_denominator")
    binds = _values(result)["volatility_floor_binding"]
    floor = _number(result, "volatility_floor")
    outcome = _label(result, "carry_outcome")

    print()
    print("  the function on live inputs (END TO END — nothing is constructed):")
    print(
        f"    differential {differential:+.6f}  vol {vol_decimal:.6f}  floor {floor}  "
        f"-> score {score:+.6f}  denominator {denominator:.6f}"
    )
    print(f"    floor binds: {binds}   outcome: {outcome}   confidence {result.confidence}")
    for note in result.warnings:
        print(f"    warning: {note}")

    # --- (4b) the foreign leg is a CHOICE, so MEASURE its effect ----------
    #
    # **This section exists because the first version of this check had a defect
    # it could only disclose.** The euro-area leg is a 3-MONTH INTERBANK rate —
    # the right TENOR for a 3-month carry — but it is MONTHLY and its last
    # observation is months old. The only CURRENT euro-area rate reachable is the
    # ECB deposit facility rate, which is a POLICY rate: current, but the wrong
    # tenor. **Neither is right, and picking one while printing "live" would be
    # the misleading choice.** So the check runs the function under BOTH and
    # asserts the READ is robust to the choice — same sign, same direction label.
    # A carry view that flips when you swap the foreign leg is not a view.
    print()
    print("  the foreign leg is a CHOICE — the same score under both reachable legs:")
    euribor_pct, euribor_date = _last(raw["IR3TIB01EZM156N"])
    ecb_pct, ecb_date = _last(raw["ECBDFR"])
    legs: tuple[tuple[str, str, float], ...] = (
        ("3m interbank (right TENOR, stale)", euribor_date, euribor_pct / 100.0),
        ("ECB deposit facility (current, POLICY rate)", ecb_date, ecb_pct / 100.0),
    )
    leg_scores: list[tuple[str, float, str]] = []
    for leg_label, leg_date, i_foreign_leg in legs:
        leg_result = carry_score(
            CarryScoreInputs(
                rate_differential_annualized=i_domestic - i_foreign_leg,
                realized_vol_annualized=vol_decimal,
            )
        )
        leg_scores.append(
            (leg_label, _number(leg_result, "score"), _label(leg_result, "carry_outcome"))
        )
        print(
            f"    {leg_label:<44} @ {leg_date}  -> {leg_scores[-1][1]:+.6f} ({leg_scores[-1][2]})"
        )
    labels = {entry[2] for entry in leg_scores}
    spread = abs(leg_scores[0][1] - leg_scores[1][1])
    print(f"    the two legs agree on the direction ({labels}) and differ by {spread:.4f}")
    if len(labels) != 1:
        failures.append(
            f"the carry DIRECTION flips with the choice of foreign leg: "
            f"{leg_scores[0][2]} against {leg_scores[1][2]} — a carry view that "
            f"depends on which euro-area rate you pick is not a view"
        )
    if any(entry[1] > 0 for entry in leg_scores) != all(entry[1] > 0 for entry in leg_scores):
        failures.append("the score's SIGN flips with the choice of foreign leg")

    # --- (5) the identities, on live numbers ------------------------------
    if abs(score - differential / denominator) > 1e-6:
        failures.append(
            f"the published score {score} is not differential/denominator "
            f"({differential}/{denominator} = {differential / denominator})"
        )
    if (score > 0) != (differential > 0):
        failures.append(
            f"the score {score} and the differential {differential} disagree in sign — "
            f"the denominator is positive by construction, so this cannot happen"
        )
    expected_outcome = (
        "long_domestic" if differential > 0 else "long_foreign" if differential < 0 else "flat"
    )
    if outcome != expected_outcome:
        failures.append(
            f"the differential {differential:+.6f} was labelled '{outcome}', "
            f"not '{expected_outcome}' — the direction rule is inverted"
        )
    expected_binding = vol_decimal < floor
    if binds is not expected_binding:
        failures.append(
            f"the floor-binding flag says {binds} but the realised vol {vol_decimal:.6f} "
            f"against the floor {floor} implies {expected_binding}"
        )
    if expected_binding:
        un_floored = differential / vol_decimal
        if abs(score) >= abs(un_floored):
            failures.append(
                f"the floor BINDS yet the score {score} is not smaller in magnitude than "
                f"the un-floored ratio {un_floored} — the floor is inflating rather than "
                f"capping, which inverts its effect"
            )

    # --- (6) the plausibility assessment, written down --------------------
    print()
    print("  PLAUSIBILITY ASSESSMENT")
    print(
        f"    a differential of {differential * 100:+.4f}pp over a volatility of "
        f"{vol_decimal * 100:.4f}% gives a carry-to-vol score of {score:+.4f}"
    )
    if binds:
        print(
            f"    ⚠️ THE FLOOR BINDS: the realised volatility {vol_decimal:.6f} is below "
            f"the shipped floor {floor}, so the denominator is the FLOOR and the score "
            f"is CAPPED. Un-floored it would be {differential / vol_decimal:+.4f}. This "
            f"is the shipped configuration's behaviour on a quiet G10 pair, and it is "
            f"the reason the flag travels with the value."
        )
    else:
        print(
            "    the floor does NOT bind, so the score is a genuine carry-to-vol ratio "
            "and is comparable with one produced the same way"
        )
    print(
        f"    SIGN AND SIZE: the differential is {'positive' if differential > 0 else 'negative'}, "
        f"so the trade is to {outcome.replace('long_', 'lend ')}; the magnitude is the "
        f"carry per unit of annualised volatility, which is the right ORDER for a "
        f"Sharpe-like ratio."
    )
    print(
        "    WHAT THIS DOES NOT SAY: a symmetric realised volatility cannot see the "
        "crash risk that makes a carry trade dangerous, so a positive score is not "
        "evidence that the trade is good. The score is a Sharpe-LIKE ratio, not a "
        "Sharpe ratio, and the specification's own tail-risk caveat is carried in "
        "the result's limitations rather than in its warnings."
    )
    print(
        f"    the euro-area leg is MONTHLY and last observed {euribor_date}, so the two "
        f"rates are not date-matched — a defect in this CHECK, not in the model. Section "
        f"(4b) MEASURES what it costs: the read is robust to the leg choice, but the score "
        f"moves by {spread:.4f} between the two reachable rates, so the LEVEL should be "
        f"read as indicative and the DIRECTION as the finding"
    )
    print(
        f"    the volatility window is a CHOICE: {_WINDOWS[0]}d and {_WINDOWS[-1]}d are both "
        f"reported above, and the score above uses the {max(_WINDOWS)}d figure because a "
        f"3-month money-market differential's natural horizon is a quarter"
    )

    print()
    print("=" * 78)
    if failures:
        print(f"FAIL — {len(failures)} problem(s):")
        for problem in failures:
            print(f"  * {problem}")
        return 1
    print("PASS — the carry-to-vol score is wired to real data end to end.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
