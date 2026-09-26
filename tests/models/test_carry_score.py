"""Hand-verified tests for ``carry_score`` — Module 9, Section 6.7.

What is derived here, not observed
----------------------------------
The score is ``rate_differential_annualized / max(realized_vol_annualized,
floor)``. Every expected value below is computed from that definition in the
test, on numbers whose arithmetic is checkable by hand, and the identities the
implementation claims are asserted as identities:

* ``score == rate_differential / effective_denominator`` recomputed from the
  PUBLISHED keys, so a wrong denominator cannot survive;
* ``sign(score) == sign(rate_differential)``, because the denominator is
  strictly positive by construction;
* ``score == 0`` exactly when the differential is zero.

The floor boundary is built by **exact float stepping** (``math.nextafter``)
rather than by subtraction: the configured floor is not a binary-exact number,
so ``floor - 1e-17`` is not one ULP below it and would test the wrong side.

**The confidence coincidence, recorded rather than hidden.** Section 6.7
hardcodes ``confidence=0.5``, and the correctly-computed value is ALSO 0.50
today (base 0.7 minus the 0.20 heuristic penalty, both bands uncalibrated). A
test asserting ``confidence == 0.5`` therefore cannot tell a hardcoded literal
from the computed one — D-050's trap in its purest form. The confidence tests
below assert against ``compute_confidence`` and against a PERTURBED base
instead, so a literal fails them.
"""

from __future__ import annotations

import math
from typing import get_args

import pytest
from pydantic import ValidationError

from macro_engine.config import CalibratedValue, FxCarrySettings, get_settings
from macro_engine.models.contracts import (
    ConfidenceInputs,
    EvidenceSourceFamily,
    ModelResult,
    compute_confidence,
)
from macro_engine.models.fx_carry import (
    CarryOutcome,
    CarryScoreInputs,
    _carry_floor_is_calibrated,
    carry_score,
)
from tests.helpers import as_bool, as_float, as_str

# ---------------------------------------------------------------------------
# The hand-computed baseline. The shipped floor is 0.1 (an annualised decimal,
# i.e. 10%/yr), so case A is written to BIND and case B to clear it.
# ---------------------------------------------------------------------------

#: (label, differential, vol, expected score, expected denominator, binds)
_CASES: tuple[tuple[str, float, float, float, float, bool], ...] = (
    ("floor binds", 0.02, 0.08, 0.02 / 0.10, 0.10, True),
    ("floor clears", 0.03, 0.12, 0.03 / 0.12, 0.12, False),
    ("negative carry", -0.02, 0.15, -0.02 / 0.15, 0.15, False),
    ("zero differential", 0.0, 0.15, 0.0, 0.15, False),
)


def _inputs(**overrides: object) -> CarryScoreInputs:
    base: dict[str, object] = {
        "rate_differential_annualized": 0.02,
        "realized_vol_annualized": 0.08,
    }
    base.update(overrides)
    return CarryScoreInputs.model_validate(base)


def _value(result: ModelResult) -> dict[str, object]:
    value = result.value
    assert isinstance(value, dict)
    return value


def _number(result: ModelResult, key: str) -> float:
    return as_float(result, key=key)


def _label(result: ModelResult, key: str) -> str:
    return as_str(result, key=key)


# ---------------------------------------------------------------------------
# The arithmetic.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "differential", "vol", "expected_score", "expected_denominator", "binds"),
    _CASES,
    ids=[case[0] for case in _CASES],
)
def test_the_score_matches_the_hand_computation(
    label: str,
    differential: float,
    vol: float,
    expected_score: float,
    expected_denominator: float,
    binds: bool,
) -> None:
    result = carry_score(
        _inputs(rate_differential_annualized=differential, realized_vol_annualized=vol)
    )
    assert _number(result, "score") == pytest.approx(expected_score, abs=1e-6)
    assert _number(result, "effective_denominator") == pytest.approx(expected_denominator, abs=1e-9)
    assert _value(result)["volatility_floor_binding"] is binds


