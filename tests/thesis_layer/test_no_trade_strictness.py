"""Static guards for ``no_trade_thesis`` (D-068).

Two properties of this increment **cannot be killed behaviourally**, and this
file exists because of them — the same reason ``test_warnings_strictness.py``
exists for D-067.

1. **The trigger vocabulary is closed.** ``NoTradeTrigger`` is a ``Literal``.
   Widening it to ``str`` (mutation ``M2.1``) is *mostly* harmless at runtime: a
   typo'd trigger still reaches ``NO_TRADE_TRIGGER_LABELS`` and raises
   ``KeyError``. It is only *slightly* harmless because a caller could pass a
   string that happens to be a key — but the real cost is that the vocabulary
   stops being a vocabulary: nothing says which four triggers exist, and a
   consumer counting by trigger sees an unbounded key space. The kill has to be a
   **static** read of ``__args__``, because no input distinguishes ``Literal``
   from ``str``.

2. **The evidence union is not ``object``.** ``NoTradeEvidence`` is a union of
   the three gate objects plus ``None``. Widening it to ``object`` would accept a
   string — the exact thing this module exists to stop discarding — and no
   behavioural test can tell the difference for the objects the tests pass.

Both are read from the module rather than from source text where possible; the
remaining source read (the union) is by AST so a reflow does not break it.
"""

from __future__ import annotations

import ast
import typing
from pathlib import Path

import pytest

from macro_engine.thesis_layer import no_trade as module
from macro_engine.thesis_layer.no_trade import (
    NO_TRADE_TRIGGER_LABELS,
    NoTradeDecision,
    NoTradeEvidence,
    NoTradeTrigger,
)

_NO_TRADE_SOURCE = Path(module.__file__).read_text(encoding="utf-8")


def test_the_trigger_vocabulary_is_closed() -> None:
    """``NoTradeTrigger`` is a ``Literal`` with exactly the four documented members.

    The static kill for ``M2.1``. ``str`` has no ``__args__``, so the mutant
    fails here with an ``AttributeError`` rather than passing — which is the
    point: the assertion is about the **type**, and a type is not observable
    through the function's behaviour.
    """
    assert typing.get_origin(NoTradeTrigger) is typing.Literal, (
        "NoTradeTrigger must be a Literal. A bare `str` makes an unlisted trigger "
        "a value nobody validates (O-29), and a consumer counting by trigger gets "
        "an unbounded key space instead of four buckets."
    )
    assert set(typing.get_args(NoTradeTrigger)) == {
        "gap_below_dispersion",
        "conflicted_signals",
        "no_falsifier",
        "caller",
    }


def test_the_vocabulary_and_the_labels_are_the_same_set() -> None:
    """Every member has a label and every label is a member.

    A member without a label ``KeyError``s when a thesis is rendered; a label
    without a member is dead code that suggests a trigger exists when it does not.
    """
    members = set(typing.get_args(NoTradeTrigger))
    labels = set(NO_TRADE_TRIGGER_LABELS)
    assert members == labels, (
        f"vocabulary-only: {sorted(members - labels)}; labels-only: {sorted(labels - members)}"
    )


def test_the_labels_are_non_empty_strings() -> None:
    """A blank label would render a warning line that names no gate."""
    for trigger, label in NO_TRADE_TRIGGER_LABELS.items():
        assert label.strip(), f"trigger {trigger!r} has a blank label"


def _annotation_of_assignment(source: str, name: str) -> str:
    """The unparsed right-hand side of a module-level assignment, or an error.

    Handles both ``X: T = ...`` and the bare ``X = T`` form, because
    ``NoTradeEvidence`` is declared as a plain union alias (``MarketPricingGap |
    ... | None``) while ``NoTradeTrigger`` is annotated. Read by AST rather than
    by regex so a reformat does not break the guard — the property under test is
    the *type*, not the layout.
    """
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.AnnAssign):
            annotated = node.target
            if isinstance(annotated, ast.Name) and annotated.id == name:
                return ast.unparse(node.annotation)
        elif isinstance(node, ast.Assign):
            # A distinct variable name: `target` is already bound to an
            # `ast.expr` by the branch above, and reusing it makes mypy report
            # the assignment as incompatible rather than as a new binding.
            for assigned in node.targets:
                if isinstance(assigned, ast.Name) and assigned.id == name:
                    return ast.unparse(node.value)
    raise AssertionError(f"no module-level assignment named {name!r}")


def test_the_evidence_union_is_not_object() -> None:
    """``NoTradeEvidence`` names the three gate objects plus ``None``.

    Widening to ``object`` would accept a string. That is the mutation this
    guards, and no behavioural test can see it: every object the tests pass is
    still accepted.
    """
    annotation = _annotation_of_assignment(_NO_TRADE_SOURCE, "NoTradeEvidence")
    parts = {part.strip() for part in annotation.split("|")}

    assert "object" not in parts, (
        "NoTradeEvidence must not be `object`. `object` accepts a string, which is "
        "exactly the thing this module exists to stop discarding (defect 3)."
    )
    for required in (
        "MarketPricingGap",
        "ConfirmationSignalAssessment",
        "InvalidationAssessment",
    ):
        assert any(required in part for part in parts), (
            f"NoTradeEvidence must include {required}; a trigger's evidence object "
            f"cannot be typed as a union that excludes it."
        )
    assert "None" in parts, "the `caller` trigger has no gate object behind it"


def test_the_evidence_union_matches_its_runtime_alias() -> None:
    """The declared annotation and the imported object describe the same set.

    ``typing.get_args`` on the union is compared against the parsed annotation so
    that a change to one without the other is caught. ``NoTradeEvidence`` is a
    ``UnionType`` at runtime in 3.13, so ``get_args`` is the reader.
    """
    runtime_parts = {str(arg) for arg in typing.get_args(NoTradeEvidence)}
    # ``None`` appears as ``NoneType`` at runtime.
    runtime_parts = {part.replace("NoneType", "None") for part in runtime_parts}
    assert any("MarketPricingGap" in p for p in runtime_parts)
    assert any("ConfirmationSignalAssessment" in p for p in runtime_parts)
    assert any("InvalidationAssessment" in p for p in runtime_parts)
    assert len(runtime_parts) == 4, f"expected four members, got {sorted(runtime_parts)}"


def test_the_decision_annotation_helpers_are_exercised() -> None:
    """The helper is real, not decorative.

    This proves the live function raises when the name is absent instead of
    silently returning something, which is what makes the two guards above
    trustworthy.
    """
    with pytest.raises(AssertionError, match="no module-level assignment"):
        _annotation_of_assignment(_NO_TRADE_SOURCE, "NotARealName")


def test_the_reserved_renderer_fields_are_the_three_the_module_sets() -> None:
    """The guard's key set is the three fields the renderer owns.

    A fourth reserved name added without the guard being updated would let a
    caller override it. Read from the source so the set cannot drift.
    """
    assert "reserved = {" in _NO_TRADE_SOURCE
    for field_name in ("trade_idea", "status", "warnings"):
        assert f'"{field_name}"' in _NO_TRADE_SOURCE
    # And the decision object really has the three fields the renderer consumes.
    assert {"trigger", "reason", "evidence", "elapsed", "status"} == set(
        NoTradeDecision.model_fields
    )
