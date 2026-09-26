"""Hand-verified tests for ``cip_check`` — Module 9, Section 6.7.

What is derived here, not observed
----------------------------------
Every expected value below is computed from the parity identity in the test, on
numbers chosen so the arithmetic is exact or checkable by hand:

* ``F_implied = S * (1 + i_d) / (1 + i_f)`` on the PERIOD rates.
* ``deviation_pct = (F - F_implied) / F_implied * 100``.
* The synthetic domestic funding rate ``(F / S) * (1 + i_f) - 1``, and the
  basis ``(i_d_synthetic - i_d)`` — which satisfies the exact identity
  ``basis_period == (1 + i_d_period) * deviation_fraction``.

The identity is asserted between two PUBLISHED keys, not between a key and
itself: ``domestic_funding_basis_bp_annualized`` is derived through the
synthetic-rate route while ``deviation_pct`` is derived through the ratio
route, so the two must agree (lesson 5co).

Every guard gets a test with a NEGATIVE CONTROL — the same fixture with the
defective field replaced by a legal value — so a passing test cannot be
explained by the rest of the fixture, and a guard that refused everything would
fail the control.
"""

from __future__ import annotations

import math
from typing import get_args

import pytest
from pydantic import ValidationError

from macro_engine.config import CalibratedValue, FxCarrySettings, get_settings
from macro_engine.models.contracts import ConfidenceInputs, ModelResult, compute_confidence
from macro_engine.models.fx_carry import (
    _BASIS_DAYS,
    CIPInputs,
    DayCountBasis,
    FundingStressSide,
    QuoteConvention,
    StressSeverity,
    _cip_bands_are_calibrated,
    cip_check,
)
from tests.helpers import as_float, as_str

# ---------------------------------------------------------------------------
# The hand-computed baseline. S = 1.10 USD per EUR, F = 1.11, 90 days ACT/360.
#
#   i_domestic_period = 0.04 * 90/360 = 0.010
#   i_foreign_period  = 0.02 * 90/360 = 0.005
#   F_implied         = 1.10 * 1.010 / 1.005 = 1.1054726368159204
#   deviation         = (1.11 - F_implied) / F_implied = +0.00409540...
#   i_d_synthetic     = (1.11 / 1.10) * 1.005 - 1 = 0.0141363636...
#   basis_period      = 0.0141363636 - 0.010 = 0.0041363636...
#   basis_bp_annual   = 0.0041363636 * (360/90) * 10000 = 165.4545...
# ---------------------------------------------------------------------------

_SPOT = 1.10
_FORWARD = 1.11
_I_DOMESTIC = 0.04
_I_FOREIGN = 0.02
_TENOR = 90
_BASIS_DAYS_IN_YEAR = 360.0

_IMPLIED_FORWARD = (
    _SPOT
    * (1.0 + _I_DOMESTIC * _TENOR / _BASIS_DAYS_IN_YEAR)
    / (1.0 + _I_FOREIGN * _TENOR / _BASIS_DAYS_IN_YEAR)
)
_DEVIATION_PCT = (_FORWARD - _IMPLIED_FORWARD) / _IMPLIED_FORWARD * 100.0
_I_D_PERIOD = _I_DOMESTIC * _TENOR / _BASIS_DAYS_IN_YEAR
_SYNTHETIC_PERIOD = (_FORWARD / _SPOT) * (1.0 + _I_FOREIGN * _TENOR / _BASIS_DAYS_IN_YEAR) - 1.0
_BASIS_BP = (_SYNTHETIC_PERIOD - _I_D_PERIOD) * (_BASIS_DAYS_IN_YEAR / _TENOR) * 10_000.0

#: The published rates and the implied forward are rounded to 8 decimal places,
#: so an assertion against the exact arithmetic must allow half a unit in the
#: last place. A tolerance tighter than this tests the rounding, not the maths.
_PUBLISHED_8DP = 1e-8


def _inputs(**overrides: object) -> CIPInputs:
    """The baseline swap, with any field overridden.

    Explicit keywords rather than a splatted dict so ``mypy --strict`` checks
    each argument against its own field type.
    """
    base: dict[str, object] = {
        "spot": _SPOT,
        "forward": _FORWARD,
        "i_domestic_annualized": _I_DOMESTIC,
        "i_foreign_annualized": _I_FOREIGN,
        "tenor_days": _TENOR,
    }
    base.update(overrides)
    return CIPInputs.model_validate(base)


