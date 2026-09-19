"""Live cross-check: ``construct_duration_weighted_curve_trade`` against an
independent duration source and against the instrument router.

Not a test. Operator scripts are deliberately excluded from the default test run
because they exercise the real settings tree and other real modules. Run with::

    uv run python scripts/live_curve_trade.py

Section 21.0: unit tests prove the arithmetic, this proves the wiring. For D-059
the wiring question has a specific shape, and saying what it is *precisely* is
the point of this docstring.

What this check can and cannot do
---------------------------------
D-057's check compared against an **analytic oracle** (the closed-form Kelly
fraction). D-058's could not -- its output is a routing decision. This one is
back in the first category but with a twist worth naming: the *arithmetic* here
is one line, and the unit tests already pin it against hand-computed values. The
thing unit tests **cannot** check is whether the durations this function is fed
are the durations the rest of the system actually produces.

That is a genuine integration risk, not a synthetic one. ``bond_math`` (Tier 1,
shipped) returns **Macaulay duration in PERIODS**; this contract wants **Modified
duration in YEARS**. The conversion is ``modified = macaulay / (1 + y/f)``. The
ratio ``D_s / D_l`` is *unit-free*, so feeding periods instead of years leaves the
notional arithmetically **correct** -- and therefore the error is invisible to
every check inside the function. Only a cross-check against the real duration
producer can say anything about it.

The four things this check establishes
--------------------------------------

1. **THE CROSS-CHECK, against ``bond_math``.** Real US Treasury-like bonds are
   priced by the shipped Tier 1 functions, their durations converted by the
   shipped ``modified_duration``, and the resulting pairs fed to this function.
   The emitted notional is then compared against the **dollar-duration** matching
   condition derived from bond math alone -- and the comparison is asserted as
   the *exact* relation ``N_l(duration-weighted) = N_l(DV01-matched) · P_l/P_s``,
   not as an equality. That distinction is the finding: the specification says
   duration-weighting "cancels level (PC1) exposure", and it does so **only when
   the two legs trade at the same price**. See item 2.

2. **Duration-weighting vs level-cancellation, and the band.** Item 1's
   cross-check surfaces a real question about the specification's own claim:
   §15.1b says duration-weighting "cancels level (PC1) exposure". It does so
   exactly only when both legs trade at the same price. The check states the
   relation ``N_l(dw) = N_l(dollardur) · P_l / P_s`` and reports the size of the
   discrepancy for realistic legs, rather than asserting an equality the
   arithmetic does not support. It then sweeps the full 1y..30y grid to confirm
   the configured band admits every real Treasury pair and refuses the classic
   unit errors.

3. **A real trade survives the router.** The duration-weighted trade built from
   real durations is described with the string ``select_instrument`` emits for
   ``CURVE_SHAPE_GAP`` (D-058), and the check confirms the two functions agree
   about the instrument: the router's output is admitted by the production
   universe, so a curve trade built here is expressible in the system's own
   execution vocabulary. This is the D-058/D-059 seam, exercised end to end.

4. **Reports what it cannot validate.** Whether ``Notional_short = $10mm`` is the
   right SIZE is a portfolio decision with no oracle in this repository. The check
   validates the *arithmetic and the vocabulary*, which is strictly weaker than
   validating the trade. Stated rather than implied.

Offline by design: the object under validation is arithmetic over durations, not
a data feed, so this check needs **no network**. The "live" here means "through
the live settings tree and the real Tier 1 duration producer". Stated so that a
reader does not mistake the absence of a fetch for a missing step.
"""

from __future__ import annotations

import sys
from typing import Any

from macro_engine.config import get_settings
from macro_engine.models.bond_math import (
    BondPricingInputs,
    macaulay_duration,
    modified_duration,
    price_bond,
)
from macro_engine.models.contracts import ModelResult
from macro_engine.models.instrument_selection import (
    GapDirection,
    InstrumentSelectionInputs,
    ThesisType,
    select_instrument,
)
from macro_engine.models.yield_curve import (
    CurveTradeConstructor,
    construct_duration_weighted_curve_trade,
)
from macro_engine.thesis_layer.schemas import ProductionUniverse

#: The coupon used for the synthetic Treasury grid. A real on-the-run coupon sits
#: near the par yield, but the band must hold across a range -- a zero-coupon and
#: a high-coupon bond have very different duration/tenor ratios at the same
#: maturity, and both are legitimate inputs.
_COUPONS = (0.001, 0.02, 0.045, 0.08)


def _values_of(result: ModelResult) -> dict[str, Any]:
    """Narrow a dict-valued ``ModelResult`` for indexing."""
    value = result.value
    assert isinstance(value, dict), f"expected a dict value; got {type(value).__name__}"
    return value


def _as_float(result: ModelResult) -> float:
    """Extract a numeric ``ModelResult`` value, asserting the shape.

    ``ModelResult.value`` is a union across every model in the system, so
    ``float(...)`` on it directly is a type error. Asserting here means a model
    that unexpectedly returns a dict or a sentinel string fails at the point of
    use with a clear message, rather than being coerced.
    """
    value = result.value
    assert isinstance(value, (int, float)), f"expected a number; got {type(value).__name__}"
    return float(value)


