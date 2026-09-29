"""Unit tests for ``check_rebalancing_drift`` (Module 17.3 / Section 15.18, D-055).

Every expected value is hand-computed in the test that uses it.

Four specification defects are pinned here:

1. A missing instrument silently reads as ``0.0``, conflating "not held" with
   "held at zero risk".
2. An instrument with no budget line is invisible to the spec's targets-first
   scan.
3. The threshold's unit convention (``drift_threshold_pct`` is a **fraction**)
   was unstated.
4. ``>`` makes the threshold non-binding at the boundary.

**A deliberate non-defect is also pinned**: the base-state rule (lesson 5g)
does not apply, because the probe measured a 10.8% trip rate rather than a
modal rebalance.
"""

from __future__ import annotations

from typing import Any, get_args

import pytest

from macro_engine.config import get_settings
from macro_engine.models.contracts import ModelResult
from macro_engine.portfolio.risk_budget import (
    RebalancingOutcome,
    RiskBudgetTarget,
    check_rebalancing_drift,
)

# The fixture used throughout. Hand-checked drift arithmetic:
#   ust2y : target 0.35, actual 0.14 -> signed -0.21, abs 0.21 > 0.10  DRIFTED (under)
#   ust10y: target 0.25, actual 0.17 -> signed -0.08, abs 0.08 <= 0.10          not
#   spx   : target 0.25, actual 0.25 -> signed  0.00, abs 0.00 <= 0.10          not
_TARGETS = [
    RiskBudgetTarget(instrument="ust2y", target_risk_contribution_pct=0.35),
    RiskBudgetTarget(instrument="ust10y", target_risk_contribution_pct=0.25),
    RiskBudgetTarget(instrument="spx", target_risk_contribution_pct=0.25),
]
_CURRENT = {"ust2y": 0.14, "ust10y": 0.17, "spx": 0.25}


def _check(
    current: dict[str, float],
    targets: list[RiskBudgetTarget] | None = None,
    threshold: float | None = None,
) -> ModelResult:
    return check_rebalancing_drift(current, targets if targets is not None else _TARGETS, threshold)


def _values_of(result: ModelResult) -> dict[str, Any]:
    """Narrow a ``ModelResult``'s published ``value`` to a dict for indexing.

    ``ModelResult.value`` is typed as a union (a result may carry a scalar), so
    indexing it requires a narrowing step. The project's operator scripts use a
    bare ``assert isinstance(..., dict)``; here it lives in ONE helper rather
    than at 45 call sites, so a failure says so once and in one place. The
    assertion is not defensive noise -- it is the type system's requirement, and
    it would catch a change that made this function publish a scalar.
    """
    value = result.value
    assert isinstance(value, dict), (
        "check_rebalancing_drift publishes a dict; a scalar would break every "
        "assertion in this file"
    )
    return value


def _values(
    current: dict[str, float],
    targets: list[RiskBudgetTarget] | None = None,
    threshold: float | None = None,
) -> dict[str, Any]:
    """``_check``'s published ``value`` dict, narrowed."""
    return _values_of(_check(current, targets, threshold))


# --------------------------------------------------------------------------
# The core arithmetic, hand-computed.
# --------------------------------------------------------------------------


def test_hand_computed_drift_on_the_three_instrument_fixture() -> None:
    result = _check(_CURRENT)

    assert _values_of(result)["outcome"] == "rebalance"
    assert _values_of(result)["instruments_evaluated"] == 3
    assert _values_of(result)["instruments_drifted"] == 1
    assert _values_of(result)["drifted_instruments"] == ["ust2y"]


def test_the_drifted_row_carries_both_signed_and_absolute_drift() -> None:
    result = _check(_CURRENT)
    (row,) = _values_of(result)["drifted"]

    # ust2y: target 0.35, actual 0.14 -> signed -0.21, abs 0.21, direction under
    assert row["instrument"] == "ust2y"
    assert row["target_risk_contribution"] == pytest.approx(0.35)
    assert row["actual_risk_contribution"] == pytest.approx(0.14)
    assert row["signed_drift"] == pytest.approx(-0.21)
    assert row["abs_drift"] == pytest.approx(0.21)
    assert row["direction"] == "under"


def test_a_position_over_its_budget_reports_direction_over() -> None:
    # spx: target 0.25, actual 0.40 -> signed +0.15 > 0.10 -> over
    result = _check({"ust2y": 0.35, "ust10y": 0.25, "spx": 0.40})

    assert _values_of(result)["drifted_instruments"] == ["spx"]
    assert _values_of(result)["drifted"][0]["direction"] == "over"
    assert _values_of(result)["drifted"][0]["signed_drift"] == pytest.approx(0.15)


def test_every_instrument_on_budget_is_balanced() -> None:
    result = _check({"ust2y": 0.35, "ust10y": 0.25, "spx": 0.25})

    assert _values_of(result)["outcome"] == "balanced"
    assert _values_of(result)["drifted"] == []
    assert _values_of(result)["instruments_drifted"] == 0