def _value(result: ModelResult) -> dict[str, object]:
    value = result.value
    assert isinstance(value, dict)
    return value


def _number(result: ModelResult, key: str) -> float:
    return as_float(result, key=key)


def _label(result: ModelResult, key: str) -> str:
    return as_str(result, key=key)


# ---------------------------------------------------------------------------
# The arithmetic, checked against the derivation above.
# ---------------------------------------------------------------------------


def test_the_implied_forward_matches_the_parity_identity() -> None:
    """The published implied forward must equal S(1+i_d)/(1+i_f) on PERIOD rates."""
    assert _number(cip_check(_inputs()), "implied_forward") == pytest.approx(
        _IMPLIED_FORWARD, abs=_PUBLISHED_8DP
    )


def test_the_deviation_matches_the_hand_computation() -> None:
    """0.4095%, computed by hand above from the parity identity."""
    deviation = _number(cip_check(_inputs()), "deviation_pct")
    assert deviation == pytest.approx(_DEVIATION_PCT, abs=1e-6)
    assert pytest.approx(0.409540, abs=1e-6) == _DEVIATION_PCT


def test_the_period_rates_are_the_annualised_rates_scaled_by_the_tenor() -> None:
    """The conversion is the whole reason ``tenor_days`` and the basis exist."""
    result = cip_check(_inputs())
    assert _number(result, "i_domestic_period") == pytest.approx(0.010, rel=1e-12)
    assert _number(result, "i_foreign_period") == pytest.approx(0.005, rel=1e-12)
    assert _value(result)["day_count_basis_days"] == 360


def test_the_synthetic_domestic_rate_and_basis_match_the_hand_computation() -> None:
    """The basis is derived through the OTHER side of the identity."""
    result = cip_check(_inputs())
    assert _number(result, "synthetic_domestic_funding_rate_period") == pytest.approx(
        _SYNTHETIC_PERIOD, abs=_PUBLISHED_8DP
    )
    assert _number(result, "domestic_funding_basis_bp_annualized") == pytest.approx(
        _BASIS_BP, abs=1e-4
    )
    assert pytest.approx(165.454545, rel=1e-8) == _BASIS_BP


def test_the_published_keys_satisfy_the_exact_basis_identity() -> None:
    """``basis_period == (1 + i_d_period) * deviation_fraction``, between PUBLISHED keys.

    This is the check that ties the two derivations together: the deviation is
    computed from the ratio ``F / F_implied`` and the basis from the synthetic
    rate ``(F / S)(1 + i_f)``, so a mutation that breaks either route cannot
    satisfy the relation. Both published numbers are rounded (6dp on the
    percentage, 4dp on the basis points), so the tolerance is derived rather
    than convenient: the rounding contributes at most ~1.3e-4 relative here,
    while a wrong formula is off by orders of magnitude.
    """
    result = cip_check(_inputs())
    tenor = int(_number(result, "tenor_days"))
    basis_days = int(_number(result, "day_count_basis_days"))
    basis_period = (
        _number(result, "domestic_funding_basis_bp_annualized") / 10_000.0 * (tenor / basis_days)
    )
    assert basis_period == pytest.approx(
        (1.0 + _number(result, "i_domestic_period")) * (_number(result, "deviation_pct") / 100.0),
        rel=1e-3,
    )


def test_the_identity_holds_on_the_extreme_case_too() -> None:
    """The identity is a property of the algebra, not of one quiet fixture."""
    result = cip_check(_inputs(forward=1.12))
    tenor = int(_number(result, "tenor_days"))
    basis_days = int(_number(result, "day_count_basis_days"))
    basis_period = (
        _number(result, "domestic_funding_basis_bp_annualized") / 10_000.0 * (tenor / basis_days)
    )
    assert basis_period == pytest.approx(
        (1.0 + _number(result, "i_domestic_period")) * (_number(result, "deviation_pct") / 100.0),
        rel=1e-3,
    )
    assert _label(result, "severity") == "extreme"


# ---------------------------------------------------------------------------
# The SIGN — the derivation's whole point.
# ---------------------------------------------------------------------------