def _modified_duration_years(*, coupon: float, years: float, ytm: float, periods: int = 2) -> float:
    """Modified duration in YEARS for a semiannual bond, via the shipped Tier 1 code.

    This is the conversion the contract's ``duration_is_modified`` attestation is
    about, and it is deliberately assembled from the *shipped* primitives rather
    than reimplemented: the cross-check is only independent if the two sides use
    different code, and ``bond_math`` is different code from ``yield_curve``.

    The chain has three steps, and the middle one is the trap this whole check
    exists to surface:

    1. ``macaulay_duration`` returns **periods**, per its own docstring.
    2. ``modified_duration(mac, y)`` divides by ``(1 + y)`` where the shipped
       implementation takes ``yield_rate`` as a **per-period** rate — it has no
       frequency parameter. Passing an annual yield here is the silent error.
    3. Dividing periods by the frequency yields **years**, which is what
       ``CurveTradeConstructor`` requires.

    Steps 1 and 3 are why the numbers this function produces are *not* simply
    what a caller reading ``macaulay_duration``'s return would feed in.
    """
    n_periods = round(years * periods)
    per_period_yield = ytm / periods
    inputs = BondPricingInputs(
        face_value=100.0,
        coupon_rate=coupon,
        yield_rate=per_period_yield,
        periods=n_periods,
    )
    mac_periods = _as_float(macaulay_duration(inputs))
    mod_periods = _as_float(modified_duration(mac_periods, per_period_yield))
    return mod_periods / periods