def test_the_worst_drift_is_named_in_the_interpretation() -> None:
    # Two drifts: ust2y -0.21 (under), spx +0.15 (over). Worst is ust2y.
    result = _check({"ust2y": 0.14, "ust10y": 0.25, "spx": 0.40})

    assert "ust2y" in result.interpretation
    assert "21.0%" in result.interpretation
    assert _values_of(result)["instruments_drifted"] == 2


# --------------------------------------------------------------------------
# Defect 4: the boundary. Built by ADDITION, not subtraction.
# --------------------------------------------------------------------------


def test_a_drift_exactly_at_the_threshold_does_not_flag() -> None:
    """A TRUE boundary fixture, found by probing which sums are binary-exact.

    **This test replaces an earlier fixture that did not sit on the boundary at
    all.** The original used ``0.25 + 0.10`` and asserted it equalled 0.35
    "exactly"; the sweep proved otherwise. ``0.25 + 0.10 - 0.25`` is
    ``0.09999999999999998`` -- a hair BELOW the threshold -- so the test passed
    for the wrong reason and could not distinguish ``>`` from ``>=``
    (sweep mutation M4.1 survived it). This is lesson 5i's trap in a new place:
    the fixture was built by addition, as the lesson requires, but the addition
    was not exact, and nothing checked.

    A binary-exact pair DOES exist: ``0.225 - 0.125 == 0.10`` exactly. The
    assertion below states the arithmetic BEFORE asserting the behaviour, so the
    fixture's status is checked rather than assumed.
    """
    assert (0.225 - 0.125) == 0.10, "fixture no longer sits ON the boundary"

    targets = [RiskBudgetTarget(instrument="a", target_risk_contribution_pct=0.125)]
    result = check_rebalancing_drift({"a": 0.225}, targets)

    assert _values_of(result)["drifted"] == []
    assert _values_of(result)["outcome"] == "balanced"


def test_a_drift_just_past_the_threshold_flags() -> None:
    result = _check({"ust2y": 0.35, "ust10y": 0.25, "spx": 0.25 + 0.1001})

    assert _values_of(result)["drifted_instruments"] == ["spx"]


def test_the_threshold_boundary_is_strict_not_inclusive() -> None:
    """Pins the ``>`` in the specification. An inclusive change must fail.

    The pair is ``0.225 - 0.125 == 0.10`` (exactly on) versus the same book with
    one ulp added (just over). A ``>=`` implementation flags BOTH; the shipped
    ``>`` flags only the second -- which is what makes this test able to kill
    sweep mutation M4.1.
    """
    targets = [RiskBudgetTarget(instrument="a", target_risk_contribution_pct=0.125)]

    on = check_rebalancing_drift({"a": 0.225}, targets)
    past = check_rebalancing_drift({"a": 0.225 + 1e-9}, targets)

    assert _values_of(on)["outcome"] == "balanced"
    assert _values_of(past)["outcome"] == "rebalance"


# --------------------------------------------------------------------------
# Defect 3: the unit convention.
# --------------------------------------------------------------------------


def test_the_configured_threshold_is_a_fraction_not_a_percent() -> None:
    """The load-bearing unit test: reads the shipped config through the loader."""
    settings = get_settings()
    threshold = settings.risk.rebalancing_drift_threshold

    # Section 15.18's default is 0.10. Read as a percent it would be 0.001.
    assert threshold == pytest.approx(0.10)
    assert 0.0 < threshold <= 1.0


def test_a_percent_scale_threshold_would_trip_on_every_real_drift() -> None:
    """The failure direction: a 0.1% tolerance is a smoke alarm that is always on."""
    # Every one of these is a *deliberate* 8pp drift, invisible at 0.001.
    permissive = 0.001
    assert abs(0.25 - 0.33) > permissive
    # ...so the check degenerates into "everything drifts". Confirm the
    # fractional reading is the discriminating one.
    assert abs(0.25 - 0.33) <= 0.10


def test_a_threshold_above_one_is_refused_as_a_percent_in_a_fraction_field() -> None:
    with pytest.raises(ValueError, match="fraction"):
        _check(_CURRENT, threshold=10.0)


def test_a_zero_or_negative_threshold_is_refused() -> None:
    with pytest.raises(ValueError, match="fraction"):
        _check(_CURRENT, threshold=0.0)
    with pytest.raises(ValueError, match="fraction"):
        _check(_CURRENT, threshold=-0.1)


def test_the_accessor_reads_its_leaf_not_the_shipped_literal() -> None:
    """A test asserting the shipped value cannot see a hardcoded literal (D-050)."""
    settings = get_settings()
    moved = settings.risk.model_copy(deep=True)
    object.__setattr__(
        moved,
        "rebalancing_drift",
        moved.rebalancing_drift.model_copy(update={"value": 0.25}),
    )
    assert moved.rebalancing_drift_threshold == pytest.approx(0.25)
    # And the shipped one is untouched, proving the read is live.
    assert get_settings().risk.rebalancing_drift_threshold == pytest.approx(0.10)