def test_positive_deviation_means_domestic_funding_is_the_expensive_side() -> None:
    """F above parity => synthetic domestic rate above actual => domestic stress.

    Derived, not recalled: ``i_d_synthetic - i_d = (1 + i_d) * dev`` exactly, so
    the sign of the deviation IS the sign of the synthetic-minus-actual spread.
    """
    result = cip_check(_inputs())
    assert _number(result, "deviation_pct") > 0.0
    assert _number(result, "synthetic_domestic_funding_rate_period") > _number(
        result, "i_domestic_period"
    )
    assert _label(result, "stressed_currency") == "domestic"
    assert result.direction == "domestic_funding_stress"


def test_negative_deviation_means_foreign_funding_is_the_expensive_side() -> None:
    """The mirror case, so the sign rule is not one-sided (D-045a's discipline)."""
    result = cip_check(_inputs(forward=1.10))
    assert _number(result, "deviation_pct") < 0.0
    assert _number(result, "synthetic_domestic_funding_rate_period") < _number(
        result, "i_domestic_period"
    )
    assert _label(result, "stressed_currency") == "foreign"
    assert result.direction == "foreign_funding_stress"


def test_the_basis_and_the_deviation_always_share_a_sign() -> None:
    """Both are positive iff the forward sits above parity — a cross-check."""
    for forward in (1.05, 1.10, 1.11, 1.20):
        result = cip_check(_inputs(forward=forward))
        deviation = _number(result, "deviation_pct")
        basis = _number(result, "domestic_funding_basis_bp_annualized")
        assert math.copysign(1.0, deviation) == math.copysign(1.0, basis), (
            f"forward {forward}: deviation {deviation} and basis {basis} disagree in sign"
        )


def test_a_forward_exactly_at_parity_has_no_deviation_and_no_basis() -> None:
    """The limiting case: F = F_implied must give exactly zero on both routes."""
    result = cip_check(_inputs(forward=_IMPLIED_FORWARD))
    assert _number(result, "deviation_pct") == pytest.approx(0.0, abs=1e-9)
    assert _number(result, "domestic_funding_basis_bp_annualized") == pytest.approx(0.0, abs=1e-6)
    assert _label(result, "severity") == "none"
    assert _label(result, "stressed_currency") == "none"
    assert result.warnings == []


def test_equal_rates_imply_a_forward_equal_to_spot() -> None:
    """With i_d == i_f the parity forward collapses to the spot rate."""
    result = cip_check(_inputs(i_domestic_annualized=0.03, i_foreign_annualized=0.03))
    assert _number(result, "implied_forward") == pytest.approx(_SPOT, rel=1e-12)


# ---------------------------------------------------------------------------
# The quote convention — the silent sign inversion.
# ---------------------------------------------------------------------------


def test_the_same_swap_in_either_quote_convention_gives_the_same_deviation() -> None:
    """A USDJPY-style quote is inverted, not read as if it were EURUSD-style.

    The two fixtures describe ONE economic swap: 1.10 and 1.11 domestic per
    foreign is the same statement as 1/1.10 and 1/1.11 foreign per domestic.
    A function that applied the parity identity to the raw numbers would return
    a different deviation for the second.
    """
    direct = cip_check(_inputs(quote="domestic_per_foreign"))
    inverted = cip_check(
        _inputs(quote="foreign_per_domestic", spot=1.0 / _SPOT, forward=1.0 / _FORWARD)
    )
    assert _number(inverted, "deviation_pct") == pytest.approx(
        _number(direct, "deviation_pct"), rel=1e-9
    )
    assert _number(inverted, "implied_forward") == pytest.approx(
        _number(direct, "implied_forward"), rel=1e-9
    )
    assert _value(inverted)["quote_was_inverted"] is True
    assert _value(direct)["quote_was_inverted"] is False
    assert _label(inverted, "quote_convention") == "foreign_per_domestic"
    assert _label(inverted, "normalized_to") == "domestic_per_foreign"


