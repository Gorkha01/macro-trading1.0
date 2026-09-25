"""Live wiring check: real FX spot + real money-market rates -> Section 6.7's ``cip_check``.

Not a test. This directory holds operator scripts, deliberately excluded from
the default test run because they hit the network. Run with::

    uv run python scripts/live_cip_check.py

Section 21.0: unit tests prove the arithmetic, this proves the WIRING — the
units, the quote convention, the sign, and whether the numbers that come out are
the numbers the specification says should come out.

What is fetched, and what is NOT
--------------------------------
* ``EURUSD``  (yfinance, via the project's OpenBB client) — spot, USD per EUR.
* ``DEXUSEU`` (FRED) — the SAME spot from an independent provider, as a
  cross-source check on the quote convention and the level.
* ``DTB3``    (FRED) — the US 3-month T-bill secondary-market rate, ANNUALISED
  PERCENT. The domestic leg.
* ``DGS3MO``  (FRED) — the 3-month constant-maturity Treasury, a second US 3m
  series, so the domestic leg has a cross-source too.
* ``IR3TIB01EZM156N`` (FRED) — the euro-area 3-month interbank rate, ANNUALISED
  PERCENT. The foreign leg. **MONTHLY**, and its last observation is months old;
  both facts are printed rather than hidden.
* ``ECBDFR`` and ``ECBESTRVOLWGTTRMDMNRT`` — the ECB deposit facility rate and
  the euro short-term rate, printed as corroboration that the euro short end sits
  far below the US one.

**There is NO FORWARD, and this is a measured block, not an omission.**
``cip_check`` takes the forward as an input, so the model ships; but no route on
this installation returns FX forward points. Measured 2026-09-25: the OpenBB
route inventory has **443** routes and **none** matching ``forward`` / ``swap`` /
``basis`` under ``currency`` or ``fixedincome``; ``obb.currency`` exposes only
``price``, ``search`` and ``snapshots``; and the CME FX futures tickers
(``6E=F``, ``6J=F``, ``6B=F``) return ``EmptyDataError`` through the yfinance
provider. The block is recorded in ``config/series_registry.yaml``.

**So this check CANNOT measure the real-world CIP deviation.** It measures the
*wiring and the sign rule* on real inputs, by feeding the function the
parity-implied forward and perturbations of it — the "live means an ORACLE"
pattern (lesson 5aa). The claim it does NOT support is "the current EUR/USD CIP
basis is X"; no forward series is reachable to support that.

What this check establishes
---------------------------

1. **The rates are read in the unit the model documents.** FRED publishes
   money-market rates as ANNUALISED PERCENT (``DTB3`` = 4.04 means 4.04%/yr);
   ``CIPInputs`` wants ANNUALISED DECIMALS. Every rate is asserted into a
   plausible percent band first, so a percent-where-a-decimal-belongs error —
   the D-106 class — fails here rather than producing a plausible deviation.

2. **The quote convention survives a real pair.** ``EURUSD`` is quoted USD per
   EUR (domestic per foreign for a USD-domestic caller); ``USDEUR`` is the same
   swap quoted the other way. The function is fed BOTH and must return the same
   deviation — a branch that ignored the convention would return a different,
   wrong-signed number for the second.

3. **The parity identity's SIGN is economically right on real data.** With US
   3-month rates above euro-area 3-month rates, the higher-yielding currency
   (USD) must sit at a FORWARD DISCOUNT — i.e. the EUR/USD forward must be ABOVE
   spot. That is a falsifiable prediction about live data, and a sign-inverted
   implementation fails it.

4. **The arithmetic reconciles against a closed form on real inputs.** The
   published ``implied_forward`` must equal ``S(1+i_d t)/(1+i_f t)`` recomputed
   from the published spot and the period rates; and perturbing the forward must
   move ``deviation_pct`` and ``domestic_funding_basis_bp_annualized`` to the
   analytically predicted values, including the exact identity
   ``basis_period == (1 + i_d_period) * deviation_fraction``.

5. **The funding-stress label follows the sign.** Above parity the label must be
   ``domestic`` and the basis positive; below parity ``foreign`` and negative.

What this check CANNOT validate
-------------------------------
The euro-area leg is a MONTHLY series whose last observation is stale, so the
two rates are NOT matched to the same date — a real defect in this CHECK (not in
the model, whose contract requires matched tenors and dates). The magnitude of a
real CIP basis, the bid/ask, the settlement-date convention and the balance-sheet
cost are all outside what a forward-less installation can measure, and the
model's ``limitations`` say so on every call.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from macro_engine.data_layer.openbb_client import OpenBBClient  # noqa: E402
from macro_engine.models.contracts import ModelResult  # noqa: E402
from macro_engine.models.fx_carry import CIPInputs, DayCountBasis, cip_check  # noqa: E402

#: The forward's tenor and the money-market basis. A 3-month forward on the
#: EUR/USD money market, which is ACT/360 on BOTH legs (the EUR money market is
#: ACT/360 like the USD one — unlike sterling).
_TENOR_DAYS = 90
#: Annotated with the model's own ``Literal`` rather than left as ``str``, so a
#: basis the model does not accept is a type error here rather than a runtime
#: ``ValidationError`` — and so ``mypy --strict`` checks this constant against
#: the contract it is fed into.
_BASIS: DayCountBasis = "actual_360"
_BASIS_DAYS = 360.0

#: Plausible ANNUALISED-PERCENT band for a money-market rate. Wide on purpose:
#: the point is to fail on a decimal-vs-percent or a basis-points mistake, not to
#: pin a regime.
_RATE_PCT_BAND = (0.0, 15.0)

#: Two spot sources are the same pair on slightly different dates, so they agree
#: only to within the week's move. 3% is far above that and far below a
#: quote-convention inversion (which would be a factor of ~1.3, i.e. 30%).
_SPOT_AGREEMENT_PCT = 3.0


def _fetch(symbols: dict[str, tuple[str, str]]) -> dict[str, pd.Series]:
    """Pull each series through the project's OpenBB client.

    ``symbols`` maps a label to ``(provider, endpoint)``. The endpoint is
    parameterised rather than fixed to FRED because the spot leg comes from
    yfinance — a different provider with a different route — and hardcoding
    ``economy.fred_series`` would have made the FX spot unreachable.
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
    print("SECTION 6.7 CIP CHECK — LIVE WIRING CHECK")
    print("=" * 78)

    print("  fetching real series via OpenBB:")
    raw = _fetch(
        {
            "EURUSD": ("yfinance", "currency.price.historical"),
            "USDEUR": ("yfinance", "currency.price.historical"),
            "DEXUSEU": ("fred", "economy.fred_series"),
            "DTB3": ("fred", "economy.fred_series"),
            "DGS3MO": ("fred", "economy.fred_series"),
            "IR3TIB01EZM156N": ("fred", "economy.fred_series"),
            "ECBDFR": ("fred", "economy.fred_series"),
            "ECBESTRVOLWGTTRMDMNRT": ("fred", "economy.fred_series"),
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
    rate_pct: dict[str, float] = {}
    for label in ("DTB3", "DGS3MO", "IR3TIB01EZM156N"):
        value, date = _last(raw[label])
        rate_pct[label] = value
        low, high = _RATE_PCT_BAND
        status = "OK" if low < value < high else "OUT-OF-BAND"
        print(f"    {label:<18} {value:8.4f} %/yr  [{status}]  @ {date}")
        if not low < value < high:
            failures.append(
                f"{label} reads {value}, outside the plausible annualised-percent "
                f"band {_RATE_PCT_BAND} — a percent-vs-decimal or a "
                f"basis-points unit error, which would rescale the implied "
                f"forward by 100x or 10000x"
            )
    print(
        f"    corroboration: ECBDFR {_last(raw['ECBDFR'])[0]:.4f} %/yr, "
        f"euro short-term rate {_last(raw['ECBESTRVOLWGTTRMDMNRT'])[0]:.4f} %/yr "
        f"(both far below the US 3m leg)"
    )

    # --- (2) the two spot sources agree ------------------------------------
    eurusd, eurusd_date = _last(raw["EURUSD"])
    usdeur, _ = _last(raw["USDEUR"])
    dexuseu, dexuseu_date = _last(raw["DEXUSEU"])
    print()
    print("  spot cross-source:")
    print(f"    EURUSD (yfinance)      {eurusd:.6f}  @ {eurusd_date}")
    print(f"    DEXUSEU (FRED)         {dexuseu:.6f}  @ {dexuseu_date}")
    print(f"    USDEUR (yfinance)      {usdeur:.6f}  (= 1/EURUSD = {1.0 / eurusd:.6f})")
    if abs(usdeur * eurusd - 1.0) > 1e-6:
        failures.append(
            f"USDEUR ({usdeur}) is not the reciprocal of EURUSD ({eurusd}) — the "
            f"two are the same swap quoted opposite ways, so a caller passing one "
            f"for the other would be silently wrong"
        )
    spread_pct = abs(eurusd - dexuseu) / eurusd * 100.0
    status = "OK" if spread_pct <= _SPOT_AGREEMENT_PCT else "DISAGREE"
    print(f"    EURUSD vs DEXUSEU differ by {spread_pct:.3f}%  [{status}]")
    if spread_pct > _SPOT_AGREEMENT_PCT:
        failures.append(
            f"the two spot sources differ by {spread_pct:.3f}% ({eurusd} vs "
            f"{dexuseu}) — more than a week of EUR/USD movement, so one of them "
            f"is the wrong pair or the wrong quote convention"
        )

    # --- (3) the parity identity's SIGN on real data -----------------------
    i_domestic_annualized = rate_pct["DTB3"] / 100.0
    i_foreign_annualized = rate_pct["IR3TIB01EZM156N"] / 100.0
    tenor_scale = _TENOR_DAYS / _BASIS_DAYS
    i_domestic_period = i_domestic_annualized * tenor_scale
    i_foreign_period = i_foreign_annualized * tenor_scale
    implied_forward = eurusd * (1.0 + i_domestic_period) / (1.0 + i_foreign_period)

    print()
    print("  the parity identity on live rates:")
    print(
        f"    US 3m {i_domestic_annualized * 100:.4f}%/yr vs euro-area 3m "
        f"{i_foreign_annualized * 100:.4f}%/yr -> the US leg is "
        f"{(i_domestic_annualized - i_foreign_annualized) * 100:+.4f}pp higher"
    )
    print(
        f"    period rates over {_TENOR_DAYS}d/{_BASIS_DAYS}: domestic "
        f"{i_domestic_period * 100:+.6f}%, foreign {i_foreign_period * 100:+.6f}%"
    )
    print(f"    spot {eurusd:.6f} -> implied forward {implied_forward:.6f}")

    # THE FALSIFIABLE PREDICTION. A higher domestic rate means the domestic
    # currency is at a forward discount, i.e. the forward quoted as domestic per
    # foreign sits ABOVE spot. A sign-inverted implementation fails here.
    if i_domestic_annualized > i_foreign_annualized:
        if not implied_forward > eurusd:
            failures.append(
                f"the US 3m rate ({i_domestic_annualized * 100:.4f}%) exceeds the "
                f"euro-area one ({i_foreign_annualized * 100:.4f}%), so the "
                f"higher-yielding currency (USD) must be at a FORWARD DISCOUNT and "
                f"the EUR/USD forward must sit ABOVE spot — but the implied forward "
                f"{implied_forward} is below spot {eurusd}. The parity ratio's sign "
                f"is inverted."
            )
        else:
            print(
                f"    direction OK: USD yields more, so USD is at a forward "
                f"discount and EUR/USD is at a premium "
                f"({(implied_forward / eurusd - 1.0) * 100:+.4f}%)"
            )
    else:
        print("    (the US leg is NOT the higher-yielding one today — direction check skipped)")

    # --- (4) the function on the real spot and the implied forward ---------
    direct = cip_check(
        CIPInputs(
            spot=eurusd,
            forward=implied_forward,
            i_domestic_annualized=i_domestic_annualized,
            i_foreign_annualized=i_foreign_annualized,
            tenor_days=_TENOR_DAYS,
            day_count_basis=_BASIS,
        )
    )
    print()
    print("  the function, fed the parity-implied forward (deviation must be ~0):")
    print(
        f"    deviation {_number(direct, 'deviation_pct'):+.6f}%   "
        f"basis {_number(direct, 'domestic_funding_basis_bp_annualized'):+.4f}bp   "
        f"severity {_label(direct, 'severity')}   "
        f"stressed {_label(direct, 'stressed_currency')}"
    )
    if abs(_number(direct, "deviation_pct")) > 1e-6:
        failures.append(
            f"feeding the parity-implied forward gave a deviation of "
            f"{_number(direct, 'deviation_pct')}%, not ~0 — the function's implied "
            f"forward does not agree with the one computed here from the same inputs"
        )

    # --- (5) the quote convention, on the REAL reciprocal pair -------------
    reverse = cip_check(
        CIPInputs(
            spot=usdeur,
            forward=1.0 / implied_forward,
            i_domestic_annualized=i_domestic_annualized,
            i_foreign_annualized=i_foreign_annualized,
            tenor_days=_TENOR_DAYS,
            day_count_basis=_BASIS,
            quote="foreign_per_domestic",
        )
    )
    delta = abs(_number(reverse, "deviation_pct") - _number(direct, "deviation_pct"))
    print()
    print("  the quote convention on the real reciprocal pair:")
    print(f"    EURUSD as domestic-per-foreign : {_number(direct, 'deviation_pct'):+.6f}%")
    print(f"    USDEUR as foreign-per-domestic : {_number(reverse, 'deviation_pct'):+.6f}%")
    print(f"    delta {delta:.2e}pp  (inverted={_values(reverse)['quote_was_inverted']})")
    if delta > 1e-6:
        failures.append(
            f"the same swap quoted the two ways gave deviations differing by "
            f"{delta}pp — the foreign_per_domestic branch is not inverting, so the "
            f"quote convention is being ignored"
        )

    # --- (6) the ORACLE: perturb the forward and check the closed form -----
    print()
    print("  oracle perturbation (the forward has no live source, so it is shocked):")
    for shock_pct in (-0.25, +0.25, +1.0):
        shocked_forward = implied_forward * (1.0 + shock_pct / 100.0)
        result = cip_check(
            CIPInputs(
                spot=eurusd,
                forward=shocked_forward,
                i_domestic_annualized=i_domestic_annualized,
                i_foreign_annualized=i_foreign_annualized,
                tenor_days=_TENOR_DAYS,
                day_count_basis=_BASIS,
            )
        )
        expected_deviation = (shocked_forward - implied_forward) / implied_forward * 100.0
        got_deviation = _number(result, "deviation_pct")
        expected_basis_period = (1.0 + i_domestic_period) * expected_deviation / 100.0
        expected_basis_bp = expected_basis_period / tenor_scale * 10_000.0
        got_basis_bp = _number(result, "domestic_funding_basis_bp_annualized")
        side = _label(result, "stressed_currency")
        expected_side = "domestic" if shock_pct > 0 else "foreign"
        print(
            f"    shock {shock_pct:+.2f}%: deviation {got_deviation:+.6f}% "
            f"(expected {expected_deviation:+.6f}%), basis {got_basis_bp:+.4f}bp "
            f"(expected {expected_basis_bp:+.4f}bp), stressed {side}"
        )
        if abs(got_deviation - expected_deviation) > 1e-5:
            failures.append(
                f"a {shock_pct:+.2f}% forward shock produced a deviation of "
                f"{got_deviation}% against a closed form of {expected_deviation}%"
            )
        if abs(got_basis_bp - expected_basis_bp) > 1e-3:
            failures.append(
                f"a {shock_pct:+.2f}% forward shock produced a basis of "
                f"{got_basis_bp}bp against the identity's {expected_basis_bp}bp"
            )
        if side != expected_side:
            failures.append(
                f"a {shock_pct:+.2f}% forward shock (forward "
                f"{'above' if shock_pct > 0 else 'below'} parity) was labelled "
                f"'{side}', not '{expected_side}' — the funding-stress sign rule "
                f"is inverted"
            )

    # --- (7) the plausibility assessment, written down ---------------------
    print()
    print("  PLAUSIBILITY ASSESSMENT")
    premium_pct = (implied_forward / eurusd - 1.0) * 100.0
    differential_pct = (i_domestic_period - i_foreign_period) * 100.0
    print(
        f"    implied forward premium {premium_pct:+.4f}% against the period "
        f"interest differential {differential_pct:+.4f}%"
    )
    print(
        f"    the two agree to {abs(premium_pct - differential_pct):.4f}pp, and the "
        f"premium is the SMALLER by construction: the exact parity premium is "
        f"(i_d - i_f)t / (1 + i_f t), so the differential overstates it by the "
        f"factor 1/(1 + i_f t) = {1.0 / (1.0 + i_foreign_period):.6f}"
    )
    print(
        "    SIGN AND SIZE: the forward premium is positive and of the order of "
        "the interest differential, which is the direction covered parity "
        "requires. This is a statement about the IDENTITY, not about the market: "
        "no forward series is reachable, so the market's own CIP deviation is "
        "NOT measured here."
    )
    print(
        f"    the euro-area leg is MONTHLY and last observed "
        f"{_last(raw['IR3TIB01EZM156N'])[1]}, so the two rates are not "
        f"date-matched — a defect in this CHECK, not in the model"
    )

    print()
    print("=" * 78)
    if failures:
        print(f"FAIL — {len(failures)} problem(s):")
        for problem in failures:
            print(f"  * {problem}")
        return 1
    print("PASS — the parity check is wired to real data end to end.")
    print(
        "  NOTE: no FX forward source exists on this installation, so the "
        "market's own CIP deviation is NOT measured — see the block in "
        "config/series_registry.yaml."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