def test_a_custom_threshold_overrides_the_configured_default() -> None:
    """5% tolerance: ust2y's 21% drift still flags, ust10y's 8% now does too."""
    result = _check(_CURRENT, threshold=0.05)

    assert sorted(_values_of(result)["drifted_instruments"]) == ["ust10y", "ust2y"]
    assert _values_of(result)["drift_threshold_fraction"] == pytest.approx(0.05)


# --------------------------------------------------------------------------
# Defect 1: a missing instrument is not a zero contribution.
# --------------------------------------------------------------------------


def test_a_budgeted_instrument_absent_from_currents_is_reported_missing() -> None:
    result = _check({"ust2y": 0.14, "ust10y": 0.17})  # spx absent

    assert _values_of(result)["missing_instruments"] == ["spx"]
    assert any("no current contribution" in w for w in result.warnings)


def test_a_missing_instrument_at_a_zero_target_is_not_silently_balanced() -> None:
    """The coincide-by-accident case: target 0.0 + absent reads as perfect."""
    targets = [RiskBudgetTarget(instrument="cash", target_risk_contribution_pct=0.0)]
    result = check_rebalancing_drift({}, targets)

    # The arithmetic says "balanced" — and the warning is what stops that from
    # being read as a fact about an instrument the function never saw.
    assert _values_of(result)["outcome"] == "balanced"
    assert _values_of(result)["missing_instruments"] == ["cash"]
    assert any("held at zero risk" in w for w in result.warnings)


def test_an_explicit_zero_is_distinguishable_from_an_absent_entry() -> None:
    targets = [RiskBudgetTarget(instrument="cash", target_risk_contribution_pct=0.0)]

    absent = check_rebalancing_drift({}, targets)
    present = check_rebalancing_drift({"cash": 0.0}, targets)

    assert _values_of(absent)["missing_instruments"] == ["cash"]
    assert _values_of(present)["missing_instruments"] == []
    # Same arithmetic answer, different reported knowledge.
    assert _values_of(absent)["outcome"] == _values_of(present)["outcome"]


def test_a_missing_instrument_raises_a_data_quality_flag() -> None:
    result = _check({"ust2y": 0.14, "ust10y": 0.17})

    assert result.data_quality_flags_present is True


def test_no_missing_instrument_leaves_the_flag_clear() -> None:
    result = _check(_CURRENT)

    assert result.data_quality_flags_present is False


# --------------------------------------------------------------------------
# Defect 2: an instrument outside the budget.
# --------------------------------------------------------------------------


def test_an_unbudgeted_instrument_is_reported_not_ignored() -> None:
    result = _check({**_CURRENT, "eurusd": 0.05})

    assert _values_of(result)["unbudgeted_instruments"] == ["eurusd"]
    assert any("NO budget line" in w for w in result.warnings)


def test_an_unbudgeted_instrument_does_not_create_a_drift_row() -> None:
    """It is a missing budget, not a drift — a different repair."""
    result = _check({**_CURRENT, "eurusd": 0.05})

    assert "eurusd" not in _values_of(result)["drifted_instruments"]
    assert _values_of(result)["drifted_instruments"] == ["ust2y"]


def test_unbudgeted_instruments_are_sorted_for_determinism() -> None:
    """The published order is SORTED, not the order a set happens to iterate.

    **Why this test was rewritten (D-107).** The original supplied
    ``{"zzz": 0.01, "aaa": 0.01}`` and asserted ``== ["aaa", "zzz"]``. Under a
    mutant that returns ``list(set(...) - seen)`` instead of
    ``sorted(set(...) - seen)`` that is **only a pin by luck of the interpreter's
    hash seed**: ``list({"zzz", "aaa"})`` is ``["aaa", "zzz"]`` for some seeds and
    ``["zzz", "aaa"]`` for others, so the mutation was killed in some processes and
    SURVIVED in others. Measured: ``PYTHONHASHSEED=0`` -> the mutant survives,
    ``PYTHONHASHSEED=1`` -> the mutant is killed. A sweep verdict that depends on
    the hash seed certifies nothing.

    **The fix is the fixture size.** A set whose iteration order *coincides* with
    sorted order is what made the mutant survivable; at two elements that is a
    coin-flip, at seven it is astronomically unlikely (measured: the set order
    differs from sorted for every seed tried, ``0..7``). The test therefore
    supplies seven unbudgeted names and pins the sorted order, and — as a second,
    independent pin — asserts the published list does not vary with the caller's
    insertion order.
    """
    names = ["zzz", "aaa", "ccc", "bbb", "qqq", "mmm", "yyy"]
    expected = sorted(names)

    forward = _values_of(_check({**_CURRENT, **dict.fromkeys(names, 0.01)}))[
        "unbudgeted_instruments"
    ]
    reversed_ = _values_of(_check({**_CURRENT, **dict.fromkeys(reversed(names), 0.01)}))[
        "unbudgeted_instruments"
    ]

    # Sorted — and with seven names a `list(set(...))` mutant cannot satisfy this
    # for any realistic hash seed.
    assert forward == expected
    # The same set supplied in the opposite insertion order must publish identically.
    assert reversed_ == expected
    assert forward == reversed_


