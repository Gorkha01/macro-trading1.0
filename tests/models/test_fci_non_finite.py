"""Non-finite inputs must not poison a composite (Section 21.0 rule 2).

The FCI is the case the audit found. ``compute_fci`` aggregates standardised
components as ``fci = sum(contributions.values())``. Because ``sum`` propagates
NaN, **one** non-finite component silently destroys the whole composite:

  * ``fci`` becomes ``nan`` — the reported index value;
  * ``tighter_than_average = fci > 0.0`` becomes ``False``, which is the
    directive's forbidden "missing -> False / neutral" substitution, and it is
    *silent*: a reader sees "financial conditions are looser than average",
    which is a fabricated conclusion drawn from absent data.

Worse than a missing component: nothing degrades to INSUFFICIENT_DATA, because
a NaN composite is still a float and every downstream guard accepts it.

``FCIComponent.std`` is already guarded (``gt=0.0``) and rejects NaN correctly —
but it accepts ``inf``, and an infinite divisor yields ``z_score == 0.0``,
which is again a neutral value manufactured from a broken input.

These tests are RED before the guards and must stay GREEN afterwards.
"""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from macro_engine.models.financial_conditions import FCIComponent

NON_FINITE = [float("nan"), float("inf"), float("-inf")]


# ---------------------------------------------------------------------------
# FCIComponent: value and std must both be finite.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", NON_FINITE)
def test_fci_component_rejects_non_finite_value(bad: float) -> None:
    """A non-finite component value must be refused at construction.

    Measured before the fix: accepted, and ``z_score`` returned ``nan``.
    """
    with pytest.raises(ValidationError):
        FCIComponent(value=bad, mean=0.0, std=1.0)


@pytest.mark.parametrize("bad", NON_FINITE)
def test_fci_component_rejects_non_finite_std(bad: float) -> None:
    """A non-finite divisor must be refused.

    Measured before the fix: ``std=nan`` was rejected by ``gt=0.0`` (because a
    NaN comparison is False), but ``std=inf`` was **accepted** and produced
    ``z_score == 0.0`` — a neutral reading invented from a broken denominator.
    The guard must reject both, and for the right reason.
    """
    with pytest.raises(ValidationError):
        FCIComponent(value=1.0, mean=0.0, std=bad)


def test_fci_component_still_accepts_finite_inputs() -> None:
    """No false positives: ordinary components must still work."""
    component = FCIComponent(value=4.35, mean=4.10, std=0.25)
    assert component.z_score == pytest.approx(1.0)


def test_fci_component_z_score_is_always_finite_for_accepted_input() -> None:
    """The load-bearing invariant: if construction succeeds, z is a real number.

    This is the property a consumer actually relies on. Stating it directly
    means a future guard removal fails here rather than in a thesis.
    """
    component = FCIComponent(value=0.0, mean=0.0, std=1e-300)
    assert math.isfinite(component.z_score), (
        "an accepted component produced a non-finite z-score, so the "
        "constructor's guard does not cover the divisor's range"
    )


# ---------------------------------------------------------------------------
# The composite: a poisoned component must not silently produce a verdict.
# ---------------------------------------------------------------------------


def test_sum_of_contributions_propagates_nan_without_a_guard() -> None:
    """Pin the REASON the composite needs its own guard.

    ``sum`` has no opinion about NaN, and a comparison against NaN is False —
    so this documents the exact mechanism that produced a silent 'looser than
    average' verdict before the fix.
    """
    contributions = [0.4, float("nan"), -0.1]
    total = sum(contributions)
    assert math.isnan(total), "sum does NOT skip a NaN contribution"
    assert (total > 0.0) is False, (
        "`nan > 0` is False, so `tighter_than_average` silently reads as False "
        "(looser than average) — a conclusion fabricated from a broken input"
    )
