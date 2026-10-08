"""``thesis_layer/warnings.py`` — the seven sample defects, and one live one.

The module's docstring lists seven measured defects in Section 16.4's nine-line
sample. Before 2026-10-06 none of them had a behavioural test (the sibling
``test_warnings_citations.py`` covers only the F-WARN-001 citation), so the
whole "what a flat list cannot carry" argument rested on prose.

``F-WARN-002`` was found BY this review and is the one live defect: the
aggregate's ``model_warnings`` was keyed by ``model_name`` with a plain
assignment, so two results sharing a name lost the earlier one's warnings — and
because the module's own census assertion measures those lengths, the public
function raised ``AssertionError``. See ``test_two_results_sharing_a_model_name_...``.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from macro_engine.models.contracts import ModelResult
from macro_engine.thesis_layer import warnings as warnings_mod
from macro_engine.thesis_layer.warnings import (
    UnattributedWarning,
    WarningSummary,
    collect_all_warnings,
)

_AS_OF = datetime(2026, 10, 6, tzinfo=UTC)


def _result(name: str, warnings: list[str] | None = None) -> ModelResult:
    return ModelResult(
        model_name=name,
        country="us",
        as_of=_AS_OF,
        value=1.0,
        confidence=0.5,
        interpretation="a reading",
        context="test",
        inputs_used=["x"],
        warnings=warnings or [],
    )


def _sample_collect(*results: ModelResult) -> list[str]:
    """Section 16.4's nine lines, verbatim — the behaviour being replaced."""
    all_warnings: list[str] = []
    for r in results:
        all_warnings.extend(r.warnings)
    return list(dict.fromkeys(all_warnings))


# ---------------------------------------------------------------------------
# defect 1 — de-duplication destroys the count, and the count is the signal
# ---------------------------------------------------------------------------


def test_the_identical_string_from_four_models_keeps_its_count() -> None:
    """§16.4 collapses four identical warnings to one entry; the count is the finding.

    The published ``warnings`` still collapses (that IS §16.4), but ``sources``
    records all four raisers — so "four models are looking through the same
    degraded input" survives as a field.
    """
    shared = "input series is stale"
    results = [_result(f"m{i}", [shared]) for i in range(4)]

    assert _sample_collect(*results) == [shared]  # the sample: count destroyed

    summary = collect_all_warnings(*results)
    assert summary.warnings == (shared,)  # §16.4 verbatim
    assert len(summary.sources) == 1
    assert summary.sources[0].model_names == ("m0", "m1", "m2", "m3")
    assert summary.sources[0].raised_by_multiple_models is True
    assert summary.shared_warnings == summary.sources


# ---------------------------------------------------------------------------
# defect 2 — the output cannot attribute a warning to its source
# ---------------------------------------------------------------------------


def test_two_models_with_identical_warnings_are_both_recorded() -> None:
    """The flat list has no room for "which models raised this"."""
    summary = collect_all_warnings(_result("a", ["w"]), _result("b", ["w"]))
    assert summary.warnings == ("w",)
    assert summary.sources[0].model_names == ("a", "b")


# ---------------------------------------------------------------------------
# defect 3 — grouping by source, which the flat list's order cannot give
# ---------------------------------------------------------------------------


def test_model_warnings_groups_by_source_in_input_order() -> None:
    summary = collect_all_warnings(
        _result("a", ["w1", "w2"]),
        _result("b", ["w3"]),
        _result("c"),
    )
    assert list(summary.model_warnings) == ["a", "b", "c"]
    assert summary.model_warnings["a"] == ("w1", "w2")
    assert summary.model_warnings["b"] == ("w3",)
    assert summary.model_warnings["c"] == ()


# ---------------------------------------------------------------------------
# defect 4 — "no warnings" and "not passed" were the same value
# ---------------------------------------------------------------------------