def test_no_unbudgeted_instrument_emits_no_unbudgeted_warning() -> None:
    result = _check(_CURRENT)

    assert _values_of(result)["unbudgeted_instruments"] == []
    assert not any("NO budget line" in w for w in result.warnings)


# --------------------------------------------------------------------------
# The share basis. Risk contributions are SHARES and must sum to 1.
# --------------------------------------------------------------------------


def test_the_fixture_sums_to_one_as_shares_must() -> None:
    targets = [
        RiskBudgetTarget(instrument="ust2y", target_risk_contribution_pct=0.35),
        RiskBudgetTarget(instrument="ust10y", target_risk_contribution_pct=0.25),
        RiskBudgetTarget(instrument="spx", target_risk_contribution_pct=0.25),
        RiskBudgetTarget(instrument="eurusd", target_risk_contribution_pct=0.15),
    ]
    result = check_rebalancing_drift(
        {"ust2y": 0.35, "ust10y": 0.25, "spx": 0.25, "eurusd": 0.15}, targets
    )

    assert _values_of(result)["total_current_contribution"] == pytest.approx(1.0)
    assert not any("not 1.0" in w for w in result.warnings)


def test_a_set_not_summing_to_one_is_disclosed() -> None:
    result = _check(_CURRENT)  # 0.56

    assert _values_of(result)["total_current_contribution"] == pytest.approx(0.56)
    assert any("not 1.0" in w for w in result.warnings)


def test_dollar_contributions_against_fractional_targets_flag_everything() -> None:
    """The unit trap the sum-to-one warning exists to surface."""
    targets = [
        RiskBudgetTarget(instrument="a", target_risk_contribution_pct=0.5),
        RiskBudgetTarget(instrument="b", target_risk_contribution_pct=0.5),
    ]
    result = check_rebalancing_drift({"a": 50000.0, "b": 50000.0}, targets)

    assert _values_of(result)["instruments_drifted"] == 2
    # The sum-to-one warning is the only thing that says *why*.
    assert any("not 1.0" in w for w in result.warnings)