def test_the_two_conventions_differ_observably_on_the_same_raw_numbers() -> None:
    """The negative control for the convention test, with the damage quantified.

    The identical raw pair read under the two labels must give different
    answers — which is what makes the convention an input rather than a
    convention. If the branch were ignored, these two would be equal.
    """
    as_domestic_per_foreign = cip_check(_inputs(quote="domestic_per_foreign"))
    as_foreign_per_domestic = cip_check(_inputs(quote="foreign_per_domestic"))
    assert _number(as_domestic_per_foreign, "deviation_pct") > 0.0
    assert _number(as_foreign_per_domestic, "deviation_pct") < 0.0
    assert _value(as_foreign_per_domestic)["quote_was_inverted"] is True


# ---------------------------------------------------------------------------
# The day-count basis.
# ---------------------------------------------------------------------------


def test_the_basis_length_is_read_from_the_convention() -> None:
    """ACT/365 shortens the period rate, so the implied forward moves."""
    actual_360 = cip_check(_inputs(day_count_basis="actual_360"))
    actual_365 = cip_check(_inputs(day_count_basis="actual_365"))
    assert _value(actual_360)["day_count_basis_days"] == 360
    assert _value(actual_365)["day_count_basis_days"] == 365
    assert _number(actual_360, "i_domestic_period") == pytest.approx(
        0.04 * 90 / 360, abs=_PUBLISHED_8DP
    )
    assert _number(actual_365, "i_domestic_period") == pytest.approx(
        0.04 * 90 / 365, abs=_PUBLISHED_8DP
    )
    assert _number(actual_365, "deviation_pct") != pytest.approx(
        _number(actual_360, "deviation_pct"), rel=1e-6
    )


def test_every_declared_basis_has_a_year_length() -> None:
    """The module's own import-time guard, asserted from the test side too.

    ``get_args`` reads the TYPE, so a member added to the ``Literal`` without a
    ``_BASIS_DAYS`` entry fails here rather than KeyErroring inside the function
    on the first call that selects it.
    """
    assert set(get_args(DayCountBasis)) == set(_BASIS_DAYS)
    assert _BASIS_DAYS == {"actual_360": 360, "actual_365": 365}


# ---------------------------------------------------------------------------
# The configured bands: boundaries exact by construction, and both read.
# ---------------------------------------------------------------------------


def test_a_deviation_exactly_on_the_notable_band_is_still_quiet() -> None:
    """Section 6.7 compares with ``>``, so a deviation equal to the band is INSIDE it.

    The fixture is exact rather than approximate: spot 1.0, both rates 0, and a
    forward of 1.0625 — 2**-4, so ``forward - spot`` is exact in binary — give a
    deviation of exactly 6.25%. The band is patched to 6.25, so a ``>`` versus
    ``>=`` change is observable.
    """
    settings = get_settings()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(settings.fx_carry.notable_deviation_pct, "value", 6.25, raising=False)
        patch.setattr(settings.fx_carry.extreme_deviation_pct, "value", 50.0, raising=False)
        result = cip_check(
            _inputs(spot=1.0, forward=1.0625, i_domestic_annualized=0.0, i_foreign_annualized=0.0)
        )
    assert _number(result, "deviation_pct") == 6.25
    assert _label(result, "severity") == "none"
    assert _label(result, "stressed_currency") == "none"
    assert result.warnings == []


def test_a_deviation_just_above_the_notable_band_is_notable() -> None:
    """The other side of the same boundary, so the band is not merely permissive."""
    settings = get_settings()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(settings.fx_carry.notable_deviation_pct, "value", 6.25, raising=False)
        patch.setattr(settings.fx_carry.extreme_deviation_pct, "value", 50.0, raising=False)
        result = cip_check(
            _inputs(
                spot=1.0, forward=1.0625001, i_domestic_annualized=0.0, i_foreign_annualized=0.0
            )
        )
    assert _number(result, "deviation_pct") > 6.25
    assert _label(result, "severity") == "notable"
    assert _label(result, "stressed_currency") == "domestic"


def test_a_deviation_exactly_on_the_extreme_band_is_only_notable() -> None:
    """The second boundary, exact by the same construction."""
    settings = get_settings()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(settings.fx_carry.notable_deviation_pct, "value", 0.1, raising=False)
        patch.setattr(settings.fx_carry.extreme_deviation_pct, "value", 6.25, raising=False)
        result = cip_check(
            _inputs(spot=1.0, forward=1.0625, i_domestic_annualized=0.0, i_foreign_annualized=0.0)
        )
    assert _number(result, "deviation_pct") == 6.25
    assert _label(result, "severity") == "notable"


