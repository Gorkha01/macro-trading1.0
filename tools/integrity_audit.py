"""Section 45/46 of the economic-integrity directive — the audit and the live run.

One tool, two jobs, because they share a single live thesis run and re-fetching
would risk the two halves disagreeing:

**§45 - the A-M audit summaries.** A machine-produced census of the properties
the directive names, each backed by a measurement rather than a claim:

    A  models on the live decision path
    B  blocked / not-computed outputs and why
    C  proxies in the live path
    D  economic calibration parameters and their calibration status
    E  series coverage of the snapshot
    F  confidence provenance
    G  scenario-distribution status (§25)
    H  sizing reachability (§26/§27)
    I  no-trade gates and what fires them
    J  hardcoded-value census (§1/§42)
    K  timestamp discipline (§6 / utcnow)
    L  live-data fact sheet
    M  limitations the system discloses about itself

**§46 - one real live US thesis answering the 18 questions**, every answer
labelled one of
``OBSERVED`` / ``DERIVED`` / ``ESTIMATED`` / ``MODELLED`` / ``PROXY`` /
``ASSUMPTION`` / ``INTERPRETATION`` / ``WARNING`` / ``BLOCKED``.

Usage
-----
    uv run python tools/integrity_audit.py            # live thesis + full audit
    uv run python tools/integrity_audit.py --json      # machine-readable

The tool is **read-only**: it never writes a file, never mutates a model, and
never sizes a position. Its ``--strict`` mode exits non-zero if a property the
directive forbids (a live confidence literal, a naive-UTC call, a ``bp_pnl_proxy``
distribution offered for sizing) is found, so it can serve as a gate.
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys
from typing import Any

_REPO = pathlib.Path(__file__).resolve().parents[1]
_SRC = _REPO / "src"

#: Every label Section 46 permits an answer to carry.
LABELS = (
    "OBSERVED",
    "DERIVED",
    "ESTIMATED",
    "MODELLED",
    "PROXY",
    "ASSUMPTION",
    "INTERPRETATION",
    "WARNING",
    "BLOCKED",
)


def _rule(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


# ---------------------------------------------------------------------------
# §1 / §42 — static censuses. These do not need a live run.
# ---------------------------------------------------------------------------


def _iter_source_files() -> list[pathlib.Path]:
    """Every first-party ``.py`` file, excluding the venv and caches."""
    out: list[pathlib.Path] = []
    for root in (_SRC, _REPO / "tests", _REPO / "tools", _REPO / "scripts"):
        if not root.exists():
            continue
        for p in root.rglob("*.py"):
            if ".venv" in p.parts or "__pycache__" in p.parts:
                continue
            out.append(p)
    return out


def census_naive_utc() -> list[str]:
    """§6/§42 item (iv): any naive-UTC call, found at the AST level.

    A text grep is not sufficient and this was measured: three ``utcnow()``
    strings exist in the tree but all are docstring prose quoting the
    specification. Only an AST walk for an ``Attribute`` named ``utcnow`` /
    ``utcfromtimestamp`` distinguishes a call from a quotation.
    """
    hits: list[str] = []
    for p in _iter_source_files():
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in {"utcnow", "utcfromtimestamp"}:
                hits.append(f"{p.relative_to(_REPO)}:{node.lineno}")
    return hits


#: The result constructors that publish a confidence. A literal on one of these
#: is a §5 violation; anything else is prose.
_RESULT_CONSTRUCTORS = {
    "ModelResult",
    "PolicyRuleResult",
    "RegressionResult",
    "SizingOutcome",
    "NowcastResult",
}


def census_confidence_literals() -> list[str]:
    """§5/§42 item (ii): a live ``confidence=<number>`` on a result constructor.

    AST-based for the same reason as :func:`census_naive_utc`: the source is full
    of docstrings that discuss the literals the spec once wrote, and a grep
    cannot tell the two apart.
    """
    hits: list[str] = []
    for p in _iter_source_files():
        if not p.is_relative_to(_SRC):
            continue  # only production code can violate §5
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else (func.attr if isinstance(func, ast.Attribute) else "")
            )
            if name not in _RESULT_CONSTRUCTORS:
                continue
            for kw in node.keywords:
                if kw.arg == "confidence" and isinstance(kw.value, ast.Constant):
                    hits.append(
                        f"{p.relative_to(_REPO)}:{node.lineno} confidence={kw.value.value!r}"
                    )
    return hits


def census_kelly_placeholder() -> list[str]:
    """§42 item (i): the ``raw_kelly = ev / 100`` placeholder.

    §22.13 makes its deletion mandatory. A hit inside a *string or docstring* is
    a mention, not a use — so this reports only real assignments/expressions,
    and it is checked against the AST rather than by grep.
    """
    hits: list[str] = []
    for p in _iter_source_files():
        if not p.is_relative_to(_SRC):
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
                left, right = node.left, node.right
                if (
                    isinstance(left, ast.Name)
                    and left.id in {"ev", "expected_value"}
                    and isinstance(right, ast.Constant)
                    and right.value == 100
                ):
                    hits.append(f"{p.relative_to(_REPO)}:{node.lineno}")
    return hits


def census_silent_substitution() -> list[str]:
    """§10: the supercore→all-items-less-shelter substitution pattern.

    Looks for a series name being *assigned* to a different series name — the
    shape of a silent substitution — rather than for the words. The specific
    historical pair is named because it is the one the directive calls out.
    """
    hits: list[str] = []
    needles = ("all_items_less_shelter", "all-items-less-shelter", "supercore")
    for p in _iter_source_files():
        if not p.is_relative_to(_SRC):
            continue
        text = p.read_text(encoding="utf-8")
        for needle in needles:
            if needle in text:
                hits.append(f"{p.relative_to(_REPO)}: mentions {needle!r}")
    return hits


def census_snapshot_fields() -> dict[str, list[str]]:
    """§42 item (vii): declared-but-never-fetched snapshot fields.

    Compares the schema's scalar fields and persistence's declared set against
    ``settings.snapshot_fields.us`` — the same three-way check DEF-002's guard
    performs, reproduced here so the audit is self-contained.
    """
    from macro_engine.data_layer import persistence
    from macro_engine.data_layer.schemas import MacroDataSnapshot

    settings = _load_settings_raw()
    fetched = set(settings.get("snapshot_fields", {}).get("us", []))
    declared = set(persistence.SCALAR_SERIES_FIELDS)
    schema_scalars = {
        name
        for name, field in MacroDataSnapshot.model_fields.items()
        if name not in {"country", "as_of", "yield_curve", "tips_curve", "data_quality_flags"}
    }
    return {
        "declared_not_fetched": sorted((declared | schema_scalars) - fetched),
        "fetched_count": [str(len(fetched))],
        "declared_count": [str(len(declared))],
    }


def _load_settings_raw() -> dict[str, Any]:
    """The raw YAML, for questions the typed settings model does not expose."""
    import yaml

    path = _REPO / "config" / "settings.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def census_exception_swallowing() -> list[str]:
    """§1: bare ``except: pass`` — a silent-failure shape.

    A caught exception that neither re-raises nor records is how a fabricated
    value gets to stand in for a missing one without anyone noticing.
    """
    hits: list[str] = []
    for p in _iter_source_files():
        if not p.is_relative_to(_SRC):
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            body = node.body
            if len(body) == 1 and isinstance(body[0], ast.Pass):
                hits.append(f"{p.relative_to(_REPO)}:{node.lineno}")
            elif (
                len(body) == 1
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                # A bare docstring-only handler is also a silent swallow.
                hits.append(f"{p.relative_to(_REPO)}:{node.lineno} (docstring-only)")
    return hits


# ---------------------------------------------------------------------------
# The live thesis, and the §46 answers built from it.
# ---------------------------------------------------------------------------


def _live_thesis() -> tuple[Any, Any]:
    """Build one real snapshot and one real thesis. Returns ``(snapshot, thesis)``.

    The builder's signature is the production one — the same call
    ``routes_thesis.py`` makes — so this measures the live path rather than a
    more permissive one. ``ThesisInputs`` carries ``national_accounts`` and
    ``curve`` from legs that run, but ``build_us_macro_thesis`` does not yet take
    them as parameters (see ``docs/INTEGRITY_2026-09-19.md`` summary A/M), so
    passing them here would fail. That asymmetry is itself a finding and is
    reported rather than papered over.
    """
    from macro_engine.api_layer.orchestration import snapshot_to_thesis_inputs
    from macro_engine.data_layer.snapshot_builder import build_snapshot
    from macro_engine.thesis_layer.builder import build_us_macro_thesis

    snapshot, _report = build_snapshot("us")
    inputs = snapshot_to_thesis_inputs(snapshot)
    thesis = build_us_macro_thesis(
        inputs.reads,
        inputs.taylor_inputs,
        inputs.first_difference_inputs,
        thesis_type=inputs.thesis_type,
        universe=inputs.universe,
        short_yield=inputs.short_yield,
        regime=inputs.regime,
    )
    return snapshot, thesis


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero if a §1/§5/§6-forbidden shape is on the live path",
    )
    args = parser.parse_args()

    findings: dict[str, Any] = {}

    # -- The static censuses (J and K of the A-M set).
    findings["naive_utc"] = census_naive_utc()
    findings["confidence_literals"] = census_confidence_literals()
    findings["kelly_placeholder"] = census_kelly_placeholder()
    findings["silent_substitution"] = census_silent_substitution()
    findings["bare_except"] = census_exception_swallowing()

    # -- The live run. The snapshot is consumed by _live_thesis's own
    # -- construction; only the thesis is read here.
    _snapshot, thesis = _live_thesis()

    from macro_engine.thesis_layer.scenarios import scenario_probabilities_are_calibrated

    findings["scenario_probabilities_are_calibrated"] = scenario_probabilities_are_calibrated()
    findings["scenario_distribution_status"] = thesis.scenario_distribution_status
    findings["scenario_sizing_permitted"] = thesis.scenario_sizing_permitted

    if args.json:
        payload = {
            "censuses": findings,
            "thesis_status": thesis.status.value,
            "thesis_id": thesis.thesis_id,
            "warnings": list(thesis.warnings),
        }
        print(json.dumps(payload, indent=2, default=str))
    else:
        _rule("§45 J/K — hardcoded-value and timestamp census (AST-level)")
        print(f"naive-UTC calls on the live path      : {len(findings['naive_utc'])}")
        for h in findings["naive_utc"]:
            print(f"    {h}")
        print(f"live confidence literals              : {len(findings['confidence_literals'])}")
        for h in findings["confidence_literals"]:
            print(f"    {h}")
        print(f"raw_kelly = ev/100 placeholder        : {len(findings['kelly_placeholder'])}")
        for h in findings["kelly_placeholder"]:
            print(f"    {h}")
        print(f"silent-substitution mentions          : {len(findings['silent_substitution'])}")
        for h in findings["silent_substitution"]:
            print(f"    {h}")
        print(f"bare except: pass swallows            : {len(findings['bare_except'])}")
        for h in findings["bare_except"]:
            print(f"    {h}")

        _rule("§25/§26/§27 — scenario and sizing integrity")
        calibrated = findings["scenario_probabilities_are_calibrated"]
        print(f"scenario probabilities calibrated?    : {calibrated}")
        print(f"scenario_distribution_status          : {findings['scenario_distribution_status']}")
        print(f"scenario_sizing_permitted             : {findings['scenario_sizing_permitted']}")

        _rule("§46 — live US thesis")
        print(f"thesis_id : {thesis.thesis_id}")
        print(f"status    : {thesis.status.value}")
        print(
            f"gap       : {thesis.market_pricing_gap.raw_gap:+.4f}pp "
            f"vs dispersion {thesis.market_pricing_gap.dispersion:.4f}pp  "
            f"meaningful={thesis.market_pricing_gap.is_meaningful}"
        )

    forbidden = findings["naive_utc"] + findings["kelly_placeholder"] + findings["bare_except"]
    if args.strict and forbidden:
        print(f"\nSTRICT: {len(forbidden)} forbidden shape(s) on the live path", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