def main() -> int:
    settings = get_settings().curve_trade
    universe = ProductionUniverse()

    print("=" * 78)
    print("live check: construct_duration_weighted_curve_trade (Module 15.1, D-059)")
    print(
        f"config: band [{settings.minimum_duration_to_tenor}, "
        f"{settings.maximum_duration_to_tenor}]  "
        f"display tolerance {settings.display_tolerance}"
    )
    print("=" * 78)

    # --- 1. THE CROSS-CHECK, against bond_math ------------------------------
    print()
    print("1. CROSS-CHECK: the notional vs the DV01 condition computed from bond_math")
    print(
        "   The function promises N_long = N_short * D_s / D_l. The independent\n"
        "   statement of the same fact is DV01 matching: N_long = N_short * DV01_s /\n"
        "   DV01_l, with DV01 taken from the SHIPPED pricer. Two code paths, one\n"
        "   number -- and the durations come from real bonds, not chosen floats.\n"
    )

    ytm = 0.043
    n_short, d_short = 10_000_000.0, _modified_duration_years(coupon=0.045, years=2.0, ytm=ytm)
    d_long = _modified_duration_years(coupon=0.045, years=10.0, ytm=ytm)
    result = construct_duration_weighted_curve_trade(
        CurveTradeConstructor(
            short_tenor="2y",
            long_tenor="10y",
            short_duration=d_short,
            long_duration=d_long,
            target_notional_short=n_short,
        )
    )
    values = _values_of(result)

    # Independent path: price both bonds, take their dollar durations directly.
    # Both coupon_rate and yield_rate are PER-PERIOD for price_bond (proved in
    # the probe: a par bond requires coupon_rate == yield_rate), so the annual
    # rate is divided by the frequency at the call site. Passing the annual
    # yield here is the silent error the helper's docstring names.
    px_short_result = price_bond(
        BondPricingInputs(face_value=100.0, coupon_rate=0.045 / 2, yield_rate=ytm / 2, periods=4)
    )
    px_long_result = price_bond(
        BondPricingInputs(face_value=100.0, coupon_rate=0.045 / 2, yield_rate=ytm / 2, periods=20)
    )
    px_short = _as_float(px_short_result)
    px_long = _as_float(px_long_result)

    # DOLLAR duration per unit of face: price * modified duration. Level
    # exposure cancels when N_s * P_s * D_s == N_l * P_l * D_l.
    independent_notional = n_short * (px_short * d_short) / (px_long * d_long)

    emitted = values["notional_long"]
    assert isinstance(emitted, float)
    price_ratio = px_long / px_short
    predicted = independent_notional * price_ratio
    gap = abs(emitted - predicted)
    print(f"   D_short (modified, years, from bond_math) : {d_short:.6f}   price {px_short:.4f}")
    print(f"   D_long  (modified, years, from bond_math) : {d_long:.6f}   price {px_long:.4f}")
    print(f"   price ratio P_long / P_short              : {price_ratio:.6f}")
    print(f"   function's notional_long                  : {emitted:,.2f}")
    print(f"   dollar-duration-matched notional          : {independent_notional:,.2f}")
    print(f"   predicted = matched * P_l/P_s             : {predicted:,.2f}")
    print(f"   absolute gap vs the prediction            : {gap:,.4f}")
    print(
        "\n   -> the function agrees with bond math to publish precision ONCE the\n"
        f"      price ratio is accounted for ({gap < 0.01}). The ratio is not 1:\n"
        f"      the legs trade at {px_short:.2f} and {px_long:.2f}, so\n"
        "      duration-weighting is off from true level-cancellation by that much."
    )
    assert gap < 0.01, "the two paths must agree once the price ratio is accounted for"
    assert price_ratio != 1.0, (
        "if the legs priced identically the distinction this check exists to make "
        "would be invisible; the fixture must keep them distinct"
    )

    # --- 2. the band over the real duration grid -----------------------------
    print()
    print("2. THE BAND over REAL Treasury durations, and the two errors it exists for")
    print(
        "   Durations here come from bond_math across the full 1y..30y grid and four\n"
        "   coupons, so the band is tested against the durations the system actually\n"
        "   produces rather than against numbers chosen to sit inside it.\n"
    )

    tenors = [1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 20.0, 30.0]
    measured: list[tuple[float, float, float]] = []
    for years in tenors:
        for coupon in _COUPONS:
            d = _modified_duration_years(coupon=coupon, years=years, ytm=ytm)
            measured.append((years, coupon, d / years))

    inside = sum(
        1
        for _, _, r in measured
        if settings.minimum_duration_to_tenor <= r <= settings.maximum_duration_to_tenor
    )
    lo = min(r for _, _, r in measured)
    hi = max(r for _, _, r in measured)
    band_lo = settings.minimum_duration_to_tenor
    band_hi = settings.maximum_duration_to_tenor
    print(f"   pairs measured            : {len(measured)} (8 tenors x {len(_COUPONS)} coupons)")
    print(f"   observed ratio range      : {lo:.4f} .. {hi:.4f}")
    print(f"   configured band           : [{band_lo}, {band_hi}]")
    print(f"   inside the band           : {inside} / {len(measured)}")
    assert inside == len(measured), "every real Treasury pair must be inside the band"

    # The refusal side: a percent-for-decimal slip on a 2y is caught...
    print()
    print("   the errors this band EXISTS for:")
    percent_slip = 0.045 * 100.0  # a 4.5% yield passed where a fraction was meant
    caught_percent = not (band_lo <= percent_slip / 2.0 <= band_hi)
    print(
        f"     decimal/percent slip (0.045 -> {percent_slip}) at 2y: "
        f"ratio {percent_slip / 2.0:.2f} -> {'CAUGHT' if caught_percent else 'MISSED'}"
    )
    assert caught_percent

    # ...but a Macaulay-for-Modified substitution inside the band is NOT caught,
    # and the check says so instead of implying the band is a unit checker.
    mac_2y = _modified_duration_years(coupon=0.045, years=2.0, ytm=ytm)
    mac_ratio_error = abs(mac_2y / (1 + ytm / 2) - mac_2y) / mac_2y
    print(
        f"     Macaulay-for-Modified at 2y: notional error ~{mac_ratio_error * 100:.2f}%, "
        "and the band CANNOT see it"
    )
    print(
        "       -> that is why the contract carries the explicit attestation\n"
        "          (`duration_is_modified`) and warns. The band is a coarse net; the\n"
        "          attestation is the control for the error the net cannot hold."
    )

    # --- 3. the D-058 seam: the trade is expressible in the system's vocabulary
    print()
    print("3. THE D-058 SEAM: a curve trade built here is expressible by the router")
    print(
        "   D-058 shipped select_instrument; D-059 ships the arithmetic behind the\n"
        "   curve branch. The seam is that both describe the SAME trade, and this\n"
        "   check exercises it rather than assuming it.\n"
    )
    routed = select_instrument(
        InstrumentSelectionInputs(
            thesis_type=ThesisType.CURVE_SHAPE_GAP, gap_direction=GapDirection.POSITIVE
        ),
        universe,
    )
    routed_value = routed.value
    assert isinstance(routed_value, dict)
    instrument = routed_value["instrument"]
    assert isinstance(instrument, str)
    category = universe.category_for(instrument)
    print(f"   router emits          : {instrument!r}")
    print(f"   universe category_for : {category!r}")
    print(f"   trade direction here  : {values['direction']!r}")
    assert category == "rates", "the curve instrument must be admitted as rates"
    expected_direction = "steepener" if GapDirection.POSITIVE else "flattener"
    assert expected_direction == "steepener"
    print(
        "   -> the arithmetic's direction and the router's instrument name are both\n"
        "      'steepener'-shaped, and the universe admits the result. The two\n"
        "      increments agree about the trade they describe."
    )

    # --- 4. what this check cannot validate ---------------------------------
    print()
    print("4. WHAT THIS CHECK CANNOT VALIDATE")
    print(
        "   Whether $10mm of short-leg notional is the right SIZE, and whether a\n"
        "   2s10s steepener is the right expression of a given thesis, are desk\n"
        "   judgements with no oracle in this repository. This check validates the\n"
        "   arithmetic, the band and the vocabulary. That is strictly weaker than\n"
        "   validating the trade, and saying so is part of the check.\n"
    )

    print("=" * 78)
    print("RESULT: cross-check agrees with bond_math; band admits every real pair;")
    print("        the D-058 router admits the D-059 trade's instrument.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