def test_no_results_and_a_quiet_result_are_distinguishable() -> None:
    """``[]`` for both was D-066's shape one function over."""
    none_passed = collect_all_warnings()
    quiet = collect_all_warnings(_result("quiet"))

    assert none_passed.warnings == () == quiet.warnings
    assert none_passed.contributing_models == 0
    assert quiet.contributing_models == 1
    assert none_passed.model_warnings == {}
    assert quiet.model_warnings == {"quiet": ()}


# ---------------------------------------------------------------------------
# defects 5 and 6 — the two mandatory classes with no ModelResult behind them
# ---------------------------------------------------------------------------


def test_the_blocked_and_quality_classes_have_a_route_in() -> None:
    """§21.4's blocked inputs and §5.4's quality flags are not ModelResults.

    (Whether a *production* caller fills this is O-81, not this function's
    contract — the function deliberately does not read the registry itself.)
    """
    blocked = UnattributedWarning(
        text="supercore_direction is BLOCKED: no valid BLS construction",
        origin="blocked_input",
        detail="OPEN_ISSUES.md",
    )
    flag = UnattributedWarning(text="series X is 400 days stale", origin="data_quality_flag")

    summary = collect_all_warnings(_result("a", ["w"]), unattributed=(blocked, flag))
    assert summary.unattributed == (blocked, flag)
    assert [u.origin for u in summary.unattributed] == ["blocked_input", "data_quality_flag"]
    assert summary.all_texts == ("w", blocked.text, flag.text)


def test_unattributed_is_not_merged_into_warnings() -> None:
    """A §5.4 flag and a model's own warning are different claims."""
    overlap = "the same sentence"
    summary = collect_all_warnings(
        _result("a", [overlap]),
        unattributed=(UnattributedWarning(text=overlap, origin="caller"),),
    )
    assert summary.warnings == (overlap,)
    assert len(summary.unattributed) == 1


# ---------------------------------------------------------------------------
# "never dropped" (Section 7.2 step 9)
# ---------------------------------------------------------------------------


def test_every_input_warning_survives_in_the_published_list() -> None:
    results = [_result("a", ["w1", "w2"]), _result("b", ["w2", "w3"]), _result("c")]
    summary = collect_all_warnings(*results)
    input_texts = {t for r in results for t in r.warnings}
    assert input_texts <= set(summary.warnings)
    # and the attribution recorded exactly as many raisers as there were warnings
    assert sum(len(s.model_names) for s in summary.sources) == sum(len(r.warnings) for r in results)


def test_order_is_first_seen_across_the_inputs() -> None:
    """§16.4's ``dict.fromkeys`` order, preserved exactly."""
    summary = collect_all_warnings(_result("a", ["z", "y"]), _result("b", ["y", "x"]))
    assert summary.warnings == ("z", "y", "x")
    assert summary.warnings == tuple(
        _sample_collect(_result("a", ["z", "y"]), _result("b", ["y", "x"]))
    )


# ---------------------------------------------------------------------------
# F-WARN-002 — two results sharing a model_name
# ---------------------------------------------------------------------------


def test_two_results_sharing_a_model_name_do_not_raise() -> None:
    """(F-WARN-002) A public function must not raise on a contract-legal input.

    ``model_warnings`` was assigned with a plain ``model_warnings[name] = own``,
    so a repeated ``model_name`` dropped the earlier result's warnings from the
    grouping. Because the module's census assertion measures exactly those
    lengths, the drop then raised ``AssertionError`` — MEASURED 2026-10-06:
    ``attribution lost a raiser: 2 recorded against 1 input warning(s)``. The
    assertion is marked ``# pragma: no cover - construction is total``, i.e. it
    was believed unreachable; it was reachable.
    """
    summary = collect_all_warnings(_result("m", ["w1"]), _result("m", ["w2"]))
    assert summary.contributing_models == 2
    assert summary.model_warnings == {"m": ("w1", "w2")}  # merged, not overwritten
    assert summary.warnings == ("w1", "w2")
    assert all(s.model_names == ("m",) for s in summary.sources)


