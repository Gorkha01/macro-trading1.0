"""Guards for ``tools/sweep_health.py``'s anchor reader (D-086).

Why this file exists
--------------------
``sweep_health.py`` decides whether a sweep's anchors still resolve. Two of its
functions read target files, and **they disagreed about how to read them**:

* ``_own_target_check`` reads with ``candidate.read_text(encoding="utf-8")``,
  which applies universal-newline translation.
* ``_native``'s 3-tuple resolver read with
  ``candidate.read_bytes().decode("utf-8")``, which does not.

The tool's own ``_own_target_check`` docstring records this exact defect —
"**The read must translate newlines, and the shipped version did not**" — and
describes the measured consequence on CRLF files: every LF anchor matches zero
times. **The fix was applied to one function and left un-applied in the other**,
which is what makes this a guard worth having rather than a bug worth fixing
once.

The two readers disagreeing is worse than either being wrong, because it
manufactures findings in a *specific, misleading direction*: the resolver
concludes the anchor lives in ``candidates[0]``, then the checker — reading
correctly — finds the anchor is not in that file and reports it
**ABSENT in the wrong file**. Measured on the tree: three mutants (M8a, M8b
targeting a CRLF ``snapshot_builder.py``; M8e targeting a CRLF ``config.py``)
were reported ABSENT while their anchors were present in the file the sweep
actually mutates.

These guards are structural (``ast``) rather than textual, per lesson 5bf: a
substring guard would be a guard on the formatter. The property is *which
function is called to read a file*, which is a property of the source.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_TOOL = Path("tools/sweep_health.py")
_SOURCE = _TOOL.read_text(encoding="utf-8")
_TREE = ast.parse(_SOURCE)


def _function(name: str) -> ast.FunctionDef:
    """The AST node of a top-level function in ``sweep_health.py``."""
    for node in _TREE.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"no top-level function named {name!r} in {_TOOL}")


#: Every method that reads a file's whole contents. A function that reads a
#: sweep target must reach it through exactly one of these, and the two differ
#: only in whether newlines are translated.
_FILE_READERS = frozenset({"read_text", "read_bytes", "decode"})

#: The reader that translates newlines. Any function that reads a *sweep target*
#: must use it.
_TRANSLATING_READER = "read_text"

#: The reader that does not. Named so the failure message can say what is wrong
#: rather than just that something is.
_BYTES_READER = "decode"


def _reader_calls(node: ast.AST) -> set[str]:
    """Which file-reading methods ``node`` calls, out of ``_FILE_READERS``.

    Filtered to the reader set deliberately: an unfiltered "any attribute call"
    extractor returns ``{"append", "startswith"}`` for a function that reads no
    files at all, which would make the guards below unable to distinguish a
    function that reads with the wrong reader from one that reads nothing.
    """
    found: set[str] = set()
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr in _FILE_READERS
        ):
            found.add(child.func.attr)
    return found


@pytest.mark.parametrize("function_name", ["_own_target_check", "_native"])
def test_every_target_reader_translates_newlines(function_name: str) -> None:
    """A sweep target must be read with the same newline handling the sweep uses.

    Sweeps anchor their ``old`` strings with ``\\n`` and read their sources with
    ``Path.read_text``, which translates CRLF to LF. A checker that reads the
    same file as raw bytes sees ``\\r\\n``, so every anchor matches zero times on
    a CRLF file — and ``src/`` contains CRLF files.

    This asserts the *call* is present, structurally. A mutant that swaps
    ``read_text`` for ``read_bytes().decode(...)`` in either function fails here.
    """
    calls = _reader_calls(_function(function_name))

    assert _TRANSLATING_READER in calls, (
        f"{function_name} does not read targets with `{_TRANSLATING_READER}`, so "
        "CRLF targets will report every anchor ABSENT"
    )


def test_the_two_readers_do_not_disagree() -> None:
    """The resolver and the checker must use the SAME reader.

    This is the specific defect D-086 found: ``_own_target_check`` translated
    newlines and ``_native`` did not, so the resolver assigned an anchor to the
    wrong candidate file and the checker then truthfully reported it ABSENT
    there. Either reader being wrong is a bug; the two *disagreeing* turns that
    bug into a confidently-reported finding about the wrong file.

    Asserted as an equality between the two functions' reader surfaces rather
    than as a property of either alone, so the guard survives a future refactor
    that renames or extracts the reader — as long as the two agree, the check is
    coherent.
    """
    resolver = _reader_calls(_function("_native"))
    checker = _reader_calls(_function("_own_target_check"))

    for reader in (_TRANSLATING_READER, _BYTES_READER):
        assert (reader in resolver) == (reader in checker), (
            f"the two target readers disagree about `{reader}`: "
            f"_native={reader in resolver}, _own_target_check={reader in checker}"
        )


def test_the_guards_can_actually_fail() -> None:
    """The checks above must be able to fail, or they are decoration.

    A structural guard asserting "this call appears somewhere" passes trivially
    if the extractor is broken — it would return the same set for every function.
    This pins that the extractor distinguishes functions: ``_legacy_targets``
    reads no files at all, so its reader surface must be empty.
    """
    assert _reader_calls(_function("_legacy_targets")) == set(), (
        "the reader extractor reports calls for a function that reads no files, "
        "so the guards above are not measuring what they claim"
    )
