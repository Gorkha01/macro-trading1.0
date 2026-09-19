"""Type-strictness guards for the thesis layer (D-067).

Why this file exists
--------------------
Two mutants in the D-067 sweep (`scripts/mutation_warnings.py`) **survived the
whole behavioural selection** in ``tests/thesis_layer/test_warnings.py`` and are
not inert. Both are caught only by a **static** check:

``M2`` — ``raisers: dict[str, list[str]]`` narrowed to ``dict[str, str]``.
The ``.append`` becomes a runtime ``AttributeError``, but it sits inside
``collect_all_warnings``, so the failure is raised from *the function under
test* rather than from an assertion. pytest reports it as an ordinary failure
and ``mypy --strict`` reports it as two errors (``"str" has no attribute
"append"``, and a bad ``setdefault`` default). A type gate kills it; no
behavioural test can, because there is no value the function can return.

``M4`` — the raiser census (``models_with_warnings``) dropped. This is the
**D-067 lesson-65 flag**: an internal ``if``/``raise`` guard with *no reachable
input* — every warning belongs to exactly one model, so "a model warned but
contributed no raiser" cannot occur. Deleting the guard changes no observable
value, and deleting the *census* around it changes no observable value either.
The guard is deliberately kept as an assertion of intent, so it must not be
reported as an inert survivor; it is exempted in the sweep, and the exemption
rests on it being genuinely unreachable rather than merely untested.

The general rule these two establish
------------------------------------
**A mutation that changes a type annotation, or removes a line whose effect no
value can express, is killed by a different gate than the one the sweep runs.**
Rather than widen the sweep to run mypy per mutation (nine extra ``mypy --strict``
invocations on the whole ``src`` tree, which the project's own gate already does
once), the strictness is pinned here — as a test, so it runs in the normal gate
and fails in the normal way when someone loosens the annotation.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WARNINGS = REPO / "src/macro_engine/thesis_layer/warnings.py"


def _annotation_of_assignment(path: Path, name: str) -> str:
    """The rendered annotation of ``name``'s first ``AnnAssign`` in ``path``.

    Parsed rather than regex-matched: a line-walk matches ``name:`` inside a
    comment or a string, which is the same defect D-064's ``enclosing_symbol``
    was written to avoid.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
        ):
            return ast.unparse(node.annotation)
    raise AssertionError(f"no annotated assignment for {name!r} in {path.name}")


def test_the_raiser_map_keeps_one_entry_per_model_not_per_text() -> None:
    """``raisers`` must be ``dict[str, list[str]]`` — a list, never a scalar.

    The single most important annotation in the file: it is what lets
    ``WarningSource.model_names`` hold *every* model that raised a text. Shrink
    it to ``dict[str, str]`` and the whole defect-1/defect-2 repair collapses
    back to the flat list's information content — while every behavioural test
    still passes, because the mutant dies at ``.append`` with an
    ``AttributeError`` rather than at one of my assertions.

    That asymmetry is why this is a test of the **source** rather than of the
    value: the value cannot exist under the mutant.
    """
    annotation = _annotation_of_assignment(WARNINGS, "raisers")
    assert annotation == "dict[str, list[str]]", (
        f"raisers is annotated {annotation!r}; it must stay dict[str, list[str]] "
        f"so a text can record EVERY model that raised it (D-067 defects 1 and 2). "
        f"A scalar value type passes the behavioural selection."
    )
    assert not annotation.startswith("dict[str, str]"), (
        "a text->single-model map is the flat list's information content again"
    )


def test_every_model_result_is_in_the_denominator() -> None:
    """The count of passed results must be ``len(model_results)``, not a tally.

    ``contributing_models`` is the denominator that makes ``warnings`` readable
    as a severity ("3 of 9 models warned"). It is computed from the argument
    length precisely so it cannot drift; a denominator that were incremented in
    the loop body could be skipped by a ``continue`` and report a smaller
    thesis than the caller built.
    """
    source = WARNINGS.read_text(encoding="utf-8")
    assert "contributing_models=len(model_results)" in source, (
        "contributing_models must be the argument length — an incremented "
        "counter can be skipped by a `continue` (D-067, defect 4)"
    )

    # And the numerator's guard must be a guard: the denominator is only
    # meaningful if a warning-free model stays out of it.
    assert "if not own:\n            continue\n        models_with_warnings += 1" in source, (
        "the warning-free guard keeps quiet models out of models_with_warnings; "
        "without it the numerator equals the denominator and '3 of 9 warned' "
        "degrades into '9 of 9 warned'"
    )


def test_the_internal_guards_are_unreachable_by_design() -> None:
    """The two census ``raise``s are assertions of intent with no reachable input.

    This is the **lesson-65 flag** (D-067): ``collect_all_warnings`` builds
    ``warnings`` and ``sources`` from one dict, and appends exactly one raiser
    per input warning, so neither ``AssertionError`` can fire. They are kept
    because they *document the invariant* a summariser must not violate, and
    because a future edit that makes them reachable would otherwise be silent.

    The test pins both that they exist and that they are unreachable, so that
    "we have an assertion" is not mistaken for "we have coverage":
    a guard nobody can trigger is not a test, and a sweep that deletes one
    reports an inert survivor.
    """
    source = WARNINGS.read_text(encoding="utf-8")
    assert source.count("raise AssertionError(") == 2, (
        "the two internal censuses (warnings/sources length, and the raiser "
        "total) must both be present"
    )

    # Unreachability is a claim about the CONSTRUCTION, so it is checked
    # structurally: `warnings` and `sources` are built from the same `raisers`,
    # and every input warning appends exactly one raiser.
    assert "warnings = tuple(raisers)" in source
    assert "for text, names in raisers.items()" in source
    assert "raisers.setdefault(text, []).append(result.model_name)" in source, (
        "exactly one raiser per input warning is what makes the raiser census "
        "unreachable; a second append or a conditional one would make it live"
    )


def test_the_length_census_is_present() -> None:
    """A guard is only useful if it is still there to be tripped by a future edit."""
    assert "if len(summary.warnings) != len(summary.sources):" in WARNINGS.read_text(
        encoding="utf-8"
    )
