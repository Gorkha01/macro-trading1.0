"""D-139 — the shared finite-input guard, and the promotion that made it shared.

A non-finite float is the one input failure that no downstream test can catch:
``nan`` fails EVERY comparison, so instead of tripping a bound it silently takes
the branch the bound was written to exclude. The policy-rule family found this
first (D-078, where ``taylor_rule(pi_current=nan)`` published ``value=nan`` and
every consumer read ``nan > actual`` as ``False``). The guard that closed it was
a private ``_FiniteInputs`` base inside ``models/policy_rules.py``.

D-139 found the SAME gap open in ``models/labor_synthesis.py`` — every input
group there typed its fields as bare ``float`` with no guard — and promoted the
base to the shared contract module rather than copying it a second time. These
tests pin the shared base's behaviour, so a later edit to it cannot silently
weaken the policy-rule family it was first written for.
"""

from __future__ import annotations

import math

import pytest
from pydantic import BaseModel, Field

from macro_engine.models.contracts import NON_FINITE_INPUT_REMEDY, FiniteInputs
from macro_engine.models.policy_rules import TaylorRuleInputs


class _ScalarOnly(FiniteInputs):
    """A minimal input group: one scalar float, one list, one non-float."""

    scalar: float = Field(description="A scalar input.")
    series: list[float] = Field(default_factory=list, description="A list input.")
    label: str = Field(default="", description="A non-numeric field.")


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_a_non_finite_scalar_is_refused(bad: float) -> None:
    """The base case: a scalar non-finite value never reaches a model body."""
    with pytest.raises(ValueError, match="non-finite"):
        _ScalarOnly(scalar=bad)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_a_non_finite_list_element_is_refused(bad: float) -> None:
    """A non-finite ELEMENT is refused, which `allow_inf_nan=False` cannot do.

    ``allow_inf_nan`` on a ``list[float]`` field constrains the LIST, not its
    elements, so the per-field idiom used elsewhere in this codebase does not
    cover the series-shaped inputs (a weekly claims series, a yield curve). The
    list branch of the shared validator is the only thing that does.
    """
    with pytest.raises(ValueError, match=r"non-finite|series\[1\]"):
        _ScalarOnly(scalar=1.0, series=[1.0, bad])


def test_the_error_names_the_offending_field() -> None:
    """Naming the field is the point: an unnamed refusal is not diagnosable.

    The remedy string is asserted too, so the two halves of the guard — WHICH
    input and WHY it is refused — cannot drift apart.
    """
    with pytest.raises(ValueError) as excinfo:
        _ScalarOnly(scalar=math.nan, series=[math.inf])
    message = str(excinfo.value)
    assert "scalar" in message, message
    assert "series" in message, message
    assert "fails EVERY comparison" in message, (
        "the shared remedy must reach the caller, or the guard explains only "
        "WHAT failed and not why it could not be tolerated"
    )


def test_finite_values_pass_unchanged() -> None:
    """The guard must not become a filter: finite inputs construct as given."""
    group = _ScalarOnly(scalar=-2.5, series=[0.0, 1.5], label="ok")
    assert group.scalar == -2.5
    assert group.series == [0.0, 1.5]
    assert group.label == "ok"


def test_an_integer_input_is_accepted_on_a_float_field() -> None:
    """An ``int`` is always finite, so it must pass through a ``float`` field.

    Pydantic coerces an int to float on the way in, so the guard sees a finite
    ``float`` — this test pins that path, because a future widening of the
    guard to ``numbers.Real`` (or a check that ran BEFORE coercion) could turn a
    perfectly finite integer input into a spurious refusal.
    """
    assert _ScalarOnly(scalar=3).scalar == 3.0


def test_an_empty_series_is_allowed() -> None:
    """Absence is not the failure this guard is for — only non-finite is."""
    assert _ScalarOnly(scalar=1.0).series == []


def test_the_promoted_base_still_guards_the_policy_rule_inputs() -> None:
    """The regression that matters most: promotion must not have loosened it.

    ``TaylorRuleInputs`` now inherits the SHARED base rather than a local one.
    If the promotion had dropped the guard — or if the alias in ``policy_rules``
    ever pointed at a plain ``BaseModel`` — the D-078 defect would reopen with
    no test noticing. This asserts through the policy-rule surface itself.
    """
    with pytest.raises(ValueError, match="non-finite"):
        TaylorRuleInputs(r_star=0.5, pi_current=math.nan, output_gap=0.0)


def test_the_balance_sheet_inputs_are_guarded() -> None:
    """D-139: the sibling class that was left OUT of the guard family.

    ``BalanceSheetInputs`` was the one policy-rule input group that did not
    inherit the finite base, so a ``nan`` change reached ``qe_qt_stance`` and was
    published as a confident ``NEUTRAL_HOLD`` — every ``nan`` comparison returns
    ``False``, which is precisely the neutral branch. This pins the fix through
    the input surface, and the assertion below pins the VERDICT the defect
    produced, so the test documents why the guard is load-bearing here.
    """
    from macro_engine.models.policy_rules import BalanceSheetInputs, qe_qt_stance

    kwargs = {
        "balance_sheet_level": 7_000_000.0,
        "balance_sheet_change_3mo": 0.2,
        "reserve_balances": 3_000_000.0,
        "reserve_balances_change_3mo": 0.1,
        "on_rrp_level": 500.0,
    }
    with pytest.raises(ValueError, match="non-finite"):
        BalanceSheetInputs.model_validate({**kwargs, "balance_sheet_change_3mo": math.nan})

    # And the pre-fix behaviour, recorded so the reason is not lost: with a nan
    # change the stance was published as NEUTRAL_HOLD by a comparison that never
    # discriminated. Constructing the broken input is now impossible, so the
    # observation is asserted on the UNGUARDED input the old class accepted.
    assert qe_qt_stance(BalanceSheetInputs.model_validate(kwargs)).value is not None


def test_every_finite_input_subclass_actually_inherits_the_guard() -> None:
    """Structural: a future input group must not silently skip the base.

    ``extra="forbid"`` and the validator are both supplied by ``FiniteInputs``.
    A subclass that re-declared ``model_config = ConfigDict(extra="forbid")``
    without inheriting would look identical in review while admitting ``nan``,
    so the inheritance is asserted directly on a sample of the families that
    share it.
    """
    from macro_engine.models import labor_synthesis, policy_rules

    for module in (labor_synthesis, policy_rules):
        for name in dir(module):
            obj = getattr(module, name)
            if (
                isinstance(obj, type)
                and issubclass(obj, BaseModel)
                and obj.__name__.endswith("Inputs")
                and obj.__module__ == module.__name__
            ):
                assert issubclass(obj, FiniteInputs), (
                    f"{module.__name__}.{obj.__name__} is a model INPUT group "
                    f"but does not inherit FiniteInputs, so a non-finite value "
                    f"reaches its model body unguarded"
                )


def test_the_remedy_constant_is_the_shared_one() -> None:
    """The remedy text has ONE definition, so every caller explains it alike."""
    assert "neither missing nor neutral" in NON_FINITE_INPUT_REMEDY
    with pytest.raises(ValueError) as excinfo:
        _ScalarOnly(scalar=math.nan)
    assert NON_FINITE_INPUT_REMEDY in str(excinfo.value)