def test_a_deviation_just_above_the_extreme_band_is_extreme() -> None:
    settings = get_settings()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(settings.fx_carry.notable_deviation_pct, "value", 0.1, raising=False)
        patch.setattr(settings.fx_carry.extreme_deviation_pct, "value", 6.25, raising=False)
        result = cip_check(
            _inputs(
                spot=1.0, forward=1.0625001, i_domestic_annualized=0.0, i_foreign_annualized=0.0
            )
        )
    assert _number(result, "deviation_pct") > 6.25
    assert _label(result, "severity") == "extreme"


def test_moving_the_notable_band_moves_the_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    """The band is READ, not a literal: a test asserting the shipped value cannot see this.

    A deviation of ~0.41% is "notable" at the shipped 0.1% band. Moving the band
    above it must make the SAME swap quiet, which no hardcoded threshold can do.
    """
    settings = get_settings()
    assert _label(cip_check(_inputs()), "severity") == "notable"
    monkeypatch.setattr(settings.fx_carry.notable_deviation_pct, "value", 5.0, raising=False)
    moved = cip_check(_inputs())
    assert _label(moved, "severity") == "none"
    assert _number(moved, "notable_threshold_pct") == 5.0


def test_moving_the_extreme_band_moves_the_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    """And the extreme band is read independently of the notable one."""
    settings = get_settings()
    monkeypatch.setattr(settings.fx_carry.extreme_deviation_pct, "value", 0.2, raising=False)
    moved = cip_check(_inputs())
    assert _label(moved, "severity") == "extreme"
    assert _number(moved, "extreme_threshold_pct") == 0.2


# ---------------------------------------------------------------------------
# Every declared vocabulary member is producible, and every produced value is a
# member (Section 21's two halves of a Literal).
# ---------------------------------------------------------------------------

#: forward = 1.10547264 sits at parity to 8dp; 1.11 and 1.10 sit either side.
_QUIET = {"forward": 1.10547264}
_NOTABLE_UP = {"forward": 1.11}
_NOTABLE_DOWN = {"forward": 1.10}
_EXTREME = {"forward": 1.20}


def test_every_declared_severity_is_producible() -> None:
    assert set(get_args(StressSeverity)) == {"none", "notable", "extreme"}
    produced = {
        _label(cip_check(_inputs(**_QUIET)), "severity"),
        _label(cip_check(_inputs(**_NOTABLE_UP)), "severity"),
        _label(cip_check(_inputs(**_EXTREME)), "severity"),
    }
    assert produced == {"none", "notable", "extreme"}


def test_every_declared_funding_side_is_producible() -> None:
    assert set(get_args(FundingStressSide)) == {"domestic", "foreign", "none"}
    produced = {
        _label(cip_check(_inputs(**_QUIET)), "stressed_currency"),
        _label(cip_check(_inputs(**_NOTABLE_UP)), "stressed_currency"),
        _label(cip_check(_inputs(**_NOTABLE_DOWN)), "stressed_currency"),
    }
    assert produced == {"domestic", "foreign", "none"}


def test_every_declared_quote_convention_is_producible() -> None:
    assert set(get_args(QuoteConvention)) == {"domestic_per_foreign", "foreign_per_domestic"}
    produced = {
        _label(cip_check(_inputs()), "quote_convention"),
        _label(
            cip_check(_inputs(quote="foreign_per_domestic", spot=1 / _SPOT, forward=1 / _FORWARD)),
            "quote_convention",
        ),
    }
    assert produced == {"domestic_per_foreign", "foreign_per_domestic"}


def test_every_produced_severity_is_a_declared_member() -> None:
    """The other half: a value assertion against the type's own member set."""
    for override in (_QUIET, _NOTABLE_UP, _NOTABLE_DOWN, _EXTREME):
        result = cip_check(_inputs(**override))
        assert _label(result, "severity") in get_args(StressSeverity)
        assert _label(result, "stressed_currency") in get_args(FundingStressSide)
        assert _label(result, "quote_convention") in get_args(QuoteConvention)
        assert _label(result, "day_count_basis") in get_args(DayCountBasis)


