"""LAW-1 config-leaf auditor: every config leaf must carry provenance.

REVIEW_PROMPT section 1A LAW 1 requires that every config leaf carry a unit and
provenance, and that each leaf be *provable live*: changing it must change
behaviour. This script enforces the part that can be checked without executing
the engine -- that no tunable leaf is a bare number with no stated origin.

The convention this enforces is the one ``config/settings.yaml`` already
declares at the top of the file: every tunable parameter is wrapped in a
``{value, calibration_status, note}`` envelope so that a reader can tell,
without opening the code, which numbers are institutional facts and which are
uncalibrated placeholders. A bare scalar in the tunable tree breaks that
promise silently, because Pydantic will happily accept it.

Scope: ``settings.yaml`` only. ``series_registry.yaml`` is a different contract
(endpoint descriptors validated by ``SeriesRegistry``), and ``logging.yaml``
carries no tunable parameters.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = REPO_ROOT / "config" / "settings.yaml"

# Mirrors config.py::_VALID_CALIBRATION. Duplicated deliberately: this script
# must be runnable without importing the package, so that it can audit config
# that would fail to load.
VALID_CALIBRATION: frozenset[str] = frozenset(
    {
        "institutional_fact",
        "institutional_convention",
        "conventional",
        "mechanical_rule",
        "fitted_assumption",
        "judgment_parameters",
        "uncalibrated_illustrative",
    }
)

# Keys that are structure, not tunable parameters.
STRUCTURAL_KEYS: frozenset[str] = frozenset({"version"})

ENVELOPE_KEYS: frozenset[str] = frozenset(
    {"value", "calibration_status", "note", "source_reference"}
)


class Audit:
    """Accumulates the results of one walk over the settings tree."""

    def __init__(self) -> None:
        """Start an empty audit."""
        self.problems: list[str] = []
        self.leaves: list[str] = []
        self.identifier_lists: list[str] = []


def _is_envelope(node: Any) -> bool:
    """True if a mapping declares a calibration status.

    Two shapes exist in settings.yaml and both are legitimate:

    * scalar envelope  -- ``{value, calibration_status, note}``; and
    * member envelope  -- ``{calibration_status, note, <members>...}`` where the
      members are named sub-fields instead of a single ``value`` (used by the
      Beveridge curve and the thesis-type route table).

    Keying on ``calibration_status`` rather than on ``value`` is what keeps the
    second shape from being reported as a pile of bare scalars.
    """
    return isinstance(node, dict) and "calibration_status" in node


def walk(node: Any, path: str, audit: Audit, covered: bool = False) -> None:
    """Recursively audit one node.

    ``covered`` means an enclosing envelope already stated the provenance for
    this subtree. A typed record nested inside a calibrated envelope -- a
    Beveridge curve point, a drawdown tier, a thesis-type route -- inherits
    that statement; requiring a second one per field would produce one
    calibration_status per number and no additional information. Provenance is
    asserted where a human chooses a value, not where a schema names a field.
    """
    if isinstance(node, dict):
        if _is_envelope(node):
            audit.leaves.append(path)
            status = node.get("calibration_status")
            if status not in VALID_CALIBRATION:
                audit.problems.append(
                    f"{path}: calibration_status {status!r} is not a permitted value"
                )
            note = str(node.get("note") or "").strip()
            if not note:
                audit.problems.append(f"{path}: no provenance note")
            if "value" in node:
                audit_value(node.get("value"), path + ".value", audit)
            for key, child in node.items():
                if key in ENVELOPE_KEYS:
                    continue
                walk(child, f"{path}.{key}", audit, covered=True)
            return
        for key, child in node.items():
            if key in STRUCTURAL_KEYS:
                continue
            walk(child, f"{path}.{key}" if path else str(key), audit, covered=covered)
        return
    if isinstance(node, list):
        # A list of plain names enumerates identifiers (snapshot field names,
        # country codes). Those are structure: there is no number to calibrate
        # and no unit to state. They are recorded separately so a reviewer can
        # see they were exempted on purpose rather than missed.
        if node and all(isinstance(item, str) for item in node):
            audit.identifier_lists.append(path)
            return
        for index, child in enumerate(node):
            walk(child, f"{path}[{index}]", audit, covered=covered)
        return
    if covered:
        return
    audit.problems.append(f"{path}: bare value {node!r} with no calibration envelope")


def audit_value(value: Any, path: str, audit: Audit) -> None:
    """An envelope's `value` may itself be a nested mapping or list."""
    if isinstance(value, dict):
        # A mapping of names to bare numbers (a weight table) carries no
        # per-entry provenance, so each entry is unattributable.
        if value and all(not isinstance(v, dict) for v in value.values()):
            audit.problems.append(
                f"{path}: mapping of {len(value)} bare scalars carries no per-entry provenance"
            )
            return
        for key, child in value.items():
            walk(child, f"{path}.{key}", audit)
        return
    if isinstance(value, list):
        # A list of scalars under one envelope is covered by that envelope's
        # single calibration statement (e.g. two VaR confidence levels sharing
        # one provenance note). Only structured items need their own envelope.
        if value and all(not isinstance(item, (dict, list)) for item in value):
            return
        for index, child in enumerate(value):
            walk(child, f"{path}[{index}]", audit)


def main() -> int:
    """Audit config/settings.yaml; return 0 only if every leaf is attributable."""
    if not SETTINGS_PATH.exists():
        print(f"MISSING: {SETTINGS_PATH}")
        return 1
    document = yaml.safe_load(SETTINGS_PATH.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        print("settings.yaml did not parse to a mapping")
        return 1

    audit = Audit()
    walk(document, "", audit)

    print(f"config leaves audited: {len(audit.leaves)}")
    print(f"identifier lists exempted: {len(audit.identifier_lists)}")
    print(f"problems: {len(audit.problems)}")
    for problem in audit.problems:
        print(f"  - {problem}")
    return 0 if not audit.problems else 1


if __name__ == "__main__":
    sys.path.insert(0, str(REPO_ROOT / "src"))
    raise SystemExit(main())