def test_the_sum_warning_bound_is_read_from_the_leaf_not_a_literal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A **mover**, not a pinner (D-031): the bound must be READ, not retyped.

    The shipped leaf (``0.01``) equals the literal this replaced, so a fixed-input
    test passes whether the function reads the config or hardcodes ``0.01``. The
    test therefore MOVES the leaf to values the old literal does not equal and
    requires the published warning to follow — the only shape that can tell a
    config read from a retyped literal.

    At a 5% deviation from 1.0 (``_CURRENT`` sums to 0.56): a bound of ``0.5``
    must SUPPRESS the warning, and the shipped ``0.01`` must raise it. Before
    this fix both used ``0.01`` and the sweep could not see the difference —
    ``mutation_rebalancing.py``'s M9.3 deletes the whole branch, so a mutant that
    MOVES the bound survived.
    """
    import macro_engine.portfolio.risk_budget as module
    from macro_engine.config import get_settings as _real_get_settings

    settings = _real_get_settings()

    def _with_bound(bound: float) -> Any:
        moved_risk = settings.risk.model_copy(deep=True)
        object.__setattr__(
            moved_risk,
            "rebalancing_contribution_sum_tolerance_value",
            moved_risk.rebalancing_contribution_sum_tolerance_value.model_copy(
                update={"value": bound}
            ),
        )
        return settings.model_copy(update={"risk": moved_risk})

    # The shipped bound (0.01) fires on a 44%-off-1.0 input; that is the control.
    monkeypatch.setattr(module, "get_settings", lambda: _with_bound(0.01))
    assert any("not 1.0" in w for w in _check(_CURRENT).warnings)

    # A LOOSE bound (0.5) is above the 0.44 deviation, so the warning must vanish:
    # only a live config read can make this pass.
    monkeypatch.setattr(module, "get_settings", lambda: _with_bound(0.5))
    assert not any("not 1.0" in w for w in _check(_CURRENT).warnings)

    # A TIGHT bound (1e-9) fires on a set that is off 1.0 by more than a part in
    # 10^9 but far less than the shipped 0.01: only a live read of the leaf can
    # make this pass, and it proves the bound is what decides the warning.
    monkeypatch.setattr(module, "get_settings", lambda: _with_bound(1e-9))
    slightly_off = {"ust2y": 0.35, "ust10y": 0.25, "spx": 0.25, "eurusd": 0.1500001}
    targets = [*_TARGETS, RiskBudgetTarget(instrument="eurusd", target_risk_contribution_pct=0.15)]
    # The shipped 0.01 would not fire on a 1e-7 deviation; the moved 1e-9 does.
    assert any("not 1.0" in w for w in check_rebalancing_drift(slightly_off, targets).warnings)


def test_the_sum_tolerance_leaf_is_validated_at_load() -> None:
    """A bound outside ``(0, 1]`` is refused (the D-128 dead-threshold class).

    ``<= 0`` would warn on every input (the warning carries no information) and
    ``> 1`` would never fire (dead code). The validator is exercised by rebuilding
    the live settings with a bad leaf, mirroring the config-load refusal.
    """
    from pydantic import ValidationError

    settings = get_settings()
    risk = settings.risk

    for bad in (0.0, -0.01, 1.5):
        raw = risk.model_dump()
        raw["rebalancing_contribution_sum_tolerance_value"] = {
            "value": bad,
            "calibration_status": "mechanical_rule",
            "note": "test",
        }
        with pytest.raises(ValidationError, match="rebalancing_contribution_sum_tolerance"):
            type(risk)(**raw)


# --------------------------------------------------------------------------
# The structural-separation contract (Section 15.18's whole purpose).
# --------------------------------------------------------------------------


def test_the_maintenance_warning_is_always_present() -> None:
    """Nothing in this function may speak to thesis validity."""
    for current in (_CURRENT, {"ust2y": 0.35, "ust10y": 0.25, "spx": 0.25}):
        result = _check(current)
        assert any("NOT a thesis-validity check" in w for w in result.warnings)


def test_the_output_never_mentions_thesis_validity_affirmatively() -> None:
    """The separation is structural, so a test reads the vocabulary, not a flag."""
    result = _check(_CURRENT)
    joined = " ".join(result.warnings) + " " + result.interpretation + " " + result.context

    assert "NOT a thesis-validity check" in joined
    assert "thesis is wrong" in joined
    # ...but never asserts it *is* invalid.
    assert "thesis is invalid" not in joined.lower()


def test_the_module_subject_is_rebalancing_not_invalidation() -> None:
    result = _check(_CURRENT)

    assert result.model_name == "rebalancing_drift_check"
    assert result.country == "us"


# --------------------------------------------------------------------------
# The published contract.
# --------------------------------------------------------------------------


def test_every_declared_outcome_is_producible() -> None:
    """The producibility half of the Literal promise (D-045a)."""
    outcomes = {
        _values(_CURRENT)["outcome"],
        _values({"ust2y": 0.35, "ust10y": 0.25, "spx": 0.25})["outcome"],
    }
    assert outcomes == {"rebalance", "balanced"}


def test_the_declared_outcome_set_is_pinned_to_the_type() -> None:
    """A Literal is NOT runtime-enforced, so only get_args can see it (D-054)."""
    assert set(get_args(RebalancingOutcome)) == {"balanced", "rebalance"}


def test_both_drift_directions_are_producible() -> None:
    from macro_engine.portfolio.risk_budget import DriftDirection

    assert set(get_args(DriftDirection)) == {"over", "under"}
    over = _check({"ust2y": 0.35, "ust10y": 0.25, "spx": 0.25 + 0.20})
    under = _check(_CURRENT)
    assert _values_of(over)["drifted"][0]["direction"] == "over"
    assert _values_of(under)["drifted"][0]["direction"] == "under"


def test_every_published_key_is_present() -> None:
    result = _check(_CURRENT)

    assert set(_values_of(result)) == {
        "outcome",
        "drifted",
        "drifted_instruments",
        "unbudgeted_instruments",
        "missing_instruments",
        "instruments_evaluated",
        "instruments_drifted",
        "drift_threshold_fraction",
        "total_current_contribution",
    }


def test_inputs_used_names_both_inputs() -> None:
    result = _check(_CURRENT)

    assert result.inputs_used == ["current_contributions", "targets"]


def test_an_empty_target_list_is_balanced_with_a_zero_denominator() -> None:
    result = check_rebalancing_drift({}, [])

    assert _values_of(result)["outcome"] == "balanced"
    assert _values_of(result)["instruments_evaluated"] == 0


def test_the_result_is_deterministic_under_repeated_calls() -> None:
    first = _check(_CURRENT)
    second = _check(_CURRENT)

    assert first.value == second.value


def test_the_result_is_invariant_under_target_permutation() -> None:
    """Order is not load-bearing; a set has no order."""
    reversed_targets = list(reversed(_TARGETS))
    forward = _check(_CURRENT)
    backward = _check(_CURRENT, targets=reversed_targets)

    assert _values_of(forward)["drifted_instruments"] == _values_of(backward)["drifted_instruments"]
    assert _values_of(forward)["instruments_drifted"] == _values_of(backward)["instruments_drifted"]


# --------------------------------------------------------------------------
# The input contract.
# --------------------------------------------------------------------------


def test_a_target_above_one_is_refused() -> None:
    with pytest.raises(ValueError):
        RiskBudgetTarget(instrument="x", target_risk_contribution_pct=1.5)


def test_a_negative_target_is_refused() -> None:
    with pytest.raises(ValueError):
        RiskBudgetTarget(instrument="x", target_risk_contribution_pct=-0.01)


def test_an_empty_instrument_name_is_refused() -> None:
    with pytest.raises(ValueError):
        RiskBudgetTarget(instrument="", target_risk_contribution_pct=0.1)


def test_an_unknown_target_field_is_refused() -> None:
    with pytest.raises(ValueError):
        RiskBudgetTarget.model_validate(
            {"instrument": "x", "target_risk_contribution_pct": 0.1, "extra": 1}
        )


def test_a_duplicate_instrument_is_evaluated_twice_not_deduplicated() -> None:
    """A duplicate budget line is a caller error; the function reports both rows.

    Hand-computed: one actual (0.5) against two contradictory targets
    (0.1 and 0.9) drifts on BOTH — signed +0.40 and -0.40, each above 0.10.
    The point is that the function does not silently take the last or the
    first line; it reports that the budget is self-contradictory.
    """
    targets = [
        RiskBudgetTarget(instrument="a", target_risk_contribution_pct=0.1),
        RiskBudgetTarget(instrument="a", target_risk_contribution_pct=0.9),
    ]
    result = check_rebalancing_drift({"a": 0.5}, targets)

    assert _values_of(result)["instruments_evaluated"] == 2
    assert _values_of(result)["instruments_drifted"] == 2
    assert [row["direction"] for row in _values_of(result)["drifted"]] == ["over", "under"]


def test_the_extra_forbid_is_load_bearing_on_the_validate_path_too() -> None:
    """``extra="forbid"`` is a *contract*, so it is tested where it is observable.

    The explicit-kwarg path is refused by ``__init__`` regardless of the config,
    so a test using only that path cannot see the setting at all (D-050's
    hardcoded-literal lesson, one level down: a test that cannot observe the
    difference is not a test of it). ``model_validate`` is the path where the
    config decides.
    """
    import pydantic

    with pytest.raises((pydantic.ValidationError, ValueError)):
        RiskBudgetTarget.model_validate(
            {"instrument": "x", "target_risk_contribution_pct": 0.1, "stray": 1}
        )


# --------------------------------------------------------------------------
# Survivors from the D-055 mutation sweep. Each of these was an unexplained
# DEFECT survivor -- a reachable output no test pinned. They are appended as a
# named group so a future reader can see exactly which mutation each closes.
# --------------------------------------------------------------------------


def test_the_total_contribution_includes_unbudgeted_instruments() -> None:
    """Closes sweep M5.4 (the total restricted to ``seen``).

    The published total is a statement about the WHOLE book, not about the
    budgeted part of it: it exists so a caller can notice their inputs do not
    sum to 1. Restricting it to budgeted instruments would silently *hide* the
    unbudgeted risk the sum-to-one warning is meant to surface -- two defects
    canceling into a plausible number, which is the failure class this project
    keeps finding.

    Hand-computed: ``_CURRENT`` sums to 0.14 + 0.17 + 0.25 == 0.56 (it is the
    DRIFTED fixture, not the balanced one), and adding eurusd's 0.05 makes the
    published total 0.61. The budgeted-only sum would still be 0.56 -- so the
    unwrapped assertion below is a genuine discriminator, not a restatement.
    """
    result = _check({**_CURRENT, "eurusd": 0.05})

    assert _values_of(result)["unbudgeted_instruments"] == ["eurusd"]
    assert _values_of(result)["total_current_contribution"] == pytest.approx(0.61)
    assert _values_of(result)["total_current_contribution"] != pytest.approx(0.56)


def test_the_configured_threshold_is_read_by_the_function_not_just_the_accessor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Closes sweep M3.3 (the function's own literal ``0.10``).

    ``test_the_accessor_reads_its_leaf_not_the_shipped_literal`` mutates the
    config leaf and re-reads ``settings.risk.rebalancing_drift_threshold``. It
    therefore proves the ACCESSOR is live and says nothing about whether the
    function consults it -- a function hardcoding ``0.10`` passes it unchanged.
    This test moves the leaf and calls the function, which is the only path
    that can see the difference.

    ``monkeypatch.setattr`` is used rather than a hand-rolled save/restore: it is
    the pattern the other test modules in this repository follow
    (``tests/models/test_convergence.py``), and it guarantees the restoration
    even if an assertion fires -- a manual ``finally`` achieves the same thing
    with more code and more ways to get it wrong.
    """
    import macro_engine.portfolio.risk_budget as module
    from macro_engine.config import get_settings as _real_get_settings

    settings = _real_get_settings()
    # ``rebalancing_drift`` lives on the nested ``risk`` block, not on Settings
    # itself -- the same shape the accessor test uses.
    moved_risk = settings.risk.model_copy(deep=True)
    object.__setattr__(
        moved_risk,
        "rebalancing_drift",
        moved_risk.rebalancing_drift.model_copy(update={"value": 0.02}),
    )
    moved_settings = settings.model_copy(update={"risk": moved_risk})

    monkeypatch.setattr(module, "get_settings", lambda: moved_settings)

    # At the shipped 0.10 threshold this book is balanced on ust10y (signed
    # -0.08). At 0.02 it drifts.
    result = _check(_CURRENT)

    assert _values_of(result)["drift_threshold_fraction"] == pytest.approx(0.02)
    assert sorted(_values_of(result)["drifted_instruments"]) == ["ust10y", "ust2y"]