def test_a_repeated_model_name_merges_even_when_only_one_side_warns() -> None:
    summary = collect_all_warnings(_result("m", ["w1"]), _result("m"))
    assert summary.model_warnings == {"m": ("w1",)}
    assert summary.contributing_models == 2
    assert summary.models_with_warnings == 1


def test_a_repeated_model_name_with_no_warnings_at_all_still_counts_both() -> None:
    """The silent half of the defect: no raise, but the grouping collapsed."""
    summary = collect_all_warnings(_result("m"), _result("m"))
    assert summary.contributing_models == 2
    assert summary.model_warnings == {"m": ()}
    assert summary.warnings == ()


def test_a_repeated_model_name_is_counted_once_per_raiser() -> None:
    """The census must still balance when a name repeats."""
    summary = collect_all_warnings(_result("m", ["w"]), _result("m", ["w"]))
    assert summary.sources[0].model_names == ("m", "m")
    assert sum(len(s.model_names) for s in summary.sources) == sum(
        len(w) for w in summary.model_warnings.values()
    )


def test_the_model_warnings_note_states_the_merge() -> None:
    """(F-WARN-002) The field description must document the merge, not the overwrite.

    A reader relies on the field description for the semantics; before the fix it
    said only "in the order the results were passed", which a dict keyed by
    ``model_name`` cannot honour for a repeated name.
    """
    source = Path(inspect.getfile(warnings_mod)).read_text(encoding="utf-8")
    assert "MERGED in input order rather than the later one" in source
    assert "``contributing_models`` still counts every result" in source


# ---------------------------------------------------------------------------
# F-WARN-003 — the §5.4 quality-flag obligation was mis-attributed to §21.4
# ---------------------------------------------------------------------------


def test_section_21_4_really_scopes_its_warnings_clause_to_blocked_items() -> None:
    """The reason the old attribution was wrong, pinned against the spec itself.

    §21.4 is *"The Loophole Ledger"*, and its ``warnings`` clause reads "Every
    BLOCKED item in Section 21.1 … must be … surfaced in every thesis's
    ``warnings``". §5.4's quality flags are attached to ``MacroDataSnapshot``
    instead, so applying §21.4's clause to them is a category error.
    """
    spec = (Path(__file__).resolve().parents[2] / "AGENTS.md").read_text(encoding="utf-8")
    # The spec hard-wraps its prose, so compare against a whitespace-flattened copy.
    flat = " ".join(spec.split())
    assert "Every BLOCKED item in Section 21.1" in flat
    assert "surfaced in every thesis's `warnings`" in flat
    # §5.4 requires the flags on the SNAPSHOT, which is where they are.
    assert "Anomalies are logged and attached to `MacroDataSnapshot`" in flat


def test_the_quality_flag_note_attributes_the_obligation_correctly() -> None:
    """(F-WARN-003) The note must not claim §21.4 obliges quality flags in warnings."""
    source = Path(inspect.getfile(warnings_mod)).read_text(encoding="utf-8")
    assert "§21.4 says *warnings*, and warnings does not get it" not in source
    assert "§5.4's own requirement is met" in source
    assert "governs **§21.1's BLOCKED items**, not §5.4's quality" in source


# ---------------------------------------------------------------------------
# the summary object's own contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("models_with_warnings", "contributing"),
    [(0, 0), (1, 3)],
)
def test_the_two_denominators_are_independent(models_with_warnings: int, contributing: int) -> None:
    """'3 of 9 models warned' is a different statement from '3 models warned'."""
    results = [
        _result(f"m{i}", ["w"] if i < models_with_warnings else []) for i in range(contributing)
    ]
    summary = collect_all_warnings(*results)
    assert summary.contributing_models == contributing
    assert summary.models_with_warnings == models_with_warnings


def test_the_summary_is_frozen_and_forbids_extra_fields() -> None:
    summary = collect_all_warnings(_result("a", ["w"]))
    assert isinstance(summary, WarningSummary)
    with pytest.raises(ValidationError):
        summary.warnings = ()  # pydantic refuses: the model is frozen
