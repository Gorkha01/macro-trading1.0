"""The two ``_signed_scalar`` guards must not drift (D-063 / D-078).

``thesis_layer/signals.py`` and ``thesis_layer/invalidation.py`` each carry a
private ``_signed_scalar`` with the same job: read a signed number out of a
union-typed ``ModelResult.value``, or ``None``. Both docstrings say the copies
"must not drift", and ``invalidation.py`` names **this file** as the thing that
enforces it:

    Any change to either guard belongs in both, and
    ``tests/thesis_layer/test_signed_scalar_parity.py`` now fails if they
    disagree.

MEASURED 2026-10-06: the file did not exist (``tests/thesis_layer/`` held only
``test_warnings_citations.py``), so the claim was false and the invariant was
unenforced — the two guards agreed by transcription, which is exactly the "two
copies of a fact" state in which a later edit to one of them changes behaviour
silently.

The two are deliberately separate functions (a shared helper would put the
thesis layer's direction rule and its invalidation rule in one module), so the
link has to be a test rather than an import. This is that test.

Why the battery is what it is: ``bool`` and the non-finite floats are the cases
the guard EXISTS for. ``isinstance(True, int)`` is True, so a flag would read as
a corroborating ``1.0``; ``nan`` passes the same type test and then fails every
comparison, publishing ``contradicts`` (D-078); ``inf`` publishes ``confirms``.
A parity test over ordinary numbers alone would pass for two guards that had
BOTH lost their ``isfinite`` clause, so the behaviour is pinned separately.
"""

from __future__ import annotations

import pytest

from macro_engine.thesis_layer import invalidation, signals

#: Chosen so every branch of the guard is exercised: the bool-first exclusion,
#: the finite-number admission, and the non-finite rejection (the clause a
#: future edit is most likely to drop).
_CASES: list[object] = [
    True,
    False,
    0,
    1,
    -1,
    0.0,
    1.5,
    -2.75,
    10**18,
    float("nan"),
    float("inf"),
    float("-inf"),
    None,
    "1.5",
    {"classification": "HIGH"},
    ["1.5"],
    (1,),
]


@pytest.mark.parametrize("value", _CASES, ids=lambda v: f"{type(v).__name__}={v!r}"[:44])
def test_the_two_signed_scalar_guards_agree(value: object) -> None:
    """The two private guards must return the SAME thing for every input."""
    a = signals._signed_scalar(value)
    b = invalidation._signed_scalar(value)
    # Compared by repr, not ==, so a `nan` return would be a visible mismatch
    # rather than a second false negative.
    assert repr(a) == repr(b), (
        f"the two _signed_scalar guards disagree on {value!r}: "
        f"signals -> {a!r}, invalidation -> {b!r}. They are copies of one rule "
        f"(D-063/D-078); any change to either belongs in BOTH."
    )


def test_both_guards_still_refuse_the_shapes_they_exist_for() -> None:
    """Non-vacuity: the parity above would also hold for two guards that had
    both lost their guards, so the behaviour itself is pinned here."""
    for guard in (signals._signed_scalar, invalidation._signed_scalar):
        where = guard.__module__
        assert guard(True) is None, f"{where}: a bool is not a direction"
        assert guard(float("nan")) is None, f"{where}: nan carries no direction"
        assert guard(float("inf")) is None, f"{where}: inf is unbounded"
        assert guard(float("-inf")) is None, f"{where}: -inf is unbounded"
        assert guard(None) is None, f"{where}: None is not a number"
        assert guard({"classification": "HIGH"}) is None, f"{where}: a dict is not a number"
        assert guard(1.5) == 1.5, f"{where}: a finite number must be read"
        assert guard(0.0) == 0.0, f"{where}: zero is a readable balance point"