def test_the_structural_separation_is_stated_in_the_context_not_only_the_warning() -> None:
    """Closes sweep M10.4 (the context string emptied).

    ``context`` is where a downstream consumer reads WHY this function exists,
    and Section 15.18's whole content is that reason. A warning is attached to
    this call; the context travels with the result -- so emptying it removes the
    separation from every surface except the one that happened to be asserted.
    """
    result = _check(_CURRENT)

    assert "PORTFOLIO risk-budget maintenance" in result.context
    assert "drifted" in result.context and "thesis is wrong" in result.context


def test_a_missing_instrument_still_drifts_at_zero_risk_not_at_its_target() -> None:
    """Closes sweep M1.1 and M1.2 together — the missing-vs-zero distinction.

    Both mutants substitute the absent instrument's *target* for its missing
    value, which makes a budgeted-but-not-held position read as perfectly on
    budget. That is defect 1 in its purest form: "not held" and "held at zero
    risk" collapse into one input, and the collapse is **silent** — the book
    reports ``balanced`` while an instrument it was told to budget has no data
    behind it at all.

    Hand-computed: two 0.5 targets, only ``b`` held (at 0.5). Under the shipped
    read, ``a`` is absent -> 0.0 -> signed -0.5 -> DRIFTED. Under M1.2 it would
    be 0.5 -> signed 0.0 -> no row, and the only surviving trace would be the
    ``missing_instruments`` list.
    """
    targets = [
        RiskBudgetTarget(instrument="a", target_risk_contribution_pct=0.5),
        RiskBudgetTarget(instrument="b", target_risk_contribution_pct=0.5),
    ]
    result = check_rebalancing_drift({"b": 0.5}, targets)

    assert _values_of(result)["missing_instruments"] == ["a"]
    # The absent instrument is measured against ZERO, not against its target.
    assert _values_of(result)["drifted_instruments"] == ["a"]
    assert _values_of(result)["drifted"][0]["actual_risk_contribution"] == pytest.approx(0.0)
    assert _values_of(result)["drifted"][0]["signed_drift"] == pytest.approx(-0.5)
    assert _values_of(result)["drifted"][0]["direction"] == "under"


