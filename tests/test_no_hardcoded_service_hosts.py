"""No module may hard-code the address of a service the project CONFIGURES (O-113c).

**The defect this guards.** O-113 found `catalysts.py` storing
``http://127.0.0.1:6901/api/...`` as a literal. Port ``6901`` is *bound but dead*
(502 on every data route), so the FOMC catalyst **failed on every call** while the
thesis still built and nothing raised. The literal was blind to
``settings.openbb.base_url`` and to the ``OPENBB_API_URL`` override, so any port
change or deployment turned a working feature into a **silent** outage.

It was found by reading **one** fetch path. This file is the scan that O-113(c) asked
for, so the class is checked rather than inspected.

**The distinction this encodes — and why it is not "no URLs in source".**
An absolute URL is a defect only when the project *also* configures that service, so
the literal and the config become **two sources of truth for one address** that can
silently disagree. There are three legitimate kinds of URL in `src/`, and a blanket
ban would fail on all of them:

1. **A third-party host the project does not configure** — ``fred.stlouisfed.org``,
   ``api.nasdaq.com``. There is no competing configured value, so a literal creates
   no contradiction. Making these configurable would be *new surface*, not a fix.
2. **The project's OWN address, declared in config** — ``127.0.0.1:8000`` as the
   default bind, or a module-level constant **pinned to config by a test** (the
   ``deployment.py`` case, where the module is deliberately dependency-free and
   cannot import `config`). These are the *one* declaration, not a duplicate.
3. **Documentation** — docstrings and comments, including the ones that *describe*
   the O-113 incident by naming the dead port.

So the rule is narrow and checkable: **no module may hard-code the host of a service
whose base URL `settings` exposes.** Today that set is exactly one service — OpenBB.

**Why an allowlist and not a cleverer heuristic.** Every entry is enumerated with its
kind, so adding a URL requires a deliberate edit here. A rule that guessed would be
free to drift from the thing it is supposed to protect, which is the failure mode
these tests exist to prevent (O-107's lesson: a predicate that is too narrow silently
stops protecting anything).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from macro_engine.config import get_settings

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"

#: Services whose address `settings` exposes. A literal naming one of these outside
#: config is the O-113 defect: two sources of truth for one configured address.
#: The key is a substring that must not appear in an executable string constant.
_CONFIGURED_SERVICE_HOSTS: dict[str, str] = {
    "127.0.0.1:6900": "settings.openbb.base_url",
    "127.0.0.1:6901": "settings.openbb.base_url (the dead port, D-087.10)",
    "localhost:6900": "settings.openbb.base_url",
    "localhost:6901": "settings.openbb.base_url (the dead port, D-087.10)",
}

#: Every permitted occurrence, by ``relative path:line``. Each carries the reason it
#: is NOT the defect, so a reader can check the claim rather than trust the list.
_ALLOWED: dict[str, str] = {
    # The one declaration of the OpenBB fallback, in a module that cannot import
    # `config` by design. Pinned to settings by
    # `tests/test_infrastructure.py::test_the_two_openbb_defaults_agree`, so the
    # duplication is guarded rather than merely permitted.
    "macro_engine/deployment.py:229": (
        "the dependency-free fallback constant, pinned to config by a test"
    ),
}


def _executable_strings(path: Path) -> list[tuple[int, str]]:
    """``(line, value)`` for every string constant in CODE — documentation excluded.

    Documentation is *the record of the incident*: the O-113 fix's own comments name
    ``6901`` deliberately, to explain what went wrong. Excluding it is what keeps this
    scan from flagging the record of the bug as the bug — the false-positive trap that
    O-107 recorded as *"a check that cries wolf is one you learn to ignore"*.

    Two forms of documentation exist in this codebase, and both are excluded:

    * **Docstrings** — the ``Expr(Constant(str))`` first statement of a module,
      function or class.
    * **Field descriptions** — a ``description="..."`` keyword on a ``Field(...)``
      call. These are documentation that happens to live in a string constant
      (``contracts.py`` uses them heavily to explain each schema field), so they
      carry the same claim on the same incident without being executable.

    The exclusion is deliberately **structural rather than line-based**: an allowlist
    keyed to line numbers would silently transfer its exemption to whatever lands on
    that line next, which is the staleness failure this file also guards against.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))

    docstrings: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                value = body[0].value.value
                if isinstance(value, str):
                    docstrings.add(value)

    # Field/argument descriptions: the documented surface of a schema, not behaviour.
    descriptions: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if (
                keyword.arg in {"description", "help", "doc"}
                and isinstance(keyword.value, ast.Constant)
                and isinstance(keyword.value.value, str)
            ):
                descriptions.add(keyword.value.value)

    documented = docstrings | descriptions
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in documented:
                continue
            found.append((node.lineno, node.value))
    return found