# ---------------------------------------------------------------------------
# The warnings: conditions of this run, and nothing when there is no condition.
# ---------------------------------------------------------------------------


def test_the_ordinary_case_emits_no_deviation_warning() -> None:
    """A warning that fires on every call is noise, and noise mutes a real one."""
    assert cip_check(_inputs(**_QUIET)).warnings == []


def test_the_notable_case_emits_exactly_one_warning_naming_the_band() -> None:
    warnings = cip_check(_inputs(**_NOTABLE_UP)).warnings
    assert len(warnings) == 1
    assert "notable band" in warnings[0]
    assert "domestic" in warnings[0]


def test_the_extreme_case_emits_exactly_one_warning_naming_the_band() -> None:
    warnings = cip_check(_inputs(**_EXTREME)).warnings
    assert len(warnings) == 1
    assert "extreme band" in warnings[0]


def test_every_warning_branch_is_reached_by_some_fixture() -> None:
    """Enumerate the branches the function can emit and prove each is triggered.

    Without this, a new warning branch can ship with no test and be deleted
    without anything noticing (Section 21.2 Step 5).
    """
    quiet = cip_check(_inputs(**_QUIET)).warnings
    notable = cip_check(_inputs(**_NOTABLE_UP)).warnings
    extreme = cip_check(_inputs(**_EXTREME)).warnings
    assert quiet == []
    assert len(notable) == 1
    assert len(extreme) == 1
    # The extreme warning must not be the notable warning under another name.
    assert notable[0] != extreme[0]


# ---------------------------------------------------------------------------
# Confidence: computed, and by its discriminating property.
# ---------------------------------------------------------------------------


def test_confidence_is_the_heuristic_penalised_value_not_the_spec_literal() -> None:
    """Section 6.7 hardcodes ``confidence=0.7``; Section 22.8 forbids that.

    The bands are uncalibrated, so the heuristic penalty applies. The assertion
    is against ``compute_confidence`` itself — the discriminating property — and
    it must DIFFER from the specification's literal, which is the whole point.
    """
    result = cip_check(_inputs())
    expected = compute_confidence(
        ConfidenceInputs(is_heuristic_not_calibrated=True, source_independence_count=0)
    )
    assert result.confidence == pytest.approx(expected)
    assert result.confidence != pytest.approx(0.7)
    assert result.confidence < get_settings().confidence.base.value


def test_the_confidence_helper_reads_the_bands_it_names() -> None:
    """Both band leaves are uncalibrated today, so the penalty applies."""
    settings = get_settings()
    assert settings.is_calibrated("fx_carry.notable_deviation_pct") is False
    assert settings.is_calibrated("fx_carry.extreme_deviation_pct") is False