def test_the_score_reconciles_against_the_published_components() -> None:
    """``score == differential / effective_denominator``, between PUBLISHED keys.

    The deviation-and-basis check in the sibling file's idiom: the score and the
    denominator are published separately, so a mutation that changed one without
    the other cannot satisfy this.
    """
    for case in _CASES:
        result = carry_score(
            _inputs(rate_differential_annualized=case[1], realized_vol_annualized=case[2])
        )
        assert _number(result, "score") == pytest.approx(
            _number(result, "rate_differential_annualized")
            / _number(result, "effective_denominator"),
            abs=1e-6,
        )


def test_the_score_shares_the_differential_s_sign() -> None:
    """The denominator is strictly positive, so the sign IS the direction.

    Asserted over a grid rather than one fixture, because a mutant that negated
    the denominator would satisfy a single positive case.
    """
    for differential in (-0.05, -0.02, -0.001, 0.001, 0.02, 0.05):
        for vol in (0.05, 0.12, 0.30):
            result = carry_score(
                _inputs(rate_differential_annualized=differential, realized_vol_annualized=vol)
            )
            score = _number(result, "score")
            assert math.copysign(1.0, score) == math.copysign(1.0, differential), (
                f"differential {differential} over vol {vol} gave a score of {score} "
                f"with the opposite sign"
            )


def test_a_zero_differential_gives_exactly_zero_and_the_flat_label() -> None:
    """Zero carry is the ABSENCE of carry, not a small one — its own label."""
    result = carry_score(_inputs(rate_differential_annualized=0.0))
    assert _number(result, "score") == 0.0
    assert _label(result, "carry_outcome") == "flat"
    assert result.direction == "flat"


def test_a_positive_differential_is_long_domestic() -> None:
    """Lend the high-yielding (domestic) leg, borrow the low-yielding one."""
    result = carry_score(_inputs(rate_differential_annualized=0.02))
    assert _label(result, "carry_outcome") == "long_domestic"
    assert result.direction == "long_domestic"


def test_a_negative_differential_is_long_foreign() -> None:
    """The mirror case, so the direction rule is not one-sided (D-045a)."""
    result = carry_score(_inputs(rate_differential_annualized=-0.02))
    assert _label(result, "carry_outcome") == "long_foreign"
    assert result.direction == "long_foreign"


# ---------------------------------------------------------------------------
# The floor: its boundary, its direction, and its disclosure.
# ---------------------------------------------------------------------------


def test_a_volatility_exactly_on_the_floor_does_not_bind() -> None:
    """The comparison is ``vol < floor``, so the floor itself is not below it.

    The fixture is exact: the floor is patched to ``0.125`` (``2**-3``) and the
    volatility is ``0.125`` verbatim, so a ``<`` versus ``<=`` change is
    observable.
    """
    settings = get_settings()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(settings.fx_carry.carry_vol_floor, "value", 0.125, raising=False)
        result = carry_score(_inputs(realized_vol_annualized=0.125))
    assert _value(result)["volatility_floor_binding"] is False
    assert result.warnings == []
    assert _number(result, "effective_denominator") == 0.125


def test_a_volatility_one_ulp_below_the_floor_binds() -> None:
    """The other side of the same boundary, by EXACT float stepping.

    ``math.nextafter(0.125, 0.0)`` is the largest representable double below
    ``0.125``. A fixture built by subtraction (``0.125 - 1e-17``) would round
    back to ``0.125`` and test the wrong side.
    """
    settings = get_settings()
    just_below = math.nextafter(0.125, 0.0)
    assert just_below < 0.125
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(settings.fx_carry.carry_vol_floor, "value", 0.125, raising=False)
        result = carry_score(_inputs(realized_vol_annualized=just_below))
    assert _value(result)["volatility_floor_binding"] is True
    assert len(result.warnings) == 1
    assert _number(result, "effective_denominator") == 0.125


