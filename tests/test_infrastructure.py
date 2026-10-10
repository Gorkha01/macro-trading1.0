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

import pytest
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
        # Section 22.5's futures-implied policy path. These two are the
        # contract's IDENTITY (the CME product code and the provider that
        # serves it), so they are strings by nature — the same shape as
        # `api.short_yield_tenor_value` above, not a numeric leaf that
        # drifted to a string.
        "market_implied_futures.symbol_value",
        "market_implied_futures.provider_value",
        # `fx_futures.provider_value`: the provider identity, a string by nature
        # — the same shape as `market_implied_futures.provider_value` above.
        "fx_futures.provider_value",
        # `fx_futures.cme_roots_value`: a currency -> CME-root MAPPING. It is data
        # (which root tracks which currency is a market fact, LAW 1), and a
        # mapping has no scalar form — the same reason
        # `risk.var_confidence_levels` is listed: an envelope carrying structure,
        # not a drifted number.
        "fx_futures.cme_roots_value",
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


# ---------------------------------------------------------------------------
# (F-CFG-004) the exactness floor is defined ONCE
# ---------------------------------------------------------------------------


def test_the_exactness_floor_is_defined_once() -> None:
    """(F-CFG-004) The "shares sum to 1.0" floor is one value, not four literals.

    MEASURED 2026-10-06: ``1e-9`` was written as a bare literal at four sites —
    ``config.py`` twice (``_remaining_shares_must_sum_to_one``,
    ``_weights_must_sum_to_one``), ``models/labor_synthesis.py`` (tightness
    weights) and ``models/risk.py`` (correlation diagonal) — while
    ``portfolio/risk_budget.py`` NAMED the same floor
    (``_RISK_BUDGET_SUM_TOLERANCE``) and ``config.py``'s own prose REFERRED to
    that name (lines 791/883). A value named in one place and retyped in another
    is indistinguishable from it without a *mover* (D-031), which is the exact
    defect the file documents for other leaves.

    The floor now lives at the lowest layer (``config``, which imports nothing
    from ``macro_engine``) so every consumer can reach it. This test asserts:

    * the definition is a single module constant on ``config``;
    * ``risk_budget``'s named constant aliases it (equal value, and it is the
      value ``config`` exposes rather than a private re-``1e-9``);
    * no bare ``1e-9`` sum-to-one comparison survives in the four modules.
    """
    import macro_engine.config as cfg
    from macro_engine.portfolio import risk_budget as rb

    assert cfg._EXACTNESS_SUM_TOLERANCE == 1e-9
    # the alias chain: one value, reached by name
    assert rb._RISK_BUDGET_SUM_TOLERANCE == cfg._EXACTNESS_SUM_TOLERANCE

    # no retyped literal among the modules that own a sum-to-one guard
    import importlib

    owners = (cfg, "macro_engine.models.risk", "macro_engine.models.labor_synthesis")
    for owner in owners:
        module = importlib.import_module(owner) if isinstance(owner, str) else owner
        source = pathlib.Path(inspect.getfile(module)).read_text(encoding="utf-8")
        assert "> 1e-9:" not in source, f"a bare 1e-9 sum comparison survives in {module.__name__}"
        assert "tolerance = 1e-9" not in source, (
            f"a bare 1e-9 tolerance survives in {module.__name__}"
        )

    # (F-CFG-004 residual, prose half) The two sites that CONTRAST the loose
    # rebalancing tolerance with the exactness floor named the floor as
    # `_RISK_BUDGET_SUM_TOLERANCE` "the module constant" — but after the fix the
    # floor is DEFINED here as `_EXACTNESS_SUM_TOLERANCE`, and
    # `risk_budget._RISK_BUDGET_SUM_TOLERANCE` only ALIASES it. The old prose
    # pointed the reader out of the file for a value that sits a few hundred
    # lines above them.
    cfg_source = pathlib.Path(inspect.getfile(cfg)).read_text(encoding="utf-8")
    assert "the `_RISK_BUDGET_SUM_TOLERANCE`" not in cfg_source, (
        "config.py still calls _RISK_BUDGET_SUM_TOLERANCE 'the ... module constant'; "
        "the floor is defined HERE as _EXACTNESS_SUM_TOLERANCE"
    )
    assert "_EXACTNESS_SUM_TOLERANCE" in cfg_source, (
        "config.py prose no longer names its own exactness-floor constant"
    )


