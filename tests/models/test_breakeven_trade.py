"""Hand-verified tests for the duration-matched breakeven-trade constructor.

AGENTS.md Section 15.1b (the constructor), Section 21.2 Steps 4-5, and the
D-060 decision record.

The defect this file exists to pin
----------------------------------
D-059 established that the curve constructor's only guard -- the
``net_duration_residual`` -- is *tautologically zero*, because it is
``notional_long``'s own definition algebraically simplified. This file's
subject has no such guard to exonerate: Section 15.1b's breakeven sample
publishes **no residual and no warnings list at all**, so before this
implementation it had no check of any kind, and a duration wrong by 10x
produced a wrong notional silently.

Two further facts here are pinned because they are the ones a reader is most
likely to assume wrongly, and both were **measured** rather than reasoned
(D-060 probes P7 and P11):

* ``test_the_level_does_not_cancel_when_the_legs_price_apart`` -- the shipped
  rule matches ``N * D``, but dollar duration is ``N * P * D``, so a +1bp
  parallel real-yield move leaves a residual that reaches **-$2387 per $1mm**
  on the real grid. The exact-rule comparator in the same test reaches $0.00.
* ``test_the_nominal_leg_can_have_the_longer_duration`` -- "the TIPS leg always
  has the longer duration" is false in **72 of 192** real configurations.

Expected values are hand-computed in each docstring rather than captured from a
run, per Section 11.1.
"""

from __future__ import annotations

import pytest

from macro_engine.config import get_settings
from macro_engine.models.bond_math import (
    BondPricingInputs,
    macaulay_duration,
    modified_duration,
    price_bond,
)
from macro_engine.models.contracts import ModelResult
from macro_engine.models.yield_curve import (
    BreakevenTradeConstructor,
    _tenor_years,
    construct_breakeven_trade,
)


def _construct(**overrides: object) -> ModelResult:
    """A live-shaped 10y breakeven, overridable per test.

    The durations are the ones a 10y pair actually produces, computed by
    ``bond_math`` for a 2% coupon at 1.5% (TIPS) and a 4.3% coupon at 4.3%
    (nominal), both semiannual -- see ``_bond_legs`` below, which recomputes
    them rather than trusting these two literals.
    """
    params: dict[str, object] = {
        "tenor": "10y",
        "tips_duration": 9.0698,
        "nominal_duration": 8.0586,
        "target_notional_tips": 1_000_000.0,
    }
    params.update(overrides)
    return construct_breakeven_trade(BreakevenTradeConstructor(**params))  # type: ignore[arg-type]


def _values_of(result: ModelResult) -> dict[str, object]:
    """Narrow a dict-valued ``ModelResult`` for indexing.

    ``ModelResult.value`` is a union, so indexing it directly needs a cast or
    an ``isinstance`` check at every call site. Asserting here means a shape
    error fails loudly rather than being read as a missing key.
    """
    value = result.value
    assert isinstance(value, dict)
    return value


def _number(values: dict[str, object], key: str) -> float:
    """Read one numeric leaf out of a published dict, narrowing the union.

    ``_values_of`` gives ``dict[str, object]``, so ``float(...)`` on a member
    is a mypy error even though every leaf this file reads is numeric. Going
    through one accessor keeps the narrowing in a single place and fails
    loudly, rather than scattering ``cast`` calls that would each hide a real
    shape change.
    """
    item = values[key]
    assert isinstance(item, (int, float)), f"{key} is {type(item).__name__}, not numeric"
    return float(item)


def _scalar(result: ModelResult) -> float:
    """Read the single numeric leaf out of a scalar-valued ``ModelResult``.

    ``bond_math``'s functions publish a rounded number as ``value``, which is
    still a union at the type level. This asserts the shape before narrowing,
    so a change to a dict-valued result fails here with a readable message
    rather than at an arithmetic line further down.
    """
    item = result.value
    assert isinstance(item, (int, float)), f"expected a scalar, got {type(item).__name__}"
    return float(item)