def test_the_floor_caps_the_score_rather_than_inflating_it() -> None:
    """A binding floor makes |score| SMALLER than the un-floored ratio.

    This pins the direction of the floor's effect. A mutant that inverted the
    ``max`` (or divided by the smaller of the two) would make a quiet pair look
    MORE attractive than its own volatility implies, which is the opposite of
    what a denominator floor does.
    """
    differential, vol, floor = 0.02, 0.08, 0.10
    result = carry_score(
        _inputs(rate_differential_annualized=differential, realized_vol_annualized=vol)
    )
    un_floored = differential / vol
    assert _value(result)["volatility_floor_binding"] is True
    assert abs(_number(result, "score")) < abs(un_floored)
    assert _number(result, "score") == pytest.approx(differential / floor, abs=1e-6)


def test_moving_the_floor_moves_the_score(monkeypatch: pytest.MonkeyPatch) -> None:
    """The floor is READ from config, not a literal.

    At the shipped 0.10 the 8 %-vol fixture binds. Raising the floor above the
    volatility keeps it binding but changes the denominator, and lowering it
    below the volatility stops it binding altogether — neither of which a
    hardcoded ``0.1`` can produce.
    """
    settings = get_settings()
    shipped = carry_score(_inputs(realized_vol_annualized=0.08))
    assert _value(shipped)["volatility_floor_binding"] is True

    monkeypatch.setattr(settings.fx_carry.carry_vol_floor, "value", 0.04, raising=False)
    loosened = carry_score(_inputs(realized_vol_annualized=0.08))
    assert _value(loosened)["volatility_floor_binding"] is False
    assert _number(loosened, "effective_denominator") == 0.08

    monkeypatch.setattr(settings.fx_carry.carry_vol_floor, "value", 0.20, raising=False)
    tightened = carry_score(_inputs(realized_vol_annualized=0.08))
    assert _value(tightened)["volatility_floor_binding"] is True
    assert _number(tightened, "effective_denominator") == 0.20


# ---------------------------------------------------------------------------
# The warnings: one branch, and it must fire only when the estimand changes.
# ---------------------------------------------------------------------------


def test_no_warning_when_the_floor_does_not_bind() -> None:
    """A warning that fires on every call is noise, and noise mutes a real one."""
    assert carry_score(_inputs(realized_vol_annualized=0.12)).warnings == []


def test_a_binding_floor_warns_and_names_the_floor() -> None:
    warnings = carry_score(_inputs(realized_vol_annualized=0.08)).warnings
    assert len(warnings) == 1
    assert "FLOOR" in warnings[0]
    assert "carry-to-vol" in warnings[0]


def test_every_warning_branch_is_reached_by_some_fixture() -> None:
    """Enumerate the branches and prove each is triggered by some fixture."""
    quiet = carry_score(_inputs(realized_vol_annualized=0.12)).warnings
    binding = carry_score(_inputs(realized_vol_annualized=0.08)).warnings
    assert quiet == []
    assert len(binding) == 1


# ---------------------------------------------------------------------------
# The declared vocabulary, both halves.
# ---------------------------------------------------------------------------


def test_every_declared_outcome_is_producible() -> None:
    assert set(get_args(CarryOutcome)) == {"long_domestic", "long_foreign", "flat"}
    produced = {
        _label(carry_score(_inputs(rate_differential_annualized=0.02)), "carry_outcome"),
        _label(carry_score(_inputs(rate_differential_annualized=-0.02)), "carry_outcome"),
        _label(carry_score(_inputs(rate_differential_annualized=0.0)), "carry_outcome"),
    }
    assert produced == {"long_domestic", "long_foreign", "flat"}


def test_every_produced_outcome_is_a_declared_member() -> None:
    """A value assertion cannot see a member removed from the TYPE."""
    for differential in (-0.02, 0.0, 0.02):
        result = carry_score(_inputs(rate_differential_annualized=differential))
        assert _label(result, "carry_outcome") in get_args(CarryOutcome)
        assert result.direction in get_args(CarryOutcome)


# ---------------------------------------------------------------------------
# Confidence — computed, and by its discriminating property.
# ---------------------------------------------------------------------------


