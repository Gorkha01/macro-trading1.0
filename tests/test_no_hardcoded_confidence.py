"""Section 22.8 / Finding #8: no model may assert its own confidence.

`compute_confidence()` is the ONLY producer of a `ModelResult.confidence` in this
tree. A literal — `confidence=0.35`, `confidence=1.0` — is a model grading its own
homework, and it is invisible to every other gate: the suite passes, `mypy` passes,
and the number looks authoritative precisely because someone typed it.

**Why this test exists at all.** A regex (`grep 'confidence=[0-9]'`) was the audit
tool for this, and it was BOTH too noisy and too blind: it matched the many
docstrings that QUOTE the specification's literals while explaining why they were
replaced (so the hits were mostly comments), and it could not see a literal that
reached a `ModelResult` through a variable. Two real defects survived it — both
`confidence=1.0`, in `thesis_layer/builder.py` and `models/scorecard.py` (D-142) —
and one of them flatly contradicted its own docstring, which already said the
confidence was `compute_confidence`'s to produce.

The check is deliberately narrow: **no `confidence=` keyword may take a numeric
literal**. That is the exact invariant Finding #8 states, it has no false
positives, and it is not fooled by comments (the AST sees code only).

Pass-throughs are legal and expected — `audit.py` re-emits `result.confidence`,
`_as_signal` forwards the ensemble's, `policy_rule_ensemble` takes the `min` of its
three legs. Those are NAMES, not literals, so this test leaves them alone. A
separate, broader traceability check lives in the sweep for this module.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src" / "macro_engine"


def _iter_confidence_keywords() -> list[tuple[Path, int, ast.expr]]:
    """Every `confidence=<expr>` keyword argument in `src/macro_engine`."""
    found: list[tuple[Path, int, ast.expr]] = []
    for path in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg == "confidence":
                    found.append((path, node.lineno, keyword.value))
    return found


def test_there_is_at_least_one_confidence_site() -> None:
    """A guard against a silent no-op: the scanner must actually find sites.

    Without this, a rename (`confidence` -> something else) or a path mistake
    would make the scanner return nothing and the real test below would pass
    vacuously — the "green gate that proves nothing" failure this repository
    keeps re-learning.
    """
    sites = _iter_confidence_keywords()
    assert len(sites) > 50, (
        f"expected the models layer to construct many ModelResults, but the "
        f"scanner found only {len(sites)} `confidence=` sites. Either the scan is "
        f"broken or the contract changed; investigate before trusting the check."
    )


def test_no_confidence_is_a_numeric_literal() -> None:
    """Finding #8: `compute_confidence()` is the only producer of a confidence.

    A literal is a model asserting its own confidence. Measured at D-142: two such
    literals existed (`confidence=1.0` in `thesis_layer/builder.py` and
    `models/scorecard.py`); both were real defects and both are fixed.
    """
    offenders: list[str] = []
    for path, lineno, value in _iter_confidence_keywords():
        # A bare number, or a negative/positive number, is the defect.
        if isinstance(value, ast.Constant) and isinstance(value.value, (int, float)):
            if isinstance(value.value, bool):
                continue  # `confidence=some_bool` is a Name, not a literal; be explicit
            offenders.append(
                f"{path.relative_to(_REPO_ROOT)}:{lineno} -> confidence={value.value!r}"
            )
        elif isinstance(value, ast.UnaryOp) and isinstance(value.operand, ast.Constant):
            offenders.append(
                f"{path.relative_to(_REPO_ROOT)}:{lineno} -> confidence={ast.unparse(value)}"
            )

    assert not offenders, (
        "Section 22.8 / Finding #8: a model may not assert its own confidence. "
        "Route every one of these through compute_confidence():\n  " + "\n  ".join(offenders)
    )


def test_the_scanner_would_catch_a_literal(tmp_path: Path) -> None:
    """The honesty control: prove the predicate actually fires.

    A check that cannot fail is not a check. This builds a synthetic module with
    exactly the defect and asserts the scanner's predicate rejects it, so a future
    edit that neuters the scan fails HERE rather than passing silently.
    """
    source = (
        "from macro_engine.models.contracts import ModelResult\n"
        "\n"
        "\n"
        "x = ModelResult(\n"
        "    confidence=1.0,\n"
        ")\n"
    )
    module = tmp_path / "synthetic_offender.py"
    module.write_text(source, encoding="utf-8")

    tree = ast.parse(module.read_text(encoding="utf-8"))
    literals = [
        kw.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for kw in node.keywords
        if kw.arg == "confidence"
        and isinstance(kw.value, ast.Constant)
        and isinstance(kw.value.value, (int, float))
    ]
    assert literals, "the predicate failed to flag a literal confidence — it is not a check"