def test_the_base_state_disclosure_bar_binds_the_smallest_rate_it_indexes() -> None:
    """(F-CFG-005) The disclosure validator must bound the rate the consumer reads.

    ``inflation_convergence_classifier`` sets ``current_measure_count_high`` to
    ``three_measure_high`` when ``total <= 3`` and ``six_measure_high`` otherwise,
    and discloses when ``current_rate > base_state_warning_threshold``. So the
    reachability bound the validator must enforce is the **minimum** of the two
    rates — a threshold above the smaller one leaves that path's disclosure
    permanently dead, the O-29/D-037 unreachable-disclosure class.

    MEASURED 2026-10-06: the validator bounded against ``max(...)``, so it
    ACCEPTED a threshold of 0.88 against the shipped 0.866 / 0.895 — at which
    ``0.866 > 0.88`` is False and the 3-measure disclosure is dead — while the
    validator's own error message already said "strictly below the smallest base
    rate". Code and message disagreed; the message was right.

    This test pins both halves: the correct bound REJECTS any threshold at or
    above the minimum, and the shipped value stays below it.
    """
    from macro_engine.config import InflationConvergenceSettings, get_settings

    convergence = get_settings().inflation.convergence
    three = convergence.measured_base_rates.three_measure_high
    six = convergence.measured_base_rates.six_measure_high
    smallest = min(three, six)

    # The shipped value must itself keep the disclosure reachable on both paths.
    assert convergence.base_state_warning_threshold < smallest

    def _with_threshold(value: float) -> InflationConvergenceSettings:
        raw = convergence.model_dump()
        raw["base_state_warning_threshold_value"]["value"] = value
        return InflationConvergenceSettings.model_validate(raw)

    # At or above the SMALLEST indexed rate -> dead on that path -> refused.
    for dead in (smallest, max(three, six), (three + six) / 2 + 1e-9, 1.0):
        with pytest.raises(ValueError, match="smallest measured HIGH base rate"):
            _with_threshold(dead)

    # Strictly below the smallest -> reachable on both paths -> accepted.
    assert _with_threshold(smallest - 1e-6).base_state_warning_threshold < smallest


def test_the_fractional_kelly_floor_is_itself_bounded() -> None:
    """(F-CFG-006) The floor must be >= 2 so full Kelly cannot be configured.

    ``KellySettings._enforce_fractional_kelly_floor`` originally checked only
    ``divisor >= floor`` — which says nothing about the floor. MEASURED
    2026-10-06, with an unbounded floor:

    * ``min_fractional_divisor=1.0, fractional_divisor=1.0`` loaded, and
      ``kelly_fraction_multiplier`` (``1/divisor``) returned ``1.0`` — FULL
      Kelly, the exact case Section 22.6 / Finding #6 prohibits, while the
      validator's own message claimed it was prohibited.
    * ``min_fractional_divisor=0.0, fractional_divisor=0.0`` loaded, and
      ``kelly_fraction_multiplier`` raised ``ZeroDivisionError`` inside
      ``apply_fractional_kelly`` — a runtime failure of a model instead of a
      config error.

    ``_MIN_FRACTIONAL_KELLY_DIVISOR`` names the boundary and the validator now
    refuses a floor below it. This test pins: the constant is 2.0, the shipped
    floor is at least it, NO floor below it loads, and the shipped multiplier is
    at most half Kelly.
    """
    import macro_engine.config as cfg
    from macro_engine.config import KellySettings, get_settings

    assert cfg._MIN_FRACTIONAL_KELLY_DIVISOR == 2.0

    kelly = get_settings().kelly
    assert float(kelly.min_fractional_divisor.value) >= cfg._MIN_FRACTIONAL_KELLY_DIVISOR
    # Full Kelly is a multiplier of 1.0; the mandatory division caps it at 0.5.
    assert kelly.kelly_fraction_multiplier <= 0.5

    def _with(floor: float, divisor: float) -> KellySettings:
        raw = kelly.model_dump()
        raw["min_fractional_divisor"]["value"] = floor
        raw["fractional_divisor"]["value"] = divisor
        return KellySettings.model_validate(raw)

    # A floor below 2.0 — full Kelly (1.0) or a zero divisor — must be refused.
    for floor, divisor in ((1.0, 1.0), (0.0, 0.0), (0.5, 0.5), (1.0, 2.0)):
        with pytest.raises(ValueError):
            _with(floor, divisor)

    # The legitimately-bounded pair still loads, and respects both clauses.
    assert _with(2.0, 3.0).kelly_fraction_multiplier == pytest.approx(1.0 / 3.0)


# ---------------------------------------------------------------------------
# (F-DEP-001) every DeploymentConfig field is backed by a declared variable
# ---------------------------------------------------------------------------


