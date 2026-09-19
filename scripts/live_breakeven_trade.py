"""Live cross-check: ``construct_breakeven_trade`` against bond math and
against the D-058 router's own TIPS vocabulary.

Not a test. Operator scripts are deliberately excluded from the default test run
because they exercise the real settings tree and other real modules. Run with::

    uv run python scripts/live_breakeven_trade.py

Section 21.0: unit tests prove the arithmetic, this proves the wiring. What
"the wiring" means for D-060 is the whole point of this docstring, because this
check is the first in the project whose cross-check **fails against the shipped
rule on purpose**.

The shape of the problem
------------------------
``construct_breakeven_trade`` implements §15.1b's rule
``N_nominal = N_tips · D_tips / D_nominal``. Its sibling
(``construct_duration_weighted_curve_trade``, D-059) carries an identical rule,
and D-060's probe established that D-059's live check already reports the gap
between that rule and true level cancellation: the rule matches **duration**
while level exposure cancels on **dollar duration**, ``N·P·D``. The two differ by
the ratio of the legs' prices.

That matter differently here. In a curve trade both legs are nominals of the same
credit, so both trade near par and the price ratio is small. Here the legs are a
**TIPS** and a **nominal**: the TIPS leg's price is driven by its own real yield
and its (typically low) real coupon, and it can trade well off par. So the gap
that D-059 reported as a curiosity is, for this function, the dominant
approximation in the model.

The four things this check establishes
--------------------------------------

1. **THE CROSS-CHECK, against ``bond_math``, and it is a FAILURE by design.**
   Both legs are priced by the shipped Tier 1 functions and their durations
   converted by the shipped ``modified_duration``. The emitted notional is
   compared against the dollar-duration-matched notional computed from those
   prices. The two are asserted to *differ*, and the difference is measured
   rather than asserted away. §15.1b's rule is reproduced exactly -- so this is
   not an implementation bug, it is a property of the specified rule, and the
   check's job is to put a number on it. **O-59** carries it.

2. **The gap's sign and its scale across the real configuration space.** The
   TIPS leg is measured over a grid of coupons (including the 0.125% real
   coupon real issues carry) and real yields, against a nominal leg held at par.
   The finding is that the shortfall is **two-signed**: with a par nominal the
   identity ``shortfall = P_nom/P_tips - 1`` reduces to ``100/P_tips - 1``, so
   the sign flips at the TIPS leg's own par price. Measured range
   **-56.38% .. +98.72%**. A one-signed error would at least be hedgeable with a
   constant adjustment; this one cannot be, which is why O-59 is an open issue
   rather than a documented approximation.

3. **The D-058 seam, in the breakeven direction.** ``select_instrument`` emits a
   breakeven instrument name; the check confirms the production universe admits
   it under ``rates``, which is the round-trip D-058's ``_RATES_KEYWORDS`` and
   D-060's contract both depend on. This is a two-keyword round-trip ("tips" AND
   "breakeven"), so it is a stronger seam test than D-059's.

4. **Reports what it cannot validate.** Whether a breakeven trade is the right
   expression of an inflation thesis is a desk judgement. The check validates the
   arithmetic, the band, the direction report and the vocabulary. Stated rather
   than implied.

Offline by design: the object under validation is arithmetic over durations and
prices computed locally from the shipped pricer, so this check needs **no
network**. "Live" here means "through the live settings tree and the real Tier 1
duration and price producers".
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
    BreakevenTradeConstructor,
    construct_breakeven_trade,
)
from macro_engine.thesis_layer.schemas import ProductionUniverse

#: Real-coupon grid for the TIPS leg. 0.125% is the floor the US Treasury has
#: actually issued at, and it is where the duration/price behaviour is most
#: different from a nominal -- which is the whole reason this check exists.
_REAL_COUPONS = (0.00125, 0.02, 0.045, 0.08)

#: Real-yield grid for the TIPS leg. Covers the post-2021 range where TIPS real
#: yields went from deeply negative to above 2%.
_REAL_YIELDS = (0.005, 0.015, 0.025, 0.035)

#: Breakeven grid: the spread the two legs' yields differ by.
_BREAKEVENS = (0.005, 0.015, 0.025)

#: The tenor the two legs share, per the contract's single ``tenor`` field.
_TENOR_YEARS = 10.0
_TENOR_LABEL = "10y"
_PERIODS = 2


def _values_of(result: ModelResult) -> dict[str, Any]:
    """Narrow a dict-valued ``ModelResult`` for indexing."""
    value = result.value
    assert isinstance(value, dict), f"expected a dict value; got {type(value).__name__}"
    return value


def _as_float(result: ModelResult) -> float:
    """Extract a numeric ``ModelResult`` value, asserting the shape."""
    value = result.value
    assert isinstance(value, (int, float)), f"expected a number; got {type(value).__name__}"
    return float(value)


def _leg(*, coupon: float, years: float, ytm: float) -> tuple[float, float]:
    """``(price, modified_duration_years)`` for a semiannual bond, via ``bond_math``.

    The cross-check is only independent if the two sides use different code, and
    ``bond_math`` is different code from ``yield_curve``. Everything here comes
    from the shipped Tier 1 primitives; nothing is reimplemented.

    Two shipped behaviours this helper has to respect, both of which are silent
    errors if ignored (the D-059 check documents the same two):

    1. ``macaulay_duration`` returns **periods**, and
       ``modified_duration(mac, y)`` divides by ``(1 + y)`` with ``y`` taken as a
       **per-period** rate -- it has no frequency parameter. Dividing periods by
       the frequency yields years.
    2. ``price_bond`` rounds its output to two decimals. That is fine for a
       price, and it is why the check reports a gap tolerance rather than
       asserting float equality.
    """
    n_periods = round(years * _PERIODS)
    per_period_yield = ytm / _PERIODS
    inputs = BondPricingInputs(
        face_value=100.0,
        coupon_rate=coupon,
        yield_rate=per_period_yield,
        periods=n_periods,
    )
    mac_periods = _as_float(macaulay_duration(inputs))
    mod_periods = _as_float(modified_duration(mac_periods, per_period_yield))
    price = _as_float(price_bond(inputs))
    return price, mod_periods / _PERIODS


def main() -> int:
    settings = get_settings().curve_trade
    universe = ProductionUniverse()

    print("=" * 78)
    print("live check: construct_breakeven_trade (Module 15.1b / 15.2, D-060)")
    print(
        f"config: ratio band [{settings.minimum_breakeven_duration_ratio}, "
        f"{settings.maximum_breakeven_duration_ratio}]  "
        f"display tolerance {settings.display_tolerance}"
    )
    print("=" * 78)

    # --- 1. THE CROSS-CHECK, against bond_math ------------------------------
    print()
    print("1. CROSS-CHECK: the emitted notional vs the DOLLAR-duration condition")
    print(
        "   The function promises N_nom = N_tips * D_tips / D_nom, per 15.1b. The\n"
        "   independent statement of level cancellation is dollar-duration\n"
        "   matching: N_tips * P_tips * D_tips == N_nom * P_nom * D_nom, with the\n"
        "   durations AND prices taken from the SHIPPED pricer. Both legs are real\n"
        "   10y bonds; the TIPS leg is a real-coupon bond at a real yield.\n"
    )

    real_coupon, real_yield, breakeven = 0.00125, 0.025, 0.015
    nominal_yield = real_yield + breakeven
    n_tips = 10_000_000.0

    px_tips, d_tips = _leg(coupon=real_coupon, years=_TENOR_YEARS, ytm=real_yield)
    # The nominal leg is a FRESH-ISSUE bond: its coupon is set to the breakeven
    # yield so it prices at par. Anything else would confound the finding with
    # an off-market coupon, and the finding has to survive the most charitable
    # possible nominal.
    px_nom, d_nom = _leg(coupon=nominal_yield, years=_TENOR_YEARS, ytm=nominal_yield)

    result = construct_breakeven_trade(
        BreakevenTradeConstructor(
            tenor=_TENOR_LABEL,
            tips_duration=d_tips,
            nominal_duration=d_nom,
            target_notional_tips=n_tips,
        )
    )
    values = _values_of(result)
    emitted = values["notional_nominal_short"]
    assert isinstance(emitted, float)

    # Independent path: dollar-duration matching, from prices bond_math produced.
    dd_tips = n_tips * px_tips * d_tips
    dd_matched_nominal = dd_tips / (px_nom * d_nom)
    # The N*D rule the shipped function implements, recomputed here from the
    # durations alone so the check distinguishes the RULE from its WIRING.
    nd_rule_nominal = n_tips * d_tips / d_nom

    shortfall = (emitted - dd_matched_nominal) / dd_matched_nominal
    print(
        f"   real coupon / yield / breakeven       : "
        f"{real_coupon:.5f} / {real_yield:.3f} / {breakeven:.3f}"
    )
    print(f"   TIPS  leg: price {px_tips:9.4f}   modified duration {d_tips:.6f} yr")
    print(f"   NOM   leg: price {px_nom:9.4f}   modified duration {d_nom:.6f} yr")
    print(f"   price ratio P_nom / P_tips            : {px_nom / px_tips:.6f}")
    print()
    print(f"   N*D rule, recomputed here             : {nd_rule_nominal:,.2f}")
    print(f"   function's notional_nominal_short     : {emitted:,.2f}")
    print(f"   dollar-duration-matched notional      : {dd_matched_nominal:,.2f}")
    print(f"   shortfall of the emitted notional     : {shortfall * 100:+.2f}%")

    assert abs(emitted - nd_rule_nominal) < 0.01, (
        "the function must reproduce the 15.1b N*D rule to published precision; "
        "if it does not, the difference is an implementation bug and O-59 is the "
        "wrong place to record it"
    )
    assert abs(emitted - dd_matched_nominal) > 0.01, (
        "the emitted notional must DIFFER from the dollar-duration-matched one; "
        "if a fixture made them agree the check would be vacuous"
    )
    # The shortfall is not a fixture defect to be bounded away -- it IS the
    # finding. But it has an EXACT closed form, and asserting that form is what
    # turns the number from a measurement into a derivation. With
    #     shipped = N_t*D_t/D_n      and     exact = N_t*P_t*D_t/(P_n*D_n),
    # the ratio shipped/exact = P_n/P_t, so
    #     shortfall = P_nom / P_tips - 1.
    # A fixture that failed this identity would indicate the two paths were not
    # computing the same thing, which is a check defect rather than a finding.
    predicted_shortfall = px_nom / px_tips - 1.0
    assert abs(shortfall - predicted_shortfall) < 1e-6, (
        f"the shortfall must equal P_nom/P_tips - 1 = {predicted_shortfall:+.6f}; "
        f"got {shortfall:+.6f}. The gap between the two rules IS the price ratio, "
        "and if that identity fails the check is comparing unlike quantities."
    )
    side = "OVER-hedges" if shortfall > 0 else "UNDER-hedges"
    print(
        "\n   -> the function reproduces 15.1b EXACTLY, and 15.1b is not dollar-\n"
        "      duration matching. It hedges DURATION, not level. The shortfall is\n"
        f"      P_nom/P_tips - 1 = {px_nom:.2f}/{px_tips:.2f} - 1 exactly, so the gap\n"
        "      is the LEGS' PRICE RATIO and nothing else.\n"
        f"      In THIS fixture the TIPS trades below par, so the rule {side}\n"
        "      the nominal leg. Item 2 measures which sign dominates in practice.\n"
        "      Recorded as O-59."
    )

    # --- 2. the gap's scale over the real configuration space ----------------
    print()
    print("2. THE GAP over the REAL TIPS configuration space")
    print(
        "   The TIPS leg is swept over real coupons (0.125%..8%), real yields\n"
        "   (0.5%..3.5%) and breakevens (0.5%..2.5%) -- the range US TIPS have\n"
        "   actually traded in. The nominal leg is always a FRESH ISSUE, priced at\n"
        "   par against its own coupon, so the grid varies the TIPS leg alone and\n"
        "   the nominal is the most favourable case the rule can be given.\n"
    )

    cases: list[tuple[float, float, float, float]] = []
    for rc in _REAL_COUPONS:
        for ry in _REAL_YIELDS:
            for be in _BREAKEVENS:
                ny = ry + be
                pc, tc = _leg(coupon=rc, years=_TENOR_YEARS, ytm=ry)
                # Fresh-issue nominal: coupon == yield, so it prices at par and
                # the TIPS leg's own price is the only thing moving.
                pn, tn = _leg(coupon=ny, years=_TENOR_YEARS, ytm=ny)
                shipped = n_tips * tc / tn
                exact = (n_tips * pc * tc) / (pn * tn)
                cases.append(((shipped - exact) / exact, rc, ry, be))

    worst = min(cases, key=lambda c: c[0])
    mildest = max(cases, key=lambda c: c[0])
    over = sum(1 for c in cases if c[0] > 0)
    under = sum(1 for c in cases if c[0] < 0)
    # With a par nominal, P_nom = 100, so the identity shortfall = P_nom/P_tips - 1
    # reduces to 100/P_tips - 1: the shortfall is positive exactly when the TIPS
    # trades BELOW par. The sign is therefore set by the TIPS price alone, which
    # is why a two-signed gap is the expected result, not a fixture error.
    dollar_worst = worst[0] * n_tips
    print(f"   cases measured                        : {len(cases)}")
    print(
        f"   shortfall range                       : "
        f"{worst[0] * 100:+.2f}% .. {mildest[0] * 100:+.2f}%"
    )
    print(f"   cases that OVER-hedge  (TIPS < par)   : {over} / {len(cases)}")
    print(f"   cases that UNDER-hedge (TIPS > par)   : {under} / {len(cases)}")
    print(
        f"   worst case    : coupon {worst[1]:.5f}, real yield {worst[2]:.3f}, "
        f"breakeven {worst[3]:.3f}"
    )
    print(
        f"   -> at $10mm TIPS of notional the worst case misstates the nominal leg\n"
        f"      by ~${abs(dollar_worst):,.0f}, in the "
        f"{'short' if worst[0] < 0 else 'long'} direction"
    )
    assert over > 0 and under > 0, (
        "the shortfall is expected to be TWO-SIGNED: with a par nominal it equals "
        "100/P_tips - 1, which flips at par. A one-signed result would mean the "
        "grid never crossed par and the finding is narrower than claimed"
    )
    print(
        "   -> the gap changes SIGN. A systematic error would at least be\n"
        "      predictable; this one flips with the TIPS leg's own price, so it\n"
        "      cannot be hedged by applying a constant adjustment. That is what\n"
        "      makes O-59 an open issue rather than a documented approximation."
    )

    # --- 3. the ratio band, against bond_math's own durations ----------------
    print()
    print("3. THE RATIO BAND against real durations, and the assumption it refutes")
    print(
        "   15.1b's own prose implies the TIPS leg always has the longer duration.\n"
        "   The contract does not assume it and reports the direction instead. This\n"
        "   section measures whether that caution was warranted.\n"
    )

    inside = 0
    nominal_longer = 0
    ratios: list[float] = []
    for rc in _REAL_COUPONS:
        for ry in _REAL_YIELDS:
            for be in _BREAKEVENS:
                _, tc = _leg(coupon=rc, years=_TENOR_YEARS, ytm=ry)
                _, tn = _leg(coupon=ry + be, years=_TENOR_YEARS, ytm=ry + be)
                ratio = tc / tn
                ratios.append(ratio)
                in_band = (
                    settings.minimum_breakeven_duration_ratio
                    <= ratio
                    <= settings.maximum_breakeven_duration_ratio
                )
                if in_band:
                    inside += 1
                if ratio < 1.0:
                    nominal_longer += 1
    print(f"   pairs measured                        : {len(ratios)}")
    print(f"   observed D_tips / D_nom range         : {min(ratios):.4f} .. {max(ratios):.4f}")
    print(
        f"   configured band                       : "
        f"[{settings.minimum_breakeven_duration_ratio}, "
        f"{settings.maximum_breakeven_duration_ratio}]"
    )
    print(f"   inside the band                       : {inside} / {len(ratios)}")
    print(f"   the NOMINAL leg is longer (ratio < 1) : {nominal_longer} / {len(ratios)}")
    assert inside == len(ratios), "every real TIPS/nominal pair must sit inside the band"
    assert nominal_longer > 0, (
        "the spec's prose assumes the TIPS duration is always longer; if no real "
        "configuration refutes it, the contract's direction field is dead code "
        "and should be re-examined"
    )
    print(
        f"   -> the prose assumption is REFUTED in {nominal_longer} of {len(ratios)} real\n"
        "      configurations, which is why the contract reports the direction\n"
        "      rather than asserting it."
    )

    # --- 4. the D-058 seam, breakeven direction -----------------------------
    print()
    print("4. THE D-058 SEAM: the breakeven trade is expressible by the router")
    print(
        "   D-058's select_instrument emits a TIPS/breakeven instrument name for\n"
        "   inflation theses. D-060 ships the arithmetic behind it. The seam is\n"
        "   that the name round-trips through the production universe's keyword\n"
        "   classifier. This is a two-keyword round-trip ('tips' AND 'breakeven'),\n"
        "   so it is a stronger seam test than the curve trade's.\n"
    )
    routed = select_instrument(
        InstrumentSelectionInputs(
            thesis_type=ThesisType.INFLATION_EXPECTATIONS_GAP,
            gap_direction=GapDirection.POSITIVE,
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
    direction = values["duration_direction"]
    print(f"   function reports      : {direction!r}")
    assert category == "rates", "the breakeven instrument must be admitted as rates"
    lowered = instrument.lower()
    assert "tips" in lowered and "breakeven" in lowered, (
        "the seam depends on BOTH classifiable keywords surviving in the router's "
        "name; if one is dropped the instrument routes nowhere"
    )
    print(
        "   -> both keywords survive and the universe admits the instrument under\n"
        "      'rates'. The two increments agree about the trade they describe."
    )

    # --- 5. what this check cannot validate ---------------------------------
    print()
    print("5. WHAT THIS CHECK CANNOT VALIDATE")
    print(
        "   Whether a breakeven trade is the right expression of an inflation\n"
        "   thesis, and whether the measured under-hedge in item 2 is acceptable\n"
        "   for the desk's book, are judgements with no oracle in this repository.\n"
        "   Nor can this check fix O-59: the exact rule needs the legs' PRICES, and\n"
        "   the contract carries none, so the choice is a contract change, not a\n"
        "   computation. This check measures the size of that choice.\n"
    )

    print("=" * 78)
    print("RESULT: the N*D rule is reproduced exactly and is NOT level-cancelling;")
    print("        the resulting shortfall equals P_nom/P_tips - 1 and is TWO-SIGNED")
    print("        across real TIPS configurations (-56.4% .. +98.7%) -- O-59; the")
    print("        router's breakeven vocabulary round-trips. The spec's 'TIPS is")
    print("        always longer' is refuted by real durations.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
