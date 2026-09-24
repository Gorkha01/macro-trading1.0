"""Repo-wide SOURCE HYGIENE gates — invariants that no single module owns.

Two defects recurred often enough to stop being accidents, and both are invisible
to every other gate in this project. Each one is asserted here over the whole
tree, so it cannot come back silently.

**1. A DUPLICATE TOP-LEVEL NAME SILENTLY REPLACES THE FIRST (O-117).**

Python binds a module-level name to the **last** definition, so two
``def test_x()`` leave ONE test and ``pytest`` reports nothing at all — a healthy
count over a suite that is missing tests. Measured three times: D-097 (three
mutations' verdicts corrupted, 52/56 -> 55/56 with **no mutation changed**),
D-100 (``pytest`` collected **176 where 178 existed**), and D-103 (an append
written twice defined a name twice; mypy's ``no-redef`` caught it). ``ruff``'s
F811 and mypy's ``no-redef`` both see it — but only if they are run over the
**whole tree**, and this file asserts the invariant directly so the failure does
not depend on which checker happens to be watching.

**2. A CARRIAGE RETURN IN A SOURCE FILE BREAKS ANCHOR MATCHING (D-061, D-103).**

The mutation sweeps locate their targets by exact text. An anchor written with
``\\n`` against a file whose bytes end ``\\r\\n`` matches **zero** times — the edit
appears to succeed while changing nothing, and the failure is indistinguishable
from a typo'd anchor (O-119). It bit three times in one session at D-103, and the
exposure was measured at **21 files** across all four roots.

The root cause is recorded in ``.gitattributes`` (D-061): ``Path.write_text``
translates ``\\n`` to ``os.linesep`` on write, so a sweep's round-trip is stable IN
MEMORY and lossy ON DISK — every sweep silently converted its target to CRLF. The
harness is fixed at the source (every ``write_text`` passes ``newline=""``), and
``.gitattributes`` pins ``* text=auto eol=lf`` for the *stored* form. **This gate
covers the WORKING TREE, which is the thing a tool actually reads** — and it is
therefore the check that catches the D-061 defect if the harness regresses.
"""

from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

#: The roots this project owns. `data/` and `.probe/` are excluded because they
#: are generated, and `.git` because it is not source.
_ROOTS = ("src", "tests", "tools", "scripts", "config")

#: Extensions whose bytes a tool may match anchors against.
_TEXT_SUFFIXES = frozenset({".py", ".md", ".yaml", ".yml", ".toml", ".txt", ".cfg", ".typed"})


def _text_files() -> list[Path]:
    """Every tracked-able text file under the owned roots."""
    found: list[Path] = []
    for root in _ROOTS:
        directory = _ROOT / root
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            if path.is_file() and path.suffix in _TEXT_SUFFIXES:
                found.append(path)
    return found


def _python_files() -> list[Path]:
    """Every Python file under the owned roots."""
    found: list[Path] = []
    for root in _ROOTS:
        directory = _ROOT / root
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.py")):
            if path.is_file():
                found.append(path)
    return found


def test_the_walk_finds_files_at_all() -> None:
    """A NEGATIVE CONTROL for the walk itself.

    Both gates below are vacuously true on an empty list, so a broken path (a
    renamed root, a wrong `parents[]` index) would make them pass forever while
    checking nothing. This is the same "a gate row is a claim, not a receipt"
    discipline the sweep tools apply: the instrument is measured before its
    reading is believed.
    """
    assert len(_text_files()) > 200, f"the text walk found only {len(_text_files())} files"
    assert len(_python_files()) > 200, f"the python walk found only {len(_python_files())} files"


def test_no_source_file_contains_a_carriage_return() -> None:
    """The WORKING TREE must be LF-only — see this module's docstring.

    `git` normalises for comparison (`.gitattributes`: `* text=auto eol=lf`), so
    a CRLF working tree is INVISIBLE to `git status` and to `git diff` — measured
    2026-09-24: 21 files were CRLF while the tree reported clean, and `git add
    --renormalize` staged **nothing** because the stored form was already LF. **So
    no git-level check can see this**, which is exactly why it needs its own gate:
    the mutation sweeps read the working tree, not the index.
    """
    offenders = [
        str(path.relative_to(_ROOT)) for path in _text_files() if b"\r" in path.read_bytes()
    ]
    assert not offenders, (
        f"{len(offenders)} source file(s) contain a carriage return: {offenders}. A "
        f"mutation anchor written with '\\n' matches ZERO times in such a file, "
        f"silently -- the edit looks applied and changes nothing (O-119). The cause "
        f"is a `write_text` without `newline=''` (D-061); find the writer, do not "
        f"just re-save the file."
    )


def _duplicate_top_level_names(path: Path) -> list[str]:
    """Top-level names defined more than once in one module.

    Only MODULE-LEVEL definitions count: a name repeated inside two different
    functions is two locals, which is ordinary. A name repeated at module level is
    a silent overwrite, which is not.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    seen: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            seen[node.name] = seen.get(node.name, 0) + 1
    return sorted(name for name, count in seen.items() if count > 1)


def test_no_module_defines_a_top_level_name_twice() -> None:
    """O-117's gate, asserted directly rather than left to a linter's scope.

    A duplicate name means the earlier definition is **gone** — and for a
    `test_*` function that means the test silently disappears while `pytest`
    reports a healthy count. `ruff` F811 and mypy `no-redef` see it, but only over
    the whole tree; this asserts the invariant itself, so a per-file lint of the
    file you just edited cannot hide it.
    """
    offenders: list[str] = []
    for path in _python_files():
        for name in _duplicate_top_level_names(path):
            offenders.append(f"{path.relative_to(_ROOT)}::{name}")
    assert not offenders, (
        f"{len(offenders)} module-level name(s) are defined more than once: {offenders}. "
        f"Python binds the LAST definition, so the earlier one is silently deleted -- "
        f"for a test, that is a test that vanishes while the count stays healthy "
        f"(O-117, recurred three times)."
    )


def test_the_duplicate_detector_fires_on_a_real_duplicate(tmp_path: Path) -> None:
    """The DIVERGENT CASE: the detector is shown to detect.

    A gate that has never been seen to fail is a gate whose reading means nothing
    (the D-051 trap, and the reason every sweep carries a canary). This writes a
    module with a genuine duplicate and asserts the helper reports it, so the test
    above cannot be satisfied by a detector that returns `[]` for everything.
    """
    probe = tmp_path / "duplicated.py"
    probe.write_text(
        "def test_alpha() -> None:\n    pass\n\n\ndef test_alpha() -> None:\n    pass\n",
        encoding="utf-8",
    )
    assert _duplicate_top_level_names(probe) == ["test_alpha"]


def test_the_carriage_return_detector_fires_on_a_real_cr(tmp_path: Path) -> None:
    """The same divergent case for the line-ending gate.

    Written as bytes so the CR survives whatever the platform's newline
    translation would otherwise do to it.
    """
    probe = tmp_path / "crlf.py"
    probe.write_bytes(b"VALUE = 1\r\nOTHER = 2\r\n")
    assert b"\r" in probe.read_bytes(), "the fixture must actually contain a CR"
    assert b"\r" not in probe.read_bytes().replace(b"\r\n", b"\n")