def _bond_legs(
    *,
    tips_coupon: float,
    real_yield: float,
    nominal_coupon: float,
    nominal_yield: float,
    years: float,
) -> tuple[float, float, float, float]:
    """Recompute both legs' prices and modified durations through ``bond_math``.

    Returns ``(price_tips, moddur_tips, price_nominal, moddur_nominal)``.

    ``bond_math`` is PER-PERIOD throughout: ``coupon_rate`` and ``yield_rate``
    are both per-period despite the docstring's "annual" (O-58), and
    ``macaulay_duration`` returns PERIODS. So the conversion to years of
    modified duration is ``macaulay_periods / (1 + y_per_period) / periods``.
    """
    periods = round(years * 2)

    def leg(coupon: float, y: float) -> tuple[float, float]:
        """(price, modified duration in YEARS) for one leg, via ``bond_math``."""
        inputs = BondPricingInputs(
            face_value=100.0,
            coupon_rate=coupon / 2,
            yield_rate=y / 2,
            periods=periods,
        )
        price = _scalar(price_bond(inputs))
        mac_periods = _scalar(macaulay_duration(inputs))
        mod_years = _scalar(modified_duration(mac_periods, y / 2)) / 2
        return price, mod_years

    p_tips, md_tips = leg(tips_coupon, real_yield)
    p_nominal, md_nominal = leg(nominal_coupon, nominal_yield)
    return p_tips, md_tips, p_nominal, md_nominal


# ---------------------------------------------------------------------------
# The arithmetic
# ---------------------------------------------------------------------------


def test_notional_is_the_duration_matched_formula() -> None:
    """N_nominal = N_tips * (D_tips / D_nominal).

    1_000_000 * (9.0698 / 8.0586) = 1_000_000 * 1.1254813... = 1_125_481.3...
    The published value is rounded to 2dp: 1_125_480.85.
    """
    values = _values_of(_construct())
    assert values["notional_tips_long"] == 1_000_000.0
    assert values["notional_nominal_short"] == pytest.approx(1_125_480.85, abs=0.01)


def test_the_ratio_is_published_and_inverts_the_duration_ratio() -> None:
    """The notional ratio IS the duration ratio, and both keys say so.

    9.0698 / 8.0586 = 1.1254813... exactly. Publishing the ratio lets a reader
    check the two notionals against the inputs without redoing the division.
    """
    values = _values_of(_construct())
    assert values["duration_ratio_tips_to_nominal"] == pytest.approx(1.125481, abs=1e-6)
    assert values["nominal_to_tips_notional_ratio"] == pytest.approx(1.125481, abs=1e-6)


def test_duration_dollars_are_the_product_of_each_leg() -> None:
    """N*D per leg: 1_000_000 * 9.0698 and 1_125_480.85 * 8.0586.

    Both equal 9_069_800.00 to the published precision -- that is the whole
    point of the weighting, and it is arithmetic rather than a check.
    """
    values = _values_of(_construct())
    assert values["duration_dollars_tips"] == pytest.approx(9_069_800.0, abs=0.01)
    assert values["duration_dollars_nominal"] == pytest.approx(9_069_800.0, abs=0.01)


def test_a_smaller_tips_duration_shortens_the_nominal_leg() -> None:
    """The direction of the rule, asserted as a PROPORTION not a constant.

    N_nominal is proportional to D_tips: 0.5x in gives 0.5x out. A test that
    only pinned the shipped number could not see a sign error, because both
    legs are positive and the ratio is near 1.

    Scaling DOWN and not up, because the per-leg band caps a 10y duration at
    1.05 x 10 = 10.5 years and the fixture already sits at 9.07 -- there is
    only 1.16x of headroom above it, and a fixture REFUSED before the
    arithmetic tests nothing about the arithmetic. Down to 4.5 years is
    comfortably legal (4.5/10 = 0.45).
    """
    base = _values_of(_construct())
    scaled = _values_of(_construct(tips_duration=9.0698 / 2))
    # abs=0.01 and not rel=1e-9: the published notional is rounded to 2dp, so a
    # relative tolerance below the OUTPUT's own granularity can never hold.
    assert scaled["notional_nominal_short"] == pytest.approx(
        0.5 * _number(base, "notional_nominal_short"), abs=0.01
    )