def test_the_confidence_helper_reads_the_notable_leaf_specifically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The helper must read the NOTABLE leaf, not whichever band is handy.

    Today both leaves carry the same calibration status, so a helper pointed at
    the wrong one returns the same answer — an equivalence that would evaporate
    the moment one band was calibrated and not the other. Moving each leaf's
    status in turn is what separates "reads the notable leaf" from "reads an
    uncalibrated leaf", and it is the only fixture that can see the difference.
    """
    fx = get_settings().fx_carry
    monkeypatch.setattr(
        fx.notable_deviation_pct, "calibration_status", "conventional", raising=False
    )
    assert _cip_bands_are_calibrated() is True

    monkeypatch.setattr(
        fx.notable_deviation_pct, "calibration_status", "uncalibrated_illustrative", raising=False
    )
    monkeypatch.setattr(
        fx.extreme_deviation_pct, "calibration_status", "conventional", raising=False
    )
    assert _cip_bands_are_calibrated() is False


# ---------------------------------------------------------------------------
# The settings validators: a band pair that cannot express its own vocabulary.
# ---------------------------------------------------------------------------


def _cal(value: float) -> CalibratedValue:
    return CalibratedValue(value=value, calibration_status="conventional")


def _fx_carry_settings(**overrides: CalibratedValue) -> FxCarrySettings:
    """A complete ``FxCarrySettings``, so a guard test exercises its own guard.

    Every construction is COMPLETE on purpose. These tests used to build the
    model with only the two band fields, and adding the required
    ``carry_vol_floor`` at D-109 made them raise ``ValidationError`` for a
    missing field instead — which the two ``pytest.raises`` tests happily
    accepted, because a missing required field and a rejected band are the SAME
    exception type. **Only the negative control failed**, which is the whole
    argument for having one. See the ``match=`` arguments below for the second
    half of the fix.

    **D-110 fired the identical trap a second time**: two more required fields
    (``dollar_smile_vix_threshold``, ``dollar_smile_sign_boundary``) were added
    to the same settings model, and this helper went stale again. The lesson is
    that "complete on purpose" has to be maintained against the model, not
    asserted once — which is why every field below is spelled out and why a
    third occurrence should be met by reading the model rather than by guessing.

    **D-112 fired it a THIRD time**, exactly as the sentence above predicted:
    ``uip_reliability_cap`` was added and this helper went stale again. The
    prediction was right and the helper was still fixed by editing rather than by
    generating — so the standing conclusion is that this helper is a
    **maintenance point**, and the remedy at the fourth occurrence is to build it
    from the model's own fields (``FxCarrySettings.model_fields``) rather than to
    hand-list them a fourth time.

    **D-114 is that fourth occurrence**, and the remedy above was applied rather
    than hand-listing again: ``ppp_reliability_cap`` and
    ``ppp_tactical_horizon_years`` were both added, and the base is now seeded
    from the SHIPPED ``fx_carry`` block. Every field the model requires is
    present by construction, so a future required field can no longer silently
    turn a guard test into a tautology — which is the failure this helper was
    written to prevent in the first place.

    The seeding is safe because the shipped leaf VALUES never matter to these
    tests: each ``pytest.raises`` case below overrides exactly the field under
    test, and the negative control reads only whether construction *succeeds*.
    """
    base: dict[str, CalibratedValue] = dict(get_settings().fx_carry)
    base.update(overrides)
    return FxCarrySettings(**base)


def test_the_band_validator_refuses_a_non_positive_notable_band() -> None:
    """A zero band makes every deviation notable, so 'none' is unreachable.

    ``match=`` names the field so the test cannot pass on an unrelated
    ``ValidationError`` — a missing required field raises the same type and
    would otherwise satisfy a bare ``pytest.raises``.
    """
    with pytest.raises(ValidationError, match="notable_deviation_pct"):
        _fx_carry_settings(notable_deviation_pct=_cal(0.0))


def test_the_band_validator_refuses_an_extreme_band_at_or_below_the_notable_one() -> None:
    """An empty middle band makes the 'notable' label dead vocabulary (D-037)."""
    with pytest.raises(ValidationError, match="extreme_deviation_pct"):
        _fx_carry_settings(notable_deviation_pct=_cal(1.0), extreme_deviation_pct=_cal(1.0))
    with pytest.raises(ValidationError, match="extreme_deviation_pct"):
        _fx_carry_settings(notable_deviation_pct=_cal(1.0), extreme_deviation_pct=_cal(0.5))


def test_the_band_validator_accepts_a_strictly_ordered_pair() -> None:
    """The negative control: an ordinary ordered pair must construct."""
    settings = _fx_carry_settings()
    assert settings.notable_threshold_pct == 0.1
    assert settings.extreme_threshold_pct == 0.5


# ---------------------------------------------------------------------------
# The reasoning contract: every disclosure field populated on every call.
# ---------------------------------------------------------------------------


def test_the_result_carries_the_module_contract() -> None:
    result = cip_check(_inputs())
    assert result.model_name == "cip_deviation"
    assert result.country == "us"
    assert result.unit == "percent"
    assert result.limitations, "limitations must be present on every call"
    assert result.assumptions, "assumptions must be present on every call"
    assert result.decision_prohibition, "prohibitions must be present on every call"
    assert result.decision_relevance is not None
    assert set(result.inputs_used) == {
        "spot",
        "forward",
        "i_domestic_annualized",
        "i_foreign_annualized",
        "tenor_days",
        "day_count_basis",
        "quote",
    }


def test_the_limitations_name_the_unmodelled_costs() -> None:
    """The three caveats that make a non-zero deviation not a trade."""
    joined = " ".join(cip_check(_inputs()).limitations).lower()
    assert "bid/ask" in joined
    assert "settlement" in joined
    assert "balance-sheet" in joined


def test_the_prohibitions_forbid_treating_the_deviation_as_an_arbitrage() -> None:
    joined = " ".join(cip_check(_inputs()).decision_prohibition).lower()
    assert "arbitrage" in joined


# ---------------------------------------------------------------------------
# The domain guards, each with an explicit negative control.
# ---------------------------------------------------------------------------

#: (label, the defective override, the legal value that replaces it)
_GUARD_CASES: tuple[tuple[str, dict[str, object], dict[str, object]], ...] = (
    ("spot is zero", {"spot": 0.0}, {"spot": 1.10}),
    ("spot is negative", {"spot": -1.0}, {"spot": 1.10}),
    ("forward is zero", {"forward": 0.0}, {"forward": 1.11}),
    ("spot is nan", {"spot": float("nan")}, {"spot": 1.10}),
    ("forward is inf", {"forward": float("inf")}, {"forward": 1.11}),
    (
        "domestic rate is nan",
        {"i_domestic_annualized": float("nan")},
        {"i_domestic_annualized": 0.04},
    ),
    (
        "foreign rate is -inf",
        {"i_foreign_annualized": float("-inf")},
        {"i_foreign_annualized": 0.02},
    ),
    ("tenor exceeds the basis year", {"tenor_days": 361}, {"tenor_days": 360}),
    (
        "period domestic rate below -100%",
        {"i_domestic_annualized": -5.0, "tenor_days": 360},
        {"i_domestic_annualized": 0.04},
    ),
    (
        "period foreign rate below -100%",
        {"i_foreign_annualized": -5.0, "tenor_days": 360},
        {"i_foreign_annualized": 0.02},
    ),
)

_GUARD_IDS = [case[0] for case in _GUARD_CASES]


@pytest.mark.parametrize(("label", "defective", "control"), _GUARD_CASES, ids=_GUARD_IDS)
def test_the_domain_guards_refuse(
    label: str, defective: dict[str, object], control: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        _inputs(**defective)


@pytest.mark.parametrize(("label", "defective", "control"), _GUARD_CASES, ids=_GUARD_IDS)
def test_the_negative_control_for_each_guard_is_accepted(
    label: str, defective: dict[str, object], control: dict[str, object]
) -> None:
    """The same fixture with the defective field replaced by a legal value.

    Without this, a guard that refused everything would pass the test above.
    """
    legal = {**defective, **control}
    assert isinstance(cip_check(_inputs(**legal)), ModelResult)


def test_a_tenor_of_exactly_the_basis_year_is_accepted() -> None:
    """The boundary of the tenor guard: 360 days on ACT/360 is exactly one year."""
    result = cip_check(_inputs(tenor_days=360))
    assert _number(result, "i_domestic_period") == pytest.approx(0.04, rel=1e-12)


def test_a_tenor_of_one_day_is_accepted() -> None:
    """The other boundary of the same guard."""
    assert _value(cip_check(_inputs(tenor_days=1)))["tenor_days"] == 1


def test_a_zero_tenor_is_refused_by_the_field_bound() -> None:
    with pytest.raises(ValidationError):
        _inputs(tenor_days=0)


def test_a_period_rate_exactly_at_the_boundary_is_refused_and_just_inside_accepted() -> None:
    """The guard sits on ``1 + i == 0``; both sides are asserted.

    At ``-100%`` over the period ``1 + i`` is exactly zero, so the parity ratio
    would divide by zero. Just inside it, the computation is legal.
    """
    with pytest.raises(ValidationError):
        _inputs(i_domestic_annualized=-1.0, tenor_days=360)
    accepted = cip_check(_inputs(i_domestic_annualized=-0.99, tenor_days=360))
    assert _number(accepted, "i_domestic_period") == pytest.approx(-0.99, rel=1e-12)


def test_an_unknown_quote_convention_is_refused() -> None:
    with pytest.raises(ValidationError):
        _inputs(quote="domestic-per-foreign")


def test_an_unknown_day_count_basis_is_refused() -> None:
    with pytest.raises(ValidationError):
        _inputs(day_count_basis="actual_364")


def test_an_extra_field_is_refused() -> None:
    with pytest.raises(ValidationError):
        _inputs(notional=1_000_000.0)