def test_every_deployment_field_is_backed_by_a_declared_variable() -> None:
    """(F-DEP-001) The field -> variable pairing is a receipt, not a prose claim.

    ``DeploymentConfig``'s docstring used to say *"the validator enforces that,
    so adding a field without declaring its variable fails at construction"* —
    and there was NO validator (MEASURED 2026-10-06: neither the class nor the
    module declared one). ``extra="forbid"`` rejects an unknown FIELD, not an
    undeclared VARIABLE, so a 15th field with no ``_VARIABLES`` entry constructed
    cleanly and defaulted to ``None`` at use.

    This test is the enforcement the docstring claimed: every field must resolve
    to a declared variable through ``_field_to_variable``, and no two fields may
    map to the same one. It fails the day a field is added without a declaration.
    """
    import macro_engine.deployment as dep

    fields = list(dep.DeploymentConfig.model_fields)
    unresolved = [f for f in fields if dep._field_to_variable(f) is None]
    assert not unresolved, (
        f"DeploymentConfig field(s) {unresolved} have no backing entry in _VARIABLES; "
        f"add the variable or an exception in _NON_CONVENTIONAL_VARIABLE"
    )

    resolved = [dep._field_to_variable(f) for f in fields]
    assert len(resolved) == len(set(resolved)), "two fields resolve to the same variable"
    # every mapped variable must actually be declared
    assert set(resolved) <= set(dep._VARIABLES)


# ---------------------------------------------------------------------------
# (F-DEP-002) the production-required set is derived, not hand-maintained
# ---------------------------------------------------------------------------


def test_production_required_list_is_derived_from_required_when() -> None:
    """(F-DEP-002) ``REQUIRED_IN_PRODUCTION`` cannot drift from ``required_when``.

    MEASURED 2026-10-06: the tuple was hand-typed and had ALREADY drifted — it
    omitted ``MACRO_API_KEY_HASH``, which ``required_when`` marks required in
    production, so ``_check_production_requirements`` (whose docstring promised
    the full set at once) reported three of the four production-required
    variables. It is now the projection of ``required_when`` onto PRODUCTION, so
    the two are incapable of disagreeing.

    This test computes the truth from the declarations and asserts equality, and
    asserts the preflight enumerates exactly that set.
    """
    import macro_engine.deployment as dep

    derived = {
        name
        for name, variable in dep._VARIABLES.items()
        if dep.AppEnvironment.PRODUCTION in variable.required_when
    }
    assert set(dep.REQUIRED_IN_PRODUCTION) == derived
    assert "MACRO_API_KEY_HASH" in derived, (
        "MACRO_API_KEY_HASH declares required_when=PRODUCTION; the derived set must include it"
    )

    # The preflight enumerates the same set when nothing is set.
    import os

    saved = dict(os.environ)
    try:
        for name in dep._VARIABLES:
            os.environ.pop(name, None)
        missing = set(dep._check_production_requirements(dep.AppEnvironment.PRODUCTION))
        # the ones that declare PRODUCTION and are unset == the derived set
        assert missing == derived
    finally:
        os.environ.clear()
        os.environ.update(saved)


# ---------------------------------------------------------------------------
# (F-DEP-003) the is_secret flag has a consumer, and it redacts
# ---------------------------------------------------------------------------


def test_secret_deployment_variables_are_never_rendered() -> None:
    """(F-DEP-003) ``is_secret`` is read: a redacted render masks those values.

    MEASURED 2026-10-06: ``is_secret`` was declared with the description *"never
    log the value; presence/absence is logged instead"* and read by NOTHING — no
    logging or redaction path consulted it. ``DeploymentConfig.redacted()`` is
    its consumer; this test asserts a secret's value cannot survive a render,
    while its presence still does.
    """
    import macro_engine.deployment as dep

    secrets = {n for n, v in dep._VARIABLES.items() if v.is_secret}
    assert secrets, "no variable declares is_secret; the flag would be untested"

    cfg = dep.DeploymentConfig(
        environment=dep.AppEnvironment.DEVELOPMENT,
        api_host="127.0.0.1",
        api_port=8000,
        api_root_path="",
        api_docs_enabled=False,
        api_cors_origins=["http://x"],
        api_key_required=False,
        api_key_hash=None,
        database_url="postgresql+psycopg://user:sup3rsecret@host/db",
        database_echo_sql=False,
        openbb_api_url="http://127.0.0.1:6900",
        data_store_path="data/raw",
        log_level="INFO",
        audit_enabled=True,
    )
    rendered = cfg.redacted()
    assert "sup3rsecret" not in str(rendered), "a secret value survived redaction"
    assert rendered["database_url"] == "<set>"
    assert rendered["api_key_hash"] == "<unset>"
    # non-secret fields still render their value
    assert rendered["api_host"] == "127.0.0.1"


# ---------------------------------------------------------------------------
# (F-DEP-004) the OpenBB default URL is pinned to settings.yaml
# ---------------------------------------------------------------------------


