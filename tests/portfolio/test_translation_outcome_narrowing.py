"""Narrowing tests for ``_as_translation_outcome`` (finding F-RB-001).

The line this replaces was::

    outcome: PositionTranslationOutcome = kelly_outcome  # type: ignore[assignment]

``kelly_outcome`` is ``str(kelly_value["outcome"])`` — a plain ``str`` — and
``PositionTranslationOutcome`` is a ``Literal`` of six strings. The suppression
declared the value to be of a type the checker knew it was not, and told the
checker not to look. The replacement checks membership at runtime and raises
naming the offending value, so the invariant is enforced rather than hidden.

Section 7 requires refusal tests that assert the error NAMES THE OFFENDING
FIELD/VALUE, so the rejection case asserts the unknown value appears in the
message rather than merely that an exception was raised.
"""

from __future__ import annotations

import pytest

from macro_engine.portfolio.risk_budget import (
    _TRANSLATION_OUTCOMES,
    _as_translation_outcome,
)


def test_every_literal_member_is_accepted() -> None:
    """Each member of the Literal narrows to itself.

    Hand-computed: the Literal has exactly six members, and each must survive
    the narrowing unchanged — a helper that rejected a legal member would break
    a live path.
    """
    expected = {
        "refused_not_a_trade",
        "refused_scenarios_uncalibrated",
        "refused_no_edge",
        "refused_no_risk_budget",
        "sized_by_kelly",
        "clipped_by_position_limit",
    }
    assert set(_TRANSLATION_OUTCOMES) == expected
    for member in sorted(expected):
        assert _as_translation_outcome(member) == member


def test_the_two_values_the_kelly_gate_actually_produces_are_accepted() -> None:
    """The two verdicts that reach this call site both narrow.

    Hand-computed from the call site: the ``no_edge`` branch returns early, so
    the only values arriving here are the two below.
    """
    for value in ("sized_by_kelly", "clipped_by_position_limit"):
        assert _as_translation_outcome(value) == value


def test_unknown_outcome_is_refused_and_names_the_value() -> None:
    """An unknown verdict raises naming the value, rather than being suppressed."""
    with pytest.raises(ValueError) as excinfo:
        _as_translation_outcome("no_edge")
    message = str(excinfo.value)
    assert "no_edge" in message
    assert "PositionTranslationOutcome" in message


def test_empty_string_is_refused() -> None:
    """An empty verdict is not a member and must not pass silently."""
    with pytest.raises(ValueError) as excinfo:
        _as_translation_outcome("")
    assert "''" in str(excinfo.value)