def test_the_caller_threshold_accepts_a_non_float_number() -> None:
    """Closes sweep M3.4 (the ``float()`` cast on the caller's argument).

    ``drift_threshold_pct`` is typed ``float | None``, but a caller holding a
    ``Decimal`` (or an int) reaches the comparison without the cast and the
    arithmetic degrades differently — ``0.10`` as a ``Decimal`` compares
    against a float in a way ``Decimal.__gt__`` refuses outright in some Python
    versions. The cast is what makes every numeric input behave as one type, so
    the test supplies a numeric input that is NOT a float.
    """
    from decimal import Decimal

    result = _check(_CURRENT, threshold=Decimal("0.05"))  # type: ignore[arg-type]

    assert _values_of(result)["drift_threshold_fraction"] == pytest.approx(0.05)
    assert sorted(_values_of(result)["drifted_instruments"]) == ["ust10y", "ust2y"]


def test_the_threshold_guard_names_the_unit_it_expects() -> None:
    """Closes sweep M3.8 (the guard's message stripped of its unit claim).

    The guard exists because ``drift_threshold_pct`` is a FRACTION wearing a
    ``_pct`` suffix. A guard that rejects ``10.0`` without saying *why* leaves
    the next caller to guess which of the two readings was wrong -- which is how
    a 100x error gets reintroduced by someone "fixing" the bound instead of the
    value. The message is part of the repair, so it is tested.

    **The first draft of this test could not kill its mutation**, because the
    mutant rewrote only the first of the message's two concatenated f-strings
    and the word "percent" survived in the second. A test is not a test of a
    message unless the mutation removes what the test reads -- so the assertion
    below reads BOTH sentences.
    """
    with pytest.raises(ValueError) as excinfo:
        _check(_CURRENT, threshold=10.0)

    message = str(excinfo.value)
    assert "fraction in (0, 1]" in message
    assert "percent written into a fraction field" in message