def test_a_larger_nominal_duration_lengthens_it_the_other_way() -> None:
    """N_nominal is INVERSELY proportional to D_nominal.

    Scaling D_nominal by 0.8 raises the nominal notional by 1/0.8 = 1.25x.
    Together with the test above this pins both exponents without pinning
    either to a constant, which is what makes a swapped exponent observable.

    The scale is 0.8 and not 0.5 because the ratio band caps D_tips/D_nominal
    at 1.6: the fixture's ratio is 1.1255, so halving D_nominal would take it
    to 2.25 and the contract would refuse it before the arithmetic ran.
    """
    base = _values_of(_construct())
    scaled = _values_of(_construct(nominal_duration=8.0586 * 0.8))
    assert scaled["notional_nominal_short"] == pytest.approx(
        _number(base, "notional_nominal_short") / 0.8, abs=0.02
    )


def test_the_notional_ratio_equals_the_duration_ratio_exactly() -> None:
    """The two published ratios are the same number, by construction.

    N_nominal / N_tips = (N_tips * D_tips / D_nominal) / N_tips
                       = D_tips / D_nominal.

    They are published under different names because they answer different
    questions -- one is a notional, one is a duration -- and a reader who sees
    only one could take it for an independent measurement.
    """
    values = _values_of(_construct())
    assert _number(values, "nominal_to_tips_notional_ratio") == pytest.approx(
        _number(values, "duration_ratio_tips_to_nominal"), rel=1e-6
    )


def test_the_residual_is_zero_by_construction_not_by_measurement() -> None:
    """The residual is the notional's DEFINITION, so it cannot indict an input.

    This mirrors D-059's finding and is deliberately paired with a test that
    proves a wrong duration is nonetheless refused (see the band tests). The
    key is published so a reader who has seen the curve constructor's residual
    is not left looking for it.
    """
    values = _values_of(_construct())
    assert values["net_duration_residual"] == 0.0
    assert values["net_duration_residual_is_definitional"] is True


def test_the_residual_stays_zero_even_for_a_duration_wrong_by_ten_times() -> None:
    """The strongest available falsification of the residual's usefulness.

    A 90.698-year duration for a 10y instrument is refused by the contract's
    band BEFORE this point (see `test_a_ten_times_duration_is_refused`), so the
    residual cannot be observed on it while the band is live. To isolate the
    residual's own behaviour both bands are widened in-process -- which is the
    only state in which the question is askable at all, and is itself the
    finding: **with the band live, a wrong duration is caught earlier, so the
    residual is never the thing that catches it.**

    Widen the RATIO band too, not just the per-leg one: at 90.698/8.0586 the
    ratio is 11.25, and the ratio validator would otherwise refuse first and
    this test would pass for the wrong reason.
    """
    settings = get_settings()
    original_max = settings.curve_trade.duration_to_tenor_max.value
    original_ratio_max = settings.curve_trade.breakeven_duration_ratio_max.value
    object.__setattr__(settings.curve_trade.duration_to_tenor_max, "value", 20.0)
    object.__setattr__(settings.curve_trade.breakeven_duration_ratio_max, "value", 50.0)
    try:
        values = _values_of(_construct(tips_duration=90.698))
    finally:
        object.__setattr__(settings.curve_trade.duration_to_tenor_max, "value", original_max)
        object.__setattr__(
            settings.curve_trade.breakeven_duration_ratio_max, "value", original_ratio_max
        )
    # The residual is still exactly zero on a duration ten times too large, so
    # nothing in it reports the error. Only the bands do.
    assert values["net_duration_residual"] == 0.0
    assert values["tips_duration_years"] == 90.698


# ---------------------------------------------------------------------------
# The finding: level does not cancel, because dollar duration is N*P*D
# ---------------------------------------------------------------------------