def test_the_openbb_fallback_url_matches_settings_yaml() -> None:
    """(F-DEP-004) The named default is pinned to the committed leaf.

    ``deployment._OPENBB_DEFAULT_BASE_URL``'s own comment claims
    *"``tests/test_infrastructure.py`` pins the two to each other so a future
    edit to one without the other fails a test instead of an outage."* MEASURED
    2026-10-06: no test referenced ``_OPENBB_DEFAULT_BASE_URL``, ``deployment``,
    or ``6900`` — the pin was a claim, not a receipt (F-SIG-003 / F-INV-002 /
    F-NT-003 class). This is that pin.
    """
    import macro_engine.deployment as dep

    committed = get_settings().openbb.local_api_base_url.value
    assert committed == dep._OPENBB_DEFAULT_BASE_URL, (
        f"deployment fallback {dep._OPENBB_DEFAULT_BASE_URL!r} != "
        f"settings.yaml openbb.local_api_base_url {committed!r}"
    )


# ---------------------------------------------------------------------------
# (F-STORE-001) the SettingRecord docstring matches the write it describes
# ---------------------------------------------------------------------------


def test_setting_record_docstring_matches_the_supersession_write() -> None:
    """(F-STORE-001) The docstring no longer claims "never updated in place".

    MEASURED 2026-10-06: ``SettingRecord``'s docstring said *"rows are never
    updated in place"*, but ``set()`` mutates three columns of the prior row
    (``is_active``/``superseded_at``/``superseded_by``). The narrower, true
    invariant — value columns immutable, supersession columns stamped — is what
    the docstring must state. A text guard, because the defect is the prose.
    """
    from macro_engine import settings_store as store

    source = pathlib.Path(inspect.getfile(store)).read_text(encoding="utf-8")
    lowered = source.lower()
    assert "rows are never updated in place" not in lowered, (
        "the false 'rows are never updated in place' claim is back in settings_store.py"
    )
    assert "value columns are never" in source, (
        "the corrected invariant ('the value columns are never rewritten') is missing"
    )


# ---------------------------------------------------------------------------
# (F-STORE-002) the value-type vocabulary is a single definition
# ---------------------------------------------------------------------------


def test_the_value_type_vocabulary_is_single_definition() -> None:
    """(F-STORE-002) ``SettingValueType`` is the one vocabulary ``set()`` enforces.

    MEASURED 2026-10-06: ``SettingValueType`` was a bare ``str`` subclass with no
    members, exported but used nowhere, while the real vocabulary lived in a
    separate ``_VALID_VALUE_TYPES`` frozenset. Two declarations, one dead. It is
    now the single definition and ``_VALID_VALUE_TYPES`` is derived from it.
    """
    from macro_engine import settings_store as store

    declared = {member.value for member in store.SettingValueType}
    assert declared == store._VALID_VALUE_TYPES
    assert declared == {"float", "int", "str", "bool", "json"}
    # a value_type the enum declares is accepted; one it does not is refused
    s = store.SettingsStore.from_url("sqlite:///:memory:")
    s.create_schema()
    for member in store.SettingValueType:
        s.set("ns", member.value, 0, value_type=member.value, actor="a", reason="r")
    with pytest.raises(ValueError):
        s.set("ns", "bad", 0, value_type="decimal", actor="a", reason="r")


# ---------------------------------------------------------------------------
# (F-AUD-002) no redundant local import of an already-imported module
# ---------------------------------------------------------------------------


def test_no_redundant_local_third_party_imports() -> None:
    """(F-AUD-002) A module-scope import is not re-imported inside a function.

    MEASURED 2026-10-06: ``audit.model_latency_summary`` did ``from sqlalchemy
    import func`` inside its body while ``sqlalchemy`` was already imported at
    module scope. Harmless, but dead ceremony implying a constraint that does not
    exist. This sweeps the three modules touched by this review for a local
    import of a name already bound at module scope.
    """
    import macro_engine.audit as audit
    import macro_engine.deployment as dep
    import macro_engine.settings_store as store

    for module in (audit, dep, store):
        tree = ast.parse(pathlib.Path(inspect.getfile(module)).read_text(encoding="utf-8"))
        module_scope: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                module_scope.update(a.asname or a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                module_scope.update(a.asname or a.name for a in node.names)
        for walked in ast.walk(tree):
            if isinstance(walked, ast.FunctionDef | ast.AsyncFunctionDef):
                for inner in ast.walk(walked):
                    if isinstance(inner, ast.Import):
                        for a in inner.names:
                            bound = a.asname or a.name.split(".")[0]
                            assert bound not in module_scope, (
                                f"{module.__name__}:{walked.name} re-imports {bound!r}, "
                                f"already bound at module scope"
                            )
                    elif isinstance(inner, ast.ImportFrom):
                        for a in inner.names:
                            bound = a.asname or a.name
                            assert bound not in module_scope, (
                                f"{module.__name__}:{walked.name} re-imports {bound!r}, "
                                f"already bound at module scope"
                            )
