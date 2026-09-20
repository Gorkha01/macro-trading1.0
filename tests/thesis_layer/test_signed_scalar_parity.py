"""The two ``_signed_scalar`` twins must agree (D-063's rule, D-078's defect).

``thesis_layer/signals.py`` and ``thesis_layer/invalidation.py`` each carry a
private ``_signed_scalar`` that reads a signed number out of a
``ModelResult.value``. They are deliberately separate functions — each layer's
import graph stays closed — but they are required to behave **identically**, and
the signals docstring states the rule outright: the two "sit in one layer and
must not drift".

They drifted. The ``isfinite`` guard added to the signals twin when D-078 was
fixed (``nan`` was being published as ``contradicts``) was never mirrored into
the invalidation twin, where the same input produced a different wrong answer:
``nan`` fell through ``_condition_for_scalar`` to ``None`` and was reported as a
signal sitting **exactly on** the crossing, and ``inf`` produced a confident
``crosses_back_negative`` falsifier. Same input, two layers, two wrong outputs.

A comment asserting the two agree is what failed the first time, so this file
replaces the comment with an executable contract: every value in a shared probe
set is passed through both functions and the results must be equal. Adding a
case to the probe set is how the contract is extended; changing one function
without the other fails here rather than in production.
"""

from __future__ import annotations

import math

import pytest

from macro_engine.thesis_layer.invalidation import (
    _signed_scalar as invalidation_signed_scalar,
)
from macro_engine.thesis_layer.signals import (
    _signed_scalar as signals_signed_scalar,
)

#: Every shape either function can be handed, including the ones that caused the
#: drift. ``True``/``False`` first because ``isinstance(True, int)`` is ``True``;
#: ``nan``/``inf`` because they are ``float`` instances that carry no direction.
#: ``None``, ``str`` and a container stand in for the other unreadable shapes.
_PROBE_VALUES: tuple[object, ...] = (
    True,
    False,
    0,
    1,
    -1,
    2.5,
    -2.5,
    0.0,
    -0.0,
    float("nan"),
    float("inf"),
    float("-inf"),
    None,
    "0.5",
    b"0.5",
    [1.0],
    (1.0,),
    {"value": 1.0},
    complex(1.0, 0.0),
)


def _describe(value: object) -> str:
    """A stable label for a probe value in assertion messages."""
    if isinstance(value, float) and math.isnan(value):
        return "float('nan')"
    return f"{value!r} ({type(value).__name__})"


@pytest.mark.parametrize("value", _PROBE_VALUES, ids=_describe)
def test_both_signed_scalar_twins_agree(value: object) -> None:
    """The twins return the same thing for every shape, including non-finite."""
    from_signals = signals_signed_scalar(value)
    from_invalidation = invalidation_signed_scalar(value)
    assert from_signals == from_invalidation, (
        f"the _signed_scalar twins disagree on {_describe(value)}: "
        f"signals -> {from_signals!r}, invalidation -> {from_invalidation!r}. "
        f"The rule is D-063's: these two must not drift."
    )


@pytest.mark.parametrize("value", _PROBE_VALUES, ids=_describe)
def test_non_finite_and_boolean_values_are_refused_by_both(value: object) -> None:
    """The specific class D-078 and this drift cover: no direction from a value.

    A ``bool`` is a flag, not a magnitude; ``nan``/``inf`` are floats that failed
    to compute or overflowed. None of them carries a sign, so both functions must
    return ``None`` rather than a number a caller would use to assert a direction.
    """
    if isinstance(value, bool) or (isinstance(value, float) and not math.isfinite(value)):
        assert signals_signed_scalar(value) is None, _describe(value)
        assert invalidation_signed_scalar(value) is None, _describe(value)


def test_finite_numbers_still_pass_through_unchanged() -> None:
    """The guard must not over-reach: real signed readings still come back.

    A guard that refused everything would satisfy both tests above and break the
    falsifier entirely, so the positive case is asserted explicitly.
    """
    for value in (0, 1, -1, 0.0, -0.0, 2.5, -2.5, 1e12, -1e12):
        assert signals_signed_scalar(value) == float(value), value
        assert invalidation_signed_scalar(value) == float(value), value


def test_nan_does_not_produce_a_confident_falsifier() -> None:
    """The end-to-end consequence, not just the guard.

    Before the fix, ``_signed_scalar(nan)`` returned ``nan`` and
    ``_condition_for_scalar`` fell through both comparisons to ``None`` — which
    the caller renders as a signal *at* the balance point. This asserts the value
    never reaches the condition builder at all, so the false "neutral" reading is
    unreachable by construction rather than merely unlikely.
    """
    from macro_engine.thesis_layer.invalidation import _condition_for_scalar

    for non_finite in (float("nan"), float("inf"), float("-inf")):
        assert invalidation_signed_scalar(non_finite) is None
        # The builder is only ever called with a finite value, so passing one
        # directly is the only way to reach it and it must still behave sanely.
        assert _condition_for_scalar("x", 0.0, 0.0) is None
        assert _condition_for_scalar("x", 1.0, 0.5) is not None