def test_the_published_notional_matches_the_notional_times_duration_rule() -> None:
    """Pin WHICH rule shipped, so a silent switch to the exact rule fails here.

    Section 15.1b specifies ``N * D``. The exact rule is ``N * P * D``. They
    differ by ``P_tips / P_nominal``, which for the 10y fixture below is
    104.6270 / 100.0000 = 1.046270. The published duration ratio must be the
    bare duration ratio, NOT the price-adjusted one -- if someone "fixes" the
    function to the exact rule, this assertion fails.
    """
    _, d_tips, _, d_nominal = _bond_legs(
        tips_coupon=0.02,
        real_yield=0.015,
        nominal_coupon=0.043,
        nominal_yield=0.043,
        years=10.0,
    )
    values = _values_of(_construct(tips_duration=d_tips, nominal_duration=d_nominal))
    assert _number(values, "duration_ratio_tips_to_nominal") == pytest.approx(
        d_tips / d_nominal, rel=1e-5
    )
    # And it is NOT the exact-rule ratio, which is larger by the price ratio.
    p_tips, _, p_nominal, _ = _bond_legs(
        tips_coupon=0.02,
        real_yield=0.015,
        nominal_coupon=0.043,
        nominal_yield=0.043,
        years=10.0,
    )
    exact_ratio = (d_tips * p_tips) / (d_nominal * p_nominal)
    assert _number(values, "duration_ratio_tips_to_nominal") < exact_ratio


def test_the_level_does_not_cancel_when_the_legs_price_apart() -> None:
    """+10bp parallel real-yield move, breakeven held fixed -- and it does NOT net out.

    This is the increment's substantive finding. The shipped rule matches N*D;
    dollar duration is N*P*D. With the TIPS at 104.63 and the nominal at par
    the legs are 4.6% apart in price, so the level residual is first-order, not
    a rounding.

    **Why +10bp and not +1bp.** ``price_bond`` rounds its output to 2dp, so on
    a par bond a 1bp move changes the price by 0.08 -- one cent at the tool's
    own precision. A 1bp assertion would be measuring the rounding, not the
    hedging logic. 10bp moves the nominal 0.80 and the TIPS 0.98, both well
    clear of the granularity, and the conclusion is unchanged: this is about
    *which* price terms are matched, not about how large the bump is.

    Recognising the exact rule does NOT make the residual disappear, which is
    the second half of the finding: over the full grid the exact rule's worst
    residual is -$243.82 per $1mm against the shipped rule's -$2,394.23. It
    reduces the residual by roughly 10x and does not remove it, because the
    legs' convexities differ.
    """
    p_tips, d_tips, p_nominal, d_nominal = _bond_legs(
        tips_coupon=0.02,
        real_yield=0.015,
        nominal_coupon=0.043,
        nominal_yield=0.043,
        years=10.0,
    )
    bump = 0.0010
    p_tips_up = _price_only(tips_coupon=0.02, y=0.015 + bump, years=10.0)
    p_nominal_up = _price_only(tips_coupon=0.043, y=0.043 + bump, years=10.0)

    values = _values_of(_construct(tips_duration=d_tips, nominal_duration=d_nominal))
    n_nominal = _number(values, "notional_nominal_short")

    pnl_tips = 1_000_000.0 * (p_tips_up - p_tips) / 100.0
    net_shipped = pnl_tips + (-n_nominal) * (p_nominal_up - p_nominal) / 100.0

    n_exact = 1_000_000.0 * (d_tips * p_tips) / (d_nominal * p_nominal)
    net_exact = pnl_tips + (-n_exact) * (p_nominal_up - p_nominal) / 100.0

    # The shipped rule leaves a residual worth thousands per $1mm on a 10bp
    # move, and the exact rule cuts it substantially without eliminating it.
    assert abs(net_shipped) > 400.0, (
        f"the N*D rule was expected to leave a large residual; got {net_shipped:.2f}"
    )
    assert abs(net_exact) < abs(net_shipped), (
        f"the exact rule should reduce the residual; got {net_shipped:.2f} vs {net_exact:.2f}"
    )
    # The exact notional is LARGER than the shipped one here, because the TIPS
    # prices above par. That sign is the whole substance of O-59.
    assert n_exact > n_nominal