def test_the_accessor_returns_a_plain_float() -> None:
    """Documents the CONDITIONAL inertness of the accessor's ``float()`` cast.

    Sweep survivor CX3 drops the cast and **cannot be killed today**, because
    the leaf is already a ``float`` and ``float(v) is v``. That is recorded in
    the sweep as a *conditional* proof, and this test is what makes the
    condition checkable: if the shipped leaf ever stops being a float, this
    assertion fails and the sweep's proof stops applying -- which is exactly
    when someone needs to know.

    It is a guard on a documented equivalence, not a kill of a mutation, and it
    is labelled as such so no future reader mistakes a green test for coverage.
    """
    from macro_engine.config import get_settings

    leaf = get_settings().risk.rebalancing_drift.value

    assert type(leaf) is float, (
        "the CX3 inertness proof in scripts/mutation_rebalancing.py is CONDITIONAL "
        "on this leaf being a float; if this fails, that proof must be revisited"
    )
    assert get_settings().risk.rebalancing_drift_threshold == float(leaf)


# --------------------------------------------------------------------------
# Confidence (Section 22.8 — computed, never asserted).
# --------------------------------------------------------------------------


def test_confidence_is_the_midpoint_and_the_heuristic_penalty_is_why() -> None:
    """base 0.7 - heuristic_penalty 0.2 == 0.5, asserted as a discriminating value."""
    result = _check(_CURRENT)
    settings = get_settings()

    expected = settings.confidence.base.value - settings.confidence.heuristic_penalty.value
    assert result.confidence == pytest.approx(expected)
    assert result.confidence == pytest.approx(0.5)


def test_a_data_quality_flag_lowers_confidence_below_the_clean_case() -> None:
    clean = _check(_CURRENT)
    flagged = _check({"ust2y": 0.14, "ust10y": 0.17})  # spx missing

    assert flagged.confidence < clean.confidence


def test_the_confidence_is_not_a_hardcoded_literal() -> None:
    """A data-quality flag must move it, which a literal cannot do."""
    settings = get_settings()
    assert _check(_CURRENT).confidence != settings.confidence.base.value


# --------------------------------------------------------------------------
# The deliberate NON-application of the base-state rule (lesson 5g).
# --------------------------------------------------------------------------


def test_the_base_state_failure_does_not_apply_here() -> None:
    """``balanced`` is modal and that is CORRECT for a maintenance check.

    Unlike D-047's ``HIGH`` at 89.5% or D-053's ``stable`` at 79.1%, the modal
    outcome here is not the absence of information — it is the right answer for
    a book that is on budget. The probe measured a 10.8% trip rate over 20 000
    plausible weight wobbles on a realistic 4-instrument covariance, so the
    partition is non-degenerate in both directions and the check discriminates.
    """
    # Both outcomes are reachable, and neither is a degenerate always-answer.
    assert _values(_CURRENT)["outcome"] == "rebalance"
    assert _values({"ust2y": 0.35, "ust10y": 0.25, "spx": 0.25})["outcome"] == "balanced"


def test_a_single_instrument_book_can_be_either_outcome() -> None:
    """A one-instrument check still discriminates — no hidden unanimity rule."""
    targets = [RiskBudgetTarget(instrument="a", target_risk_contribution_pct=0.50)]

    assert _values_of(check_rebalancing_drift({"a": 0.50}, targets))["outcome"] == "balanced"
    assert _values_of(check_rebalancing_drift({"a": 0.80}, targets))["outcome"] == "rebalance"


# --------------------------------------------------------------------------
# Warning coverage — a partition, not a hit (lesson 5f / D-052).
# --------------------------------------------------------------------------

_WARNING_MARKERS = [
    "NOT a thesis-validity check",
    "NO budget line",
    "no current contribution",
    "not 1.0",
]

# Every warning this function can emit, as mutually non-colliding markers.
_ALL_WARNING_MARKERS = _WARNING_MARKERS


def _warning_scenarios() -> list[dict[str, float]]:
    return [
        _CURRENT,  # baseline
        {**_CURRENT, "eurusd": 0.05},  # unbudgeted
        {"ust2y": 0.14, "ust10y": 0.17},  # missing spx
        {**_CURRENT, "eurusd": 0.05, "aaa": 0.02},  # unbudgeted several
    ]


def test_every_warning_branch_is_triggered_by_some_test() -> None:
    emitted: set[str] = set()
    for current in _warning_scenarios():
        result = _check(current)
        for warning in result.warnings:
            matching = [m for m in _ALL_WARNING_MARKERS if m in warning]
            # A partition, not a hit: each warning matches exactly one marker.
            assert len(matching) == 1, f"{warning!r} matched {matching}"
            emitted.add(matching[0])

    assert emitted == set(_ALL_WARNING_MARKERS)


def test_each_warning_matches_exactly_one_marker() -> None:
    """Guards against a wording collision masquerading as coverage."""
    for current in _warning_scenarios():
        for warning in _check(current).warnings:
            matches = [m for m in _ALL_WARNING_MARKERS if m in warning]
            assert len(matches) == 1


def test_the_marker_set_is_internally_non_colliding() -> None:
    """No marker is a substring of another — the failure D-052's M10.3 exploited."""
    for outer in _ALL_WARNING_MARKERS:
        for inner in _ALL_WARNING_MARKERS:
            if outer is not inner:
                assert inner not in outer, f"{inner!r} hides inside {outer!r}"