def test_confidence_is_the_heuristic_penalised_value() -> None:
    """The computed value, NOT the specification's literal.

    ``compute_confidence`` with the penalty applied is 0.50, which is ALSO
    Section 6.7's hardcoded literal — so asserting ``== 0.5`` would pass on a
    hardcoded constant. The discriminating assertion is that the penalised and
    un-penalised values DIFFER, and that a perturbed base moves the result.
    """
    result = carry_score(_inputs())
    penalised = compute_confidence(ConfidenceInputs(is_heuristic_not_calibrated=True))
    unpenalised = compute_confidence(ConfidenceInputs(is_heuristic_not_calibrated=False))
    assert result.confidence == pytest.approx(penalised)
    assert penalised != pytest.approx(unpenalised)


def test_a_perturbed_confidence_base_moves_the_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hardcoded 0.5 cannot follow a moved base. This is what kills it."""
    settings = get_settings()
    monkeypatch.setattr(settings.confidence.base, "value", 0.9, raising=False)
    moved = carry_score(_inputs())
    assert moved.confidence == pytest.approx(0.7)
    assert moved.confidence != pytest.approx(0.5)


def test_the_confidence_helper_reads_the_floor_leaf_specifically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The helper must read the floor, not a neighbouring CIP band.

    Today both leaves carry the same calibration status, so a helper pointed at
    the wrong one returns the same answer — an equivalence that would evaporate
    the moment one was calibrated and not the other. Moving each leaf's status
    in turn is the only fixture that separates the two.
    """
    fx = get_settings().fx_carry
    monkeypatch.setattr(fx.carry_vol_floor, "calibration_status", "conventional", raising=False)
    assert _carry_floor_is_calibrated() is True

    monkeypatch.setattr(
        fx.carry_vol_floor, "calibration_status", "uncalibrated_illustrative", raising=False
    )
    monkeypatch.setattr(
        fx.notable_deviation_pct, "calibration_status", "conventional", raising=False
    )
    assert _carry_floor_is_calibrated() is False


def _fx_carry_settings(**overrides: CalibratedValue) -> FxCarrySettings:
    """A COMPLETE ``FxCarrySettings``, so a guard test exercises its own guard.

    Complete on purpose, and this is D-109's lesson firing again at D-110: these
    tests previously built the model with only the fields each one cared about,
    which means adding a REQUIRED field made every bare construction raise for a
    *missing field* instead — the same exception type as the rejection under
    test. The negative control was the only test that noticed, which is the whole
    argument for having one. Every field the settings model requires is listed
    here, so a future required field breaks THIS helper (loudly, in one place)
    rather than silently turning a guard test into a tautology.

    D-112 is that future: ``uip_reliability_cap`` was added and this helper
    broke here, in one place, exactly as designed. **D-114 added two more leaves**
    (``ppp_reliability_cap``, ``ppp_tactical_horizon_years``) and the base is now
    seeded from the shipped ``fx_carry`` block, so the "one place" is now the
    model itself and this helper cannot go stale at all.

    The shipped VALUES are immaterial here: the guard test below overrides
    ``carry_vol_floor`` and the negative control asserts on its own override.
    """
    base: dict[str, CalibratedValue] = dict(get_settings().fx_carry)
    base.update(overrides)
    return FxCarrySettings(**base)


def test_the_settings_validator_refuses_a_non_positive_floor() -> None:
    """A non-positive denominator floor divides by zero and flips every sign.

    ``match=`` is load-bearing (O-127): without it this test passed for the
    wrong reason from D-110 onward, when two newly-required ``dollar_smile_*``
    fields made every bare construction raise a *missing-field* error. A missing
    required field and a rejected floor are the same exception TYPE, so a bare
    ``pytest.raises`` cannot tell them apart.
    """
    with pytest.raises(ValidationError, match="carry_vol_floor"):
        _fx_carry_settings(
            carry_vol_floor=CalibratedValue(value=0.0, calibration_status="conventional")
        )