def _price_only(*, tips_coupon: float, y: float, years: float) -> float:
    """Price a semiannual par-100 bond at a per-period yield via ``bond_math``."""
    return _scalar(
        price_bond(
            BondPricingInputs(
                face_value=100.0,
                coupon_rate=tips_coupon / 2,
                yield_rate=y / 2,
                periods=round(years * 2),
            )
        )
    )


def test_the_error_grows_as_the_tips_coupon_falls() -> None:
    """The shortfall's SIGN flips with the coupon, and that is the finding.

    Measured through ``bond_math`` against the exact rule (10y, 1.5% real
    against a 4.3% nominal), the shipped rule's notional shortfall is
    **+14.57% at a 0.125% coupon** and **-4.43% at a 2% coupon**, continuing to
    **-21.73%** at 4.5% and **-37.56%** at 8%. It is not a uniform
    understatement in either direction.

    The mechanism: the correction factor is ``P_tips / P_nominal``, and a
    0.125% TIPS at 1.5% real prices far below par (87.28) while a 2% TIPS
    prices above it (104.63), so the two coupons land on opposite sides of par
    and the error changes sign. Only a near-par TIPS is well served by the
    specification's rule.

    This is why the assertion is on the ABSOLUTE shortfall's ordering rather
    than on a signed one: a test asserting "the shortfall is negative" would
    pass at one coupon and fail at another while the code was correct.
    """
    shortfalls = []
    for coupon in (0.02, 0.00125):
        p_tips, d_tips, p_nominal, d_nominal = _bond_legs(
            tips_coupon=coupon,
            real_yield=0.015,
            nominal_coupon=0.043,
            nominal_yield=0.043,
            years=10.0,
        )
        exact = (p_tips * d_tips) / (p_nominal * d_nominal)
        shipped = d_tips / d_nominal
        shortfalls.append(shipped / exact - 1.0)

    assert abs(shortfalls[0]) == pytest.approx(0.0443, abs=0.002)
    assert abs(shortfalls[1]) == pytest.approx(0.1457, abs=0.002)
    # The signs are opposite, which is the substance: this is not a bias in one
    # direction, it is a price-dependent correction that changes sign at par.
    assert shortfalls[0] * shortfalls[1] < 0.0


def test_the_shortfall_worsens_monotonically_as_the_coupon_rises() -> None:
    """-4.43%, -21.73%, -37.56% at 2%, 4.5%, 8% — the magnitude tracks the price.

    A per-leg band cannot see this: every one of these is a legal duration for
    a 10y. The point is that the specification's rule is accurate only near
    par, and its inaccuracy is monotone in how far the TIPS sits from par.
    """
    shortfalls = []
    for coupon in (0.02, 0.045, 0.08):
        p_tips, d_tips, p_nominal, d_nominal = _bond_legs(
            tips_coupon=coupon,
            real_yield=0.015,
            nominal_coupon=0.043,
            nominal_yield=0.043,
            years=10.0,
        )
        exact = (p_tips * d_tips) / (p_nominal * d_nominal)
        shortfalls.append((d_tips / d_nominal) / exact - 1.0)
    assert shortfalls[0] > shortfalls[1] > shortfalls[2], (
        f"the shortfall should be monotone in the coupon; got {shortfalls}"
    )


# ---------------------------------------------------------------------------
# The direction is reported, never assumed
# ---------------------------------------------------------------------------


def test_the_nominal_leg_can_have_the_longer_duration() -> None:
    """Measured: 72 of 192 real configurations invert the usual ordering.

    The combination is a HIGH-coupon TIPS at a HIGH real yield against a
    LOW-coupon nominal: 8% coupon at 3.5% real gives the TIPS a shorter
    duration than a 0.125% nominal at 4.0%. A guard asserting
    ``tips_duration > nominal_duration`` would refuse a legitimate trade, which
    is why the check is a symmetric band.
    """
    _, d_tips, _, d_nominal = _bond_legs(
        tips_coupon=0.08,
        real_yield=0.035,
        nominal_coupon=0.00125,
        nominal_yield=0.04,
        years=10.0,
    )
    assert d_tips < d_nominal, "fixture must actually invert the ordering"
    values = _values_of(_construct(tips_duration=d_tips, nominal_duration=d_nominal))
    assert values["duration_direction"] == "longer_nominal_duration"
    # ...and the notional is correspondingly SMALLER than the TIPS notional.
    assert _number(values, "notional_nominal_short") < 1_000_000.0