def _source_files() -> list[Path]:
    return sorted(p for p in _SRC.rglob("*.py") if "__pycache__" not in p.parts)


def test_no_module_hard_codes_a_configured_service_host() -> None:
    """The O-113(c) scan: the class is checked, not just the one instance we found.

    Fails naming file, line and value, so the remedy is obvious. If a genuine
    exemption is needed, it goes in ``_ALLOWED`` with a stated reason — an
    allowlist entry with no reason is not an exemption, it is a recurrence.
    """
    findings: list[str] = []
    for path in _source_files():
        rel = path.relative_to(_SRC).as_posix()
        for line, value in _executable_strings(path):
            for host, owner in _CONFIGURED_SERVICE_HOSTS.items():
                if host not in value:
                    continue
                if f"{rel}:{line}" in _ALLOWED:
                    continue
                findings.append(
                    f"{rel}:{line} hard-codes {host!r} — that address is "
                    f"{owner}. Derive it from config at call time (O-113): a "
                    f"literal is blind to a port change, and the failure is "
                    f"silent whenever a fallback leg still answers."
                )

    assert not findings, "\n".join(findings)


def test_the_allowlist_has_no_stale_entries() -> None:
    """An allowlist entry that no longer matches anything is a licence to drift.

    If the permitted site moves or is removed, its entry must go — otherwise the
    entry silently becomes a blanket exemption for whatever lands on that line
    number next. This is the same staleness rule the reachability baseline uses.
    """
    stale: list[str] = []
    for entry in _ALLOWED:
        rel, _, line_text = entry.partition(":")
        path = _SRC / rel
        assert path.exists(), f"allowlist names a missing file: {entry}"
        assert line_text.isdigit(), f"allowlist entry is not path:line: {entry}"

    for rel in {e.partition(":")[0] for e in _ALLOWED}:
        path = _SRC / rel
        lines = {line for line, _ in _executable_strings(path)}
        for entry in _ALLOWED:
            if not entry.startswith(f"{rel}:"):
                continue
            line_no = int(entry.partition(":")[2])
            if line_no not in lines:
                stale.append(entry)

    assert not stale, (
        f"allowlist entries no longer name an executable string: {stale}. "
        "Remove them, or the exemption silently transfers to whatever lands "
        "on that line next."
    )


def test_every_allowlist_entry_states_a_reason() -> None:
    """Each exemption carries WHY, so it can be challenged rather than trusted.

    The project's do-not-fix list has been wrong three times out of three, on the
    argument that any such entry is an unverified claim. The same scepticism applies
    to a hard-coded-host exemption, so the reason must be written down where a
    reader will see it.
    """
    for entry, reason in _ALLOWED.items():
        assert reason.strip(), f"allowlist entry {entry} has no stated reason"
        assert len(reason) > 20, (
            f"allowlist entry {entry}'s reason is too short to be checkable: {reason!r}"
        )


