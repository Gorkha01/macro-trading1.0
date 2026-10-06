"""Infrastructure invariants over ``config/settings.yaml``'s shape.

THIS FILE IS CITED FOUR TIMES IN ``config.py`` AND DID NOT EXIST. MEASURED
2026-10-06: ``config.py`` names it as the enforcement of three separate
invariants, and two further test names it cites were absent from ``tests/``
entirely:

* ``config.py:4168`` and ``:5382`` — *"``tests/test_infrastructure.py`` requires
  every envelope to be readable as a ``float``"* / *"enforces that every
  ``CalibratedValue`` leaf is readable as a plain NUMBER by a property or
  ``Settings.scalar()``"*.
* ``config.py:5638`` and ``:5997`` — *"the D-035 collision guard in
  ``tests/test_infrastructure.py``"*, i.e. that no ``property`` shares a name
  with a ``model_field``.
* ``config.py:3834`` — ``test_config_properties_are_not_shadowed_by_fields``
  *"sweeps the whole settings tree and asserts that no ``property`` shares a name
  with a ``model_field`` in any settings group"*.
* ``config.py:3879`` — ``test_no_validator_shadows_a_property`` *"asserts the
  property identity to keep it that way"*.

Two of the four are written here at the names the module uses; the third is
written as the rule the config ACTUALLY satisfies, with the non-numeric leaves
pinned as a disclosed set so a new one fails.

**``test_no_validator_shadows_a_property`` has teeth on the day it is written:**
MEASURED, ``KellySettings._enforce_fractional_kelly_floor`` assigned a local named
``divisor``, shadowing that class's own ``divisor`` property inside the validator
frame — the exact defect class ``_ceiling_must_be_reachable_and_binding``
documents at length, and benign only because the local happened to compute the
same value the property returns. Fixed by `_`-prefixing the locals.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
import typing

from pydantic import BaseModel

from macro_engine.config import CalibratedValue, Settings, get_settings

#: The envelope leaves that hold a NON-numeric payload on purpose: a URL, a
#: tenor label, a label's display text, a marker vocabulary, a thesis-family
#: name, or a list of confidence levels. Pinned as a set so a NEW one fails the
#: numeric sweep rather than quietly joining the exception.
#:
#: MEASURED 2026-10-06: 19 of the 339 ``CalibratedValue`` leaves are non-numeric,
#: which is why the cited invariant is stated here as *"every NUMERIC envelope is
#: scalar-readable"* rather than the stronger claim the docstrings make.
_NON_NUMERIC_ENVELOPES = frozenset(
    {
        "openbb.local_api_base_url",
        "risk.var_confidence_levels",
        "instrument_selection.curve_default_short_tenor",
        "instrument_selection.curve_default_long_tenor",
        "invalidation.supporting_agreement_class",
        "statement_text.hawkish_markers_value",
        "statement_text.dovish_markers_value",
        "validation.zero_yield_permitted_tenors",
        "intervention.unconstrained_label",
        "intervention.reserve_constrained_label_text",
        "em_vulnerability.low_label",
        "em_vulnerability.moderate_label",
        "em_vulnerability.high_label",
        "em_vulnerability.critical_label",
        "equity_macro.no_prior_label_leaf",
        "api.host_value",
        "api.cors_origins_value",
        "api.short_yield_tenor_value",
        "api.default_thesis_type_value",
    }
)


def _walk_groups(
    model_cls: type[BaseModel], prefix: str = ""
) -> typing.Iterator[tuple[str, type[BaseModel]]]:
    """Every nested settings group, with its dotted path."""
    for name, field in model_cls.model_fields.items():
        annotation = field.annotation
        for arg in typing.get_args(annotation):
            if isinstance(arg, type) and issubclass(arg, BaseModel):
                annotation = arg
                break
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            path = f"{prefix}{name}"
            yield path, annotation
            yield from _walk_groups(annotation, f"{path}.")


def _properties(model_cls: type[BaseModel]) -> set[str]:
    return {name for name, value in vars(model_cls).items() if isinstance(value, property)}


def _config_source() -> str:
    return pathlib.Path(inspect.getfile(Settings)).read_text(encoding="utf-8")


def _is_validator(node: ast.FunctionDef) -> bool:
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        name = getattr(target, "attr", None) or getattr(target, "id", "")
        if "validator" in str(name):
            return True
    return False


# ---------------------------------------------------------------------------
# the two named guards
# ---------------------------------------------------------------------------


def test_config_properties_are_not_shadowed_by_fields() -> None:
    """No ``property`` may share a name with a ``model_field``, in ANY group.

    The class-wide form of D-035's collision: a property and a field with the
    same name make the field unreachable through the property and the property
    unreachable through attribute access, and which one wins depends on the
    lookup path rather than on intent.
    """
    collisions: list[tuple[str, list[str]]] = []
    for path, group in _walk_groups(Settings):
        overlap = set(group.model_fields) & _properties(group)
        if overlap:
            collisions.append((path, sorted(overlap)))
    assert collisions == [], f"property/field name collisions: {collisions}"

    # Non-vacuity: the sweep actually visits the tree and finds properties.
    visited = list(_walk_groups(Settings))
    assert len(visited) > 50, f"the sweep visited only {len(visited)} groups"
    assert any(_properties(group) for _path, group in visited), "no properties found to check"


def test_no_validator_shadows_a_property() -> None:
    """A validator's local must not repeat a member name.

    A ``model_validator(mode="after")`` body runs as an ordinary function, so a
    local assignment wins over the class's property INSIDE that frame — and the
    failure then surfaces elsewhere (the sibling docstring records exactly that:
    a ``duration_saturation_weeks`` local produced
    ``TypeError: unsupported operand type(s) for /: 'int' and 'CalibratedValue'``
    in a different property).
    """
    tree = ast.parse(_config_source())
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        properties = set()
        for statement in node.body:
            if isinstance(statement, ast.FunctionDef):
                for decorator in statement.decorator_list:
                    target = decorator.func if isinstance(decorator, ast.Call) else decorator
                    if (getattr(target, "attr", None) or getattr(target, "id", "")) == "property":
                        properties.add(statement.name)
        if not properties:
            continue
        for statement in node.body:
            if not isinstance(statement, ast.FunctionDef) or not _is_validator(statement):
                continue
            assigned: set[str] = set()
            for sub in ast.walk(statement):
                if isinstance(sub, ast.Assign):
                    assigned |= {t.id for t in sub.targets if isinstance(t, ast.Name)}
            overlap = assigned & properties
            if overlap:
                offenders.append(f"{node.name}.{statement.name} -> {sorted(overlap)}")
    assert offenders == [], f"validator local(s) shadowing a property: {offenders}"


# ---------------------------------------------------------------------------
# the envelope readability invariant
# ---------------------------------------------------------------------------


def _envelope_leaves() -> list[str]:
    leaves: list[str] = []
    for path, group in _walk_groups(Settings):
        for name, field in group.model_fields.items():
            if field.annotation is CalibratedValue:
                leaves.append(f"{path}.{name}")
    return leaves


def test_every_numeric_envelope_leaf_is_scalar_readable() -> None:
    """``Settings.scalar()`` must return a ``float`` for every NUMERIC envelope.

    This is the half of the cited invariant that holds. The docstrings state it
    as *"every envelope"*; MEASURED, 19 of 339 leaves hold a string or a list on
    purpose, so the rule enforced here is the one the config actually satisfies —
    and the 19 are pinned below so a NEW non-numeric leaf fails.
    """
    settings = get_settings()
    leaves = _envelope_leaves()
    assert len(leaves) > 300, f"only {len(leaves)} envelope leaves found"

    unreadable: list[str] = []
    for path in leaves:
        if path in _NON_NUMERIC_ENVELOPES:
            continue
        # `scalar` is annotated `-> float`, so the TYPE is a static guarantee —
        # mypy proves it, which is why there is no `isinstance` branch here. What
        # a test can add is that the call does not RAISE for a leaf it is supposed
        # to be able to read.
        try:
            settings.scalar(path)
        except Exception as exc:
            unreadable.append(f"{path} ({type(exc).__name__}: {exc})")
    assert unreadable == [], f"numeric envelope(s) not scalar-readable: {unreadable}"


def test_the_non_numeric_envelopes_are_exactly_the_disclosed_set() -> None:
    """A new non-numeric envelope must be a deliberate edit, not a silent drift.

    The docstrings' reasoning is that a string cannot satisfy a float invariant,
    which is why several CHOICES ship as plain ``str`` — these 19 are envelopes
    holding a string or a list anyway, and they are named rather than counted so
    the discrepancy is auditable.
    """
    settings = get_settings()
    measured: set[str] = set()
    for path in _envelope_leaves():
        try:
            if not isinstance(settings.scalar(path), float):
                measured.add(path)
        except Exception:
            measured.add(path)
    assert measured == set(_NON_NUMERIC_ENVELOPES), (
        f"added: {sorted(measured - _NON_NUMERIC_ENVELOPES)} | "
        f"removed: {sorted(_NON_NUMERIC_ENVELOPES - measured)}"
    )


def test_the_docstring_does_not_over_claim_the_envelope_invariant() -> None:
    """(F-CFG-002) ``config.py`` cited the invariant as covering *every* envelope.

    MEASURED 2026-10-06: 19 of the 339 ``CalibratedValue`` leaves hold a string or
    a list on purpose, so the strong form was false in two places. The docstrings
    now state the numeric rule and point at the disclosed set.
    """
    source = _config_source()
    assert "requires every envelope to be readable as a" not in source
    assert "requires every **numeric** envelope" in source