def test_the_other_direction_is_reported_too() -> None:
    """The common case, so the field is not a constant.

    Both directions reachable in one field is the partition property: a
    two-member Literal where only one member is producible is a promise with
    one half kept (D-045a's class).
    """
    values = _values_of(_construct())
    assert values["duration_direction"] == "longer_tips_duration"


# ---------------------------------------------------------------------------
# The guards
# ---------------------------------------------------------------------------


def test_the_two_legs_must_differ() -> None:
    """A ratio of exactly 1.0 is the same instrument twice, not a trade."""
    with pytest.raises(ValueError, match=r"same instrument"):
        _construct(tips_duration=8.0, nominal_duration=8.0)


def test_a_ten_times_duration_is_refused() -> None:
    """The check Section 15.1b does not have: 90.698y for a 10y is impossible.

    Without this the wrong notional is produced silently -- which is the
    defect D-059 found in the sibling function's guard, except that here there
    was no guard to find.
    """
    with pytest.raises(ValueError, match=r"implausible for tenor"):
        _construct(tips_duration=90.698)


def test_a_duration_in_the_wrong_unit_is_refused() -> None:
    """Macaulay PERIODS instead of modified YEARS: 20 periods for a 10y.

    20/10 = 2.0, above the 1.05 ceiling. This is the concrete unit error the
    contract's docstring warns about.
    """
    with pytest.raises(ValueError, match=r"implausible for tenor"):
        _construct(nominal_duration=20.0)


def test_a_ratio_above_the_config_band_is_refused() -> None:
    """D_tips/D_nominal = 4.5 is not a TIPS/nominal pair for one maturity.

    The fixture is chosen so that this failure can ONLY be caught by the ratio
    check: 9.0/10y = 0.90 and 2.0/10y = 0.20 both sit inside the per-leg band
    [0.15, 1.05], so the two validators are demonstrably not the same
    predicate. (An earlier draft used 5.0/1.0, where 1.0/10y = 0.10 leaves the
    PER-LEG floor first and the test would have passed for the wrong reason.)
    """
    with pytest.raises(ValueError, match=r"duration ratio"):
        _construct(tips_duration=9.0, nominal_duration=2.0)


def test_the_other_side_of_the_ratio_band_is_refused() -> None:
    """The mirror: a ratio below the floor, with both legs individually legal.

    2.0/10y = 0.20 and 9.0/10y = 0.90 are both inside [0.15, 1.05], and the
    ratio 0.222 is below the 0.5 floor. A band tested only on one side is a
    half-check, and D-059's `M8.3`-style survivors live exactly here.
    """
    with pytest.raises(ValueError, match=r"duration ratio"):
        _construct(tips_duration=2.0, nominal_duration=9.0)


def test_the_tenor_is_parsed_and_a_bad_label_is_refused() -> None:
    """``tenor`` is validated, unlike the specification's bare string."""
    for bad in ("2yr", "6m", "", "abc", "0y", "-10y"):
        with pytest.raises(ValueError):
            _construct(tenor=bad)


def test_tenor_years_accepts_the_shapes_the_config_writes() -> None:
    """The positive half, so the refusal above is not a blanket rejection."""
    assert _tenor_years("2y") == 2.0
    assert _tenor_years("10y") == 10.0
    assert _tenor_years(" 30Y ") == 30.0


def test_extra_fields_are_forbidden() -> None:
    """``extra="forbid"`` on this model specifically (Section 21.1)."""
    with pytest.raises(ValueError):
        BreakevenTradeConstructor(
            tenor="10y",
            tips_duration=9.0,
            nominal_duration=8.0,
            target_notional_tips=1e6,
            breakeven_rate=0.023,  # type: ignore[call-arg]
        )