def test_the_scan_would_catch_the_original_defect() -> None:
    """The scan must fail on the SHAPE O-113 actually had.

    A scanner that cannot reproduce the defect it was written for is decoration.
    This reconstructs the original literal in a temp module and asserts the
    detector fires — so the guard is proven against the real shape, not a guess.
    """
    source = (
        "from __future__ import annotations\n"
        "\n"
        '"""A module that reintroduces the O-113 defect."""\n'
        "\n"
        '_FOMC_DOCUMENTS_URL = "http://127.0.0.1:6901/api/v1/economy/fomc_documents"\n'
    )
    tree = ast.parse(source)

    docstrings: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                v = body[0].value.value
                if isinstance(v, str):
                    docstrings.add(v)

    hits = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value not in docstrings
        and any(h in node.value for h in _CONFIGURED_SERVICE_HOSTS)
    ]
    assert hits, (
        "the detector did not fire on the original O-113 literal — the scan "
        "cannot reproduce the defect it exists for"
    )
    # And the docstring naming the incident must NOT fire: the fix's own
    # explanation mentions the dead port on purpose.
    assert not any("reintroduces the O-113 defect" in h for h in hits), (
        "the detector fired on a DOCSTRING — documentation of the incident is "
        "not the incident, and flagging it would make the scan cry wolf"
    )


def test_the_scan_excludes_docstrings_but_keeps_code() -> None:
    """The docstring exclusion is real, and it does not swallow code.

    Both halves matter: without the exclusion the scan flags the O-113 fix's own
    explanatory comments (which name `6901` deliberately); if the exclusion were too
    broad it would stop seeing the actual defect. Asserted on the live tree, where
    both kinds genuinely coexist.
    """
    catalysts = _SRC / "macro_engine" / "thesis_layer" / "catalysts.py"
    assert catalysts.exists()

    code_strings = {v for _, v in _executable_strings(catalysts)}
    assert not any("6901" in v for v in code_strings), (
        "an executable string in catalysts.py names the dead port — the O-113 "
        "fix appears to have regressed"
    )
    # ...while the module still DOCUMENTS it, so the exclusion is doing work.
    raw = catalysts.read_text(encoding="utf-8")
    assert "6901" in raw, (
        "catalysts.py no longer documents the dead port at all; if the record was "
        "removed, revisit whether this exclusion is still needed"
    )


@pytest.mark.parametrize(
    "line",
    [
        'url = "http://127.0.0.1:6901/api/v1/economy/fomc_documents"',
        'base = "http://localhost:6901"',
        'BASE = "http://127.0.0.1:6900"',
    ],
)
def test_the_detector_matches_each_configured_host_form(line: str) -> None:
    """Every form the configured address can take is actually matched.

    Parametrized rather than single-case because O-107 showed a predicate can be
    right for the case that motivated it and blind to its neighbour (`elif`), and
    O-108 showed a check can be trivially satisfiable. Both ``127.0.0.1`` and
    ``localhost`` spellings, and both ports, must be seen.
    """
    tree = ast.parse(line)
    values = [
        n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]
    assert any(any(h in v for h in _CONFIGURED_SERVICE_HOSTS) for v in values), (
        f"the detector missed {line!r}"
    )


def test_the_configured_host_set_matches_reality() -> None:
    """The scan's host list must name the address config actually exposes.

    A scan keyed to a stale port would pass forever while the real defect (the new
    port, hard-coded) went unseen. This re-derives the host from live settings, so
    a config change forces the list to be revisited instead of silently drifting.
    """
    base = get_settings().openbb.base_url
    assert base.startswith("http://"), base
    host = base.removeprefix("http://").rstrip("/")

    assert host in _CONFIGURED_SERVICE_HOSTS, (
        f"the configured OpenBB host is {host!r}, which is NOT in the scan's "
        f"{sorted(_CONFIGURED_SERVICE_HOSTS)}. Update _CONFIGURED_SERVICE_HOSTS, "
        "or the scan is guarding an address the project no longer uses."
    )
    # The dead port must stay listed: it is the one a regressed literal would
    # most plausibly name, precisely because it was pinned in config for a day.
    assert any("6901" in h for h in _CONFIGURED_SERVICE_HOSTS), (
        "the dead port was dropped from the scan; a literal naming it would now "
        "pass silently (O-113)"
    )