def test_the_settings_validator_accepts_a_positive_floor() -> None:
    """The negative control: an ordinary floor must construct."""
    settings = _fx_carry_settings(
        carry_vol_floor=CalibratedValue(value=0.1, calibration_status="conventional")
    )
    assert settings.volatility_floor == 0.1


# ---------------------------------------------------------------------------
# The reasoning contract.
# ---------------------------------------------------------------------------


def test_the_result_carries_the_module_contract() -> None:
    result = carry_score(_inputs())
    assert result.model_name == "carry_score"
    assert result.country == "us"
    assert result.unit is not None and "dimensionless" in result.unit
    assert result.source_family is EvidenceSourceFamily.MARKET_FX
    assert result.limitations, "limitations must be present on every call"
    assert result.assumptions, "assumptions must be present on every call"
    assert result.decision_prohibition, "prohibitions must be present on every call"
    assert result.decision_relevance is not None
    assert set(result.inputs_used) == {
        "rate_differential_annualized",
        "realized_vol_annualized",
    }


def test_the_limitations_name_the_tail_risk() -> None:
    """Section 6.7's own disclosure, which the stub carried as a WARNING.

    It holds on every call, so it is a limitation rather than a condition of
    this run — and the specification's phrase for it is preserved.
    """
    joined = " ".join(carry_score(_inputs()).limitations)
    assert "steamroller" in joined
    assert "TAIL AND CRASH RISK" in joined
    assert "peso problem" in joined


def test_the_prohibitions_forbid_sizing_on_the_score_alone() -> None:
    joined = " ".join(carry_score(_inputs()).decision_prohibition).lower()
    assert "size" in joined
    assert "forecast" in joined
    assert "volatility_floor_binding" in joined


def test_the_context_states_both_units() -> None:
    """The one contract that makes the ratio dimensionless must be visible."""
    context = carry_score(_inputs()).context
    assert "ANNUALISED DECIMALS" in context


# ---------------------------------------------------------------------------
# The domain guards, each with an explicit negative control.
# ---------------------------------------------------------------------------

#: (label, the defective override, the legal value that replaces it)
_GUARD_CASES: tuple[tuple[str, dict[str, object], dict[str, object]], ...] = (
    ("volatility is zero", {"realized_vol_annualized": 0.0}, {"realized_vol_annualized": 0.08}),
    (
        "volatility is negative",
        {"realized_vol_annualized": -0.01},
        {"realized_vol_annualized": 0.08},
    ),
    (
        "volatility is nan",
        {"realized_vol_annualized": float("nan")},
        {"realized_vol_annualized": 0.08},
    ),
    (
        "volatility is inf",
        {"realized_vol_annualized": float("inf")},
        {"realized_vol_annualized": 0.08},
    ),
    (
        "differential is nan",
        {"rate_differential_annualized": float("nan")},
        {"rate_differential_annualized": 0.02},
    ),
    (
        "differential is -inf",
        {"rate_differential_annualized": float("-inf")},
        {"rate_differential_annualized": 0.02},
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
    assert isinstance(carry_score(_inputs(**legal)), ModelResult)


def test_the_smallest_positive_volatility_is_accepted() -> None:
    """The lower boundary of the domain: any positive vol is legal."""
    result = carry_score(_inputs(realized_vol_annualized=math.nextafter(0.0, 1.0)))
    assert _number(result, "effective_denominator") > 0.0
    assert _value(result)["volatility_floor_binding"] is True


def test_an_extra_field_is_refused() -> None:
    with pytest.raises(ValidationError):
        _inputs(notional=1_000_000.0)


def test_the_floor_binding_flag_is_a_real_boolean() -> None:
    """``is True`` / ``is False`` in the other tests is only meaningful if the
    published field is a ``bool`` and not, say, a rounded float — ``bool`` is a
    subclass of ``int``, so a truthiness assertion would accept either."""
    binding = carry_score(_inputs(realized_vol_annualized=0.08))
    quiet = carry_score(_inputs(realized_vol_annualized=0.12))
    assert as_bool(binding, key="volatility_floor_binding") is True
    assert as_bool(quiet, key="volatility_floor_binding") is False