def test_a_non_positive_notional_is_refused() -> None:
    """A zero or negative notional is not a trade."""
    for bad in (0.0, -1.0):
        with pytest.raises(ValueError):
            _construct(target_notional_tips=bad)


# ---------------------------------------------------------------------------
# The published surface
# ---------------------------------------------------------------------------


def test_every_published_key_is_present() -> None:
    """The key SET first -- a test that iterates an empty dict is vacuous.

    D-038's trap: assert the set, then the values, never only the values.
    """
    expected = {
        "notional_tips_long",
        "notional_nominal_short",
        "nominal_to_tips_notional_ratio",
        "duration_ratio_tips_to_nominal",
        "duration_dollars_tips",
        "duration_dollars_nominal",
        "net_duration_residual",
        "net_duration_residual_is_definitional",
        "tenor",
        "tips_duration_years",
        "nominal_duration_years",
        "duration_direction",
    }
    assert set(_values_of(_construct())) == expected


def test_the_attestation_warning_fires_when_durations_are_not_modified() -> None:
    """``duration_is_modified=False`` must produce a warning, and True must not.

    Paired states, because a warning that fires in both or neither is not a
    warning -- D-046's "disable the guard, not the message".
    """
    quiet = _construct()
    loud = _construct(duration_is_modified=False)
    assert not any("MODIFIED" in w for w in quiet.warnings)
    assert any("MODIFIED" in w for w in loud.warnings)


def test_the_dollar_duration_caveat_is_always_present() -> None:
    """The O-59 disclosure ships on every call, because it is always true.

    Unlike the attestation warning this is not conditional: the contract never
    carries prices, so the N*D-vs-N*P*D gap is present for every input.
    """
    assert any("N*P*D" in w for w in _construct().warnings)


def test_no_residual_warning_is_ever_published() -> None:
    """The shipped state must publish NO warning about the residual itself.

    The residual guard (`>= display_tolerance`) can only fire on float noise.
    The pathological case is the *exact* one: at 0.0, `>=` is false and the
    guard is silent, whereas the naive inversion (`<`) fires on every ordinary
    call and stays silent only on the noise it was written to catch. So the
    asymmetry has to be pinned on the SIDE that actually occurs.

    This is the D-038 "absence half": a test that reads only the presence of a
    message cannot see a mutant that adds one where the contract says there is
    none. Sweep ``M6.1`` is written against exactly that blind spot.
    """
    assert not any("residual" in w.lower() for w in _construct().warnings)
    # The residual itself is an exact zero in every shipped configuration, so
    # there is nothing for a warning to describe. Asserted on the value too,
    # so an edit that makes the residual nonzero fails here rather than
    # silently making the absence assertion vacuous.
    assert _number(_values_of(_construct()), "net_duration_residual") == 0.0


def test_the_confidence_comes_from_the_config_calibration_status() -> None:
    """0.7, derived -- never asserted (Section 22.8).

    The leaves are ``mechanical_rule``, so they are not
    ``uncalibrated_illustrative`` and no heuristic penalty applies. The point
    of the test is that changing the config status moves this number without
    any edit to the function.
    """
    result = _construct()
    settings = get_settings()
    assert settings.curve_trade.breakeven_duration_ratio_min.calibration_status == (
        "mechanical_rule"
    )
    assert result.confidence == pytest.approx(0.7)


def test_the_value_is_a_dict_not_a_scalar() -> None:
    """The shape contract: this function publishes a structure, not a number."""
    assert isinstance(_construct().value, dict)


def test_inputs_used_lists_the_four_real_inputs() -> None:
    """Assert against the FIXTURE's own values, never a mutant's output (D-051)."""
    assert _construct().inputs_used == [
        "tenor",
        "tips_duration",
        "nominal_duration",
        "target_notional_tips",
    ]


def test_the_interpretation_names_both_legs_at_the_shared_tenor() -> None:
    """Both legs are the same maturity, and the wording must say so.

    A reader who sees two notionals with no tenor on the short leg could take
    them for different maturities.
    """
    text = _construct().interpretation
    assert text.count("10y") == 2
    assert "1,125,480.85" in text
