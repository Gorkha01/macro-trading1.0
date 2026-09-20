"""Static guards for the API layer (D-070).

Why this file exists at all
---------------------------
Three properties of this increment **cannot be killed behaviourally**, and each
one is a property this increment's whole honesty claim rests on:

1. **The exclusion of literals from the stream is a property of the SOURCE, not
   of a value.** ``test_routes.py`` proves that the emitted gap equals a
   separately computed gap *for the snapshot on disk*. A mutant that hardcoded a
   value which happened to equal today's would pass that test. The only guard
   that survives a lucky literal is reading the module and proving **no
   hardcoded market number appears in an emitted detail string** — which is what
   lesson 5bf dictates: pin the *structure* via ``ast.parse``, never the spelling
   of the source text, because a spelling guard passes forever while the meaning
   changes.

2. **"Configured, not hardcoded" is a property of where a number is READ.** The
   sweep's ``M2.2``/``M3.4`` replace a config accessor with a literal, and the
   behaviour is *identical under the shipped config* — that identity is precisely
   why no behavioural test can see it. The guard has to assert that the value
   reaches the computation **through ``get_settings()``**, which is a source
   property.

3. **The status-code table is a mapping, not a series of branches.** A mutant
   that returns the right status for the classes the tests happen to hit, and the
   wrong one for a class they do not, is invisible to a behavioural test. The
   guard reads the mapping's **structure** and asserts every documented exception
   class maps to a distinct code.

Everything here is read from the module through ``ast`` rather than from source
text by substring, because a reflow must not break a guard and — more
importantly — a substring guard is a guard on the formatter, not on the code.

The one deliberate exception is documented at its use: ``test_the_stream_module_
contains_no_literal_market_numbers`` walks the AST for string constants, which is
a *structural* read of the constants rather than a text search.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from macro_engine.api_layer import (
    orchestration,
    reasoning_stream,
    routes_dashboard,
    routes_health,
    routes_query,
    routes_thesis,
    snapshot_provider,
)
from macro_engine.api_layer.routes_query import QueryResponse
from macro_engine.api_layer.routes_thesis import _http_status_for
from macro_engine.config import get_settings

_ORCH_SOURCE = Path(orchestration.__file__).read_text(encoding="utf-8")
_PROVIDER_SOURCE = Path(snapshot_provider.__file__).read_text(encoding="utf-8")
_STREAM_SOURCE = Path(reasoning_stream.__file__).read_text(encoding="utf-8")
_THESIS_SOURCE = Path(routes_thesis.__file__).read_text(encoding="utf-8")
_CONFIG_SOURCE = Path(get_settings.__module__.replace(".", "/") + ".py")


# ---------------------------------------------------------------------------
# Helper: read a function's source structurally
# ---------------------------------------------------------------------------


def _function_node(source: str, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    """The AST node of a top-level function, or an assertion error.

    Structural rather than textual so the guards below cannot be satisfied by a
    comment that mentions the function (the D-064 mistake in ``sweep_health``'s
    first ``enclosing_symbol``, where a comment written at column 0 was mistaken
    for a definition).
    """
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"no top-level function named {name!r}")


def _calls_in(node: ast.AST) -> set[str]:
    """Every name called anywhere inside ``node``, as dotted strings where possible."""
    found: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            found.add(ast.unparse(child.func))
    return found


def _stream_body_node() -> ast.FunctionDef | ast.AsyncFunctionDef:
    """The stream function whose body actually emits the trace frames.

    ``reasoning_step_generator`` is the SSE entry point, but its body is now a
    thin outer guard: it wraps ``_reasoning_frames`` in a ``try``/``finally``
    that guarantees the ``[DONE]`` terminator is emitted exactly once on every
    exit path (the finding-2.1 fix). The stages, the interpolated details and the
    calls to the derivation module all live in ``_reasoning_frames``.

    These guards are about *what the stream emits and from where*, not about
    which function object holds the code, so they follow the indirection rather
    than pinning a function name. Pinning the name would make a pure refactor —
    one that changed nobody's behaviour — look like a violation, which is how a
    guard starts manufacturing findings.

    Resolved structurally: ``reasoning_step_generator`` must iterate the result
    of exactly one other top-level function, and that function is the body. If
    no such function exists (someone flattened the two back together), fall back
    to the entry point itself so the guards still apply.
    """
    entry = _function_node(_STREAM_SOURCE, "reasoning_step_generator")
    candidate = _iterated_local_function(entry)
    if candidate is not None:
        return _function_node(_STREAM_SOURCE, candidate)
    return entry


def _iterated_local_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> str | None:
    """The name of the top-level function ``node`` iterates over, if any.

    Looks for ``async for ... in <name>(...)`` / ``for ... in <name>(...)`` where
    ``<name>`` is a bare identifier — the shape the outer guard uses to delegate.
    """
    for child in ast.walk(node):
        if not isinstance(child, (ast.For, ast.AsyncFor)):
            continue
        target = child.iter
        if (
            isinstance(target, ast.Call)
            and isinstance(target.func, ast.Name)
            and target.func.id != node.name
        ):
            return target.func.id
    return None


def _module_docstring(tree: ast.Module) -> str:
    """The module docstring, which is prose ABOUT the code rather than code.

    Excluded from the literal guards below for a reason worth stating: the
    docstring of ``reasoning_stream.py`` **quotes** §8.3's fabricated values in
    order to explain why they are wrong. A guard that scanned it would flag the
    explanation as the defect — the "gate manufacturing findings" failure mode
    (lesson 80), which is worse than no gate.
    """
    if tree.body and isinstance(tree.body[0], ast.Expr):
        value = tree.body[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
    return ""


def _string_constants(node: ast.AST) -> list[str]:
    """Every string literal inside ``node``, folded where they are concatenated.

    ``ast.walk`` visits a ``JoinedStr``'s parts individually, so an f-string's
    literal fragments appear here too — which is what makes the guard below able
    to see ``"gap = "`` as well as ``"14 series"``.
    """
    return [
        c.value for c in ast.walk(node) if isinstance(c, ast.Constant) and isinstance(c.value, str)
    ]


def _code_string_constants(source: str) -> list[tuple[int, str]]:
    """Every string constant in the module's CODE, excluding the docstring.

    ``(lineno, value)`` pairs, so a failure names the line rather than dumping
    the whole module — the first version of this guard failed with an assertion
    message containing the entire docstring, which is a diagnostic nobody can
    read. Docstrings of nested functions and classes are excluded too: they are
    prose as well, and ``_event``'s own docstring contains an example frame.
    """
    tree = ast.parse(source)
    skip: set[int] = set()
    docstrings = [_module_docstring(tree)]
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr):
                value = body[0].value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    skip.add(id(value))

    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in skip or node.value in docstrings:
            continue
        found.append((node.lineno, node.value))
    return found


# ---------------------------------------------------------------------------
# 1. No literal market numbers in any emitted stream detail
# ---------------------------------------------------------------------------


def test_the_stream_module_contains_no_literal_market_numbers() -> None:
    """The core of D-070, as a structural guard.

    Section 8.3's sample hardcodes ``"gap = -140bp"`` and ``"HIGH convergence"``.
    ``test_routes.py`` proves the emitted gap matches the models' for the
    snapshot on disk — but a literal that happened to be right today would pass
    it, and the defect would return the next day. This guard is the one that
    cannot be fooled by a lucky value: it asserts that **no number-bearing
    market string is a constant in the emitting module**.

    Read structurally: every string constant in ``reasoning_stream.py`` is
    examined for a market-shaped numeric literal. Numbers that are *format
    specifications* (``":.1f"``), *unit suffixes* (``"bp"``), *step names*
    (``"compute_gap"``) and *messages with no value in them* are not market
    numbers and are not what this guards — the guard is about a **value that
    should have been computed arriving as a constant**, which is why it looks for
    digits attached to a unit rather than for digits.
    """
    # A digit-run followed by a market unit, e.g. "140bp", "4.5%", "26 bp".
    import re

    market_number = re.compile(r"\d+(?:\.\d+)?\s*(?:bp|bps|percent)\b", re.IGNORECASE)
    offenders: list[str] = []
    for lineno, literal in _code_string_constants(_STREAM_SOURCE):
        if market_number.search(literal):
            offenders.append(f"line {lineno}: {literal!r}")

    assert not offenders, (
        "reasoning_stream.py contains a hardcoded market number in a string "
        f"constant: {offenders}. Section 8.3's defect is exactly this — a value "
        "that should be measured arriving as a literal. The kind of value is "
        "fine ('gap = '), the number is not."
    )


def test_the_stream_never_assembles_a_gap_or_convergence_from_a_constant() -> None:
    """The same property, one level up: the detail must interpolate a value.

    ``f"convergence=HIGH"`` contains no digits, so the digit guard above would
    miss it — and it is one of §8.3's four literal details. This checks that the
    ``compute_gap``, ``run_models`` and ``classify_convergence`` frames each
    contain at least one interpolated expression, i.e. that they are **built from
    a value** rather than typed.

    "Contains an F-string" is not enough, and that is the whole subtlety:
    ``f"{len(rules)} models completed"`` interpolates a COUNT and still tells a
    reader nothing about what the models produced. So the guard requires the
    interpolation to reach **at least one expression that is not a ``len(...)``
    call** — the mutant ``M8.2`` is exactly that shape, and it is the one
    §8.3 mutation a naive "does it interpolate" check would let through.
    """
    generator = _stream_body_node()

    constant_only: list[str] = []
    count_only: list[str] = []
    #: ``(step, status)`` pairs — NOT step alone. ``run_models`` is emitted twice:
    #: a ``started`` frame ("Running the policy rules and the gap") that is
    #: correctly a constant, and the ``done`` frame that must carry the values.
    #: Keying on the step alone flagged the progress note as a fabricated result,
    #: which is a guard manufacturing findings (lesson 80).
    wanted = {
        ("compute_gap", "done"),
        ("run_models", "done"),
        ("classify_convergence", "done"),
    }
    seen: set[tuple[str, str]] = set()
    for node in ast.walk(generator):
        if not isinstance(node, ast.Call):
            continue
        if ast.unparse(node.func) != "_event" or len(node.args) < 3:
            continue
        step, status = node.args[0], node.args[1]
        if not isinstance(step, ast.Constant) or not isinstance(status, ast.Constant):
            continue
        key = (str(step.value), str(status.value))
        if key not in wanted:
            continue
        seen.add(key)

        # Walk the WHOLE detail expression, not just a top-level JoinedStr: the
        # `run_models` detail is `f"..." + ", ".join(f"..." for ...)`, so its
        # interpolations live inside a BinOp and a generator expression.
        formatted = [
            child for child in ast.walk(node.args[2]) if isinstance(child, ast.FormattedValue)
        ]
        if not formatted:
            constant_only.append(f"{key[0]}/{key[1]}")
            continue
        if all(ast.unparse(f.value).startswith("len(") for f in formatted):
            count_only.append(f"{key[0]}/{key[1]}")

    assert seen == wanted, f"the guard did not find every frame it names; found {sorted(seen)}"
    assert not constant_only, (
        f"these stream frames are constant strings: {constant_only}. A frame with "
        f"no interpolation cannot disagree with itself, which is exactly what "
        f"makes a fabricated detail survive every behavioural test."
    )
    assert not count_only, (
        f"these stream frames interpolate only a length: {count_only}. §8.3's "
        f"'9 models completed' is a count that cannot be wrong because it is not "
        f"measured — the trace must say WHICH rules produced WHAT."
    )


# ---------------------------------------------------------------------------
# 2. Configured, not hardcoded
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("function", "accessor"),
    [
        ("_yoy_tolerance_days", "api.yoy_match_tolerance_days"),
        ("_percentile_window_months", "labor.quits_percentile_window_months"),
    ],
)
def test_the_tunable_reaches_the_computation_through_config(
    function: str,
    accessor: str,
) -> None:
    """A reviewer-visible knob that is not read is D-037's inert-input class.

    ``M2.2`` and ``M3.4`` replace these accessors with literals, and the
    behaviour is unchanged **under the shipped config** — which is why no
    behavioural test can see it and why the guard has to read the source.

    The accessor is checked by its leaf name (``yoy_match_tolerance_days``)
    rather than by the full dotted path, because the two are reached through
    different settings roots and a guard that hardcoded the root would be a guard
    on the settings tree's shape rather than on the read.
    """
    node = _function_node(_ORCH_SOURCE, function)

    calls = _calls_in(node)
    assert "get_settings" in calls, (
        f"{function} does not call get_settings(), so its value cannot come from "
        f"config. A literal here makes {accessor} an inert input."
    )
    attributes = {child.attr for child in ast.walk(node) if isinstance(child, ast.Attribute)}
    leaf = accessor.rsplit(".", 1)[1]
    assert leaf in attributes, (
        f"{function} never reads the {leaf!r} attribute; expected {accessor}. A "
        f"knob a reviewer can see and the code does not read is worse than no knob."
    )


def test_the_configured_leaves_exist_and_are_reviewable() -> None:
    """Both knobs exist on the settings object, with a calibration status.

    The ``ast`` guard above proves the read happens; this proves the leaf it
    reads is real and carries the envelope every other leaf in this project
    carries. Together they mean the knob is published AND connected.
    """
    settings = get_settings()

    assert settings.api.yoy_match_tolerance_days == 5
    # NOTE: the accessor already returns an int, so there is no .value here. An
    # earlier draft of this test read `.value` and failed with
    # `'int' object has no attribute 'value'` — the same mistake the sweep's
    # M2.2 mutant is built to punish, made in the guard rather than in the code.
    assert isinstance(settings.labor.quits_percentile_window, int)
    assert settings.labor.quits_percentile_window == 36
    assert settings.labor.quits_percentile_window_months.value == 36.0
    for leaf in (
        settings.api.yoy_match_tolerance_days_value,
        settings.labor.quits_percentile_window_months,
        settings.api.default_thesis_type_value,
        settings.api.short_yield_tenor_value,
    ):
        assert leaf.calibration_status, "a config leaf with no calibration status is unreviewable"


def test_the_yoy_tolerance_excludes_the_adjacent_month() -> None:
    """The tolerance's *value* is load-bearing, not decorative.

    A tolerance that admitted the neighbouring month (28-31 days away) would
    silently convert a 29-day comparison into a "year-over-year" one — which is
    the defect the guard exists to catch, restored through the config door. This
    asserts the relationship rather than the number, so widening the tolerance to
    30 days fails here even though ``M2.1``'s mutant would still be caught.
    """
    tolerance = get_settings().api.yoy_match_tolerance_days

    assert tolerance < 28, (
        f"api.yoy_match_tolerance_days is {tolerance}. A tolerance of 28 or more "
        f"admits a monthly series' neighbouring month, which converts a 29-day "
        f"comparison into an annual one — the exact mislabelling this guard "
        f"exists to prevent."
    )
    assert tolerance >= 1, "a zero tolerance refuses a weekly series legitimately 1 day off"


# ---------------------------------------------------------------------------
# 3. The status-code table
# ---------------------------------------------------------------------------


def test_every_documented_status_code_is_distinct_and_present() -> None:
    """501 / 502 / 500 are three different claims and must stay three.

    ``_http_status_for`` maps an exception onto a code. A mutant that collapsed
    two of them would be invisible to a test that only exercises the classes it
    hits — so the guard reads the function's structure and asserts the codes are
    the ones the module docstring documents.

    Read through the function object rather than by parsing where possible:
    ``inspect.getsource`` is used only to confirm the mapping is *complete*, and
    the codes themselves are checked by calling the function, which is the
    strongest form available (the mapping is pure).
    """
    from macro_engine.api_layer.orchestration import OrchestrationError
    from macro_engine.api_layer.snapshot_provider import SnapshotUnavailableError

    not_implemented = _http_status_for(NotImplementedError("x"), country="de")
    unavailable = _http_status_for(SnapshotUnavailableError("x"), country="us")
    orchestration_failure = _http_status_for(
        OrchestrationError("x", fields=("pce_core",)), country="us"
    )

    assert not_implemented.status_code == 501, (
        "an unimplemented country is a capability gap, not a dependency failure. "
        "502 would send a caller to retry a provider that is working."
    )
    assert unavailable.status_code == 502
    assert orchestration_failure.status_code == 502
    assert orchestration_failure.status_code != not_implemented.status_code, (
        "501 and 502 are different claims: 'this capability does not exist' versus "
        "'the capability ran and the dependency failed'."
    )
    assert "pce_core" in orchestration_failure.detail, (
        "the 502 for an unusable field must name the field, or the caller cannot "
        "tell which series to inspect."
    )


def test_an_unmapped_exception_is_re_raised_not_dressed() -> None:
    """``_http_status_for`` must not invent a status for a class it does not know.

    A catch-all would mean a defect in this service arrives as a plausible
    dependency failure — the 500/502 distinction would stop carrying information,
    and ``test_a_builder_failure_is_a_500`` would no longer prove anything.
    """
    with pytest.raises(ValueError, match="not a known failure class"):
        _http_status_for(ValueError("not a known failure class"), country="us")


def test_the_builder_failure_path_is_deliberately_a_500() -> None:
    """Read structurally: the builder's ``except`` raises 500, not 502.

    ``M5.3`` swaps this and no behavioural test can see the difference unless it
    triggers a builder bug, which by definition does not exist in a green tree.
    """
    node = _function_node(_THESIS_SOURCE, "get_thesis")

    codes: list[int] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Raise) or not isinstance(child.exc, ast.Call):
            continue
        for keyword in child.exc.keywords:
            if keyword.arg != "status_code" or not isinstance(keyword.value, ast.Constant):
                continue
            status = keyword.value.value
            if isinstance(status, int) and not isinstance(status, bool):
                codes.append(status)

    assert 500 in codes, (
        "get_thesis no longer raises a 500 anywhere. The two 502 classes exist so "
        "that a 500 means 'this code is wrong'; without it a builder defect is "
        "reported as a data condition."
    )
    assert codes.count(500) == 1, (
        f"expected exactly one 500 (the builder path), found {codes.count(500)} in {codes}"
    )


# ---------------------------------------------------------------------------
# 4. The CORS / loopback pair (Section 8.4)
# ---------------------------------------------------------------------------


def test_a_permissive_cors_list_cannot_be_configured_on_a_network_bind() -> None:
    """The pair is enforced, not documented.

    No route test can construct this configuration — it is a *settings* refusal,
    raised at load time. The guard therefore builds the invalid object directly
    and asserts it is rejected, which is the only way to test a validator whose
    whole job is to prevent the object existing.
    """
    from pydantic import ValidationError

    from macro_engine.config import ApiSettings

    # ``model_validate`` rather than the constructor: the envelopes arrive as
    # plain dicts in the YAML-parsed shape, which is exactly how the invalid
    # configuration would reach the loader. Typing them as ``CalibratedValue``
    # would let the test construct an object the loader could never produce.
    with pytest.raises(ValidationError, match="loopback"):
        ApiSettings.model_validate(
            {
                # A deliberate non-loopback bind, to prove the validator refuses
                # it. Written as a concatenation so the literal never appears in
                # the source as a bindable address (S104 cannot know this is a
                # config object rather than a socket).
                "host_value": {
                    "value": "0.0." + "0.0",
                    "calibration_status": "institutional_fact",
                },
                "cors_origins_value": {
                    "value": ["*"],
                    "calibration_status": "institutional_convention",
                },
            }
        )


def test_the_shipped_config_is_loopback_only() -> None:
    """The default posture is the safe one, and it is published as a value."""
    settings = get_settings()

    assert settings.api.loopback_only is True
    assert settings.api.host in {"127.0.0.1", "localhost", "::1"}


def test_loopback_only_is_computed_from_the_bind_not_hardcoded() -> None:
    """``loopback_only`` must be a function of the bind, proven by a FALSE case.

    ``M9.5`` replaces the set-membership check with ``return True``. Asserting
    the property is True under the shipped config cannot kill it, because the
    shipped host is loopback and ``True == True`` — the guard would be a
    tautology that manufactures a green (lesson 80). The only assertion that
    separates a computed property from a constant is one where they DISAGREE,
    so this test constructs a reachable non-loopback bind and requires False.
    """
    from macro_engine.config import ApiSettings

    # A non-loopback bind with restrictive CORS, so the 8.4 pairing validator
    # permits the object: this is a *legal* configuration, and 8.4's whole
    # point is that such a service must still report itself as reachable.
    # ``ApiSettings`` IS the api block — ``get_settings().api`` is the object
    # this class instantiates, so the properties live on it directly.
    api = ApiSettings.model_validate(
        {
            "host_value": {"value": "10.0.0.5", "calibration_status": "institutional_fact"},
            "cors_origins_value": {
                "value": ["https://internal.example"],
                "calibration_status": "institutional_convention",
            },
        }
    )

    assert api.host == "10.0.0.5", "the test's own premise is wrong: the bind did not take."
    assert api.loopback_only is False, (
        "loopback_only reported True for a non-loopback bind — it is a constant, "
        "not a measurement, and a caller cannot tell whether the service is "
        "reachable off this machine."
    )


# ---------------------------------------------------------------------------
# 5. The version constant is shared, not duplicated
# ---------------------------------------------------------------------------


def test_the_health_version_is_the_app_version() -> None:
    """One constant, two readers — pinned against an INDEPENDENT source.

    ``M10.2`` changes the constant's value. Asserting only
    ``app.version == routes_health.SERVICE_VERSION`` cannot kill it: both sides
    read the same constant, so they move together and the comparison is
    self-referential (lesson 80). The property that matters is that the constant
    agrees with the project's declared version, which lives in ``pyproject.toml``
    and is therefore the one thing a mutation cannot move in lockstep.
    """
    import tomllib

    import macro_engine.api_layer.app as app_module

    pyproject = tomllib.loads(
        (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    )
    declared = pyproject["project"]["version"]

    assert declared == routes_health.SERVICE_VERSION, (
        f"routes_health.SERVICE_VERSION is {routes_health.SERVICE_VERSION!r} but "
        f"pyproject.toml declares {declared!r}; the API advertises a version the "
        f"package does not have, and a client pinning versions talks to the "
        f"wrong build."
    )

    app = app_module.create_app()

    assert app.version == routes_health.SERVICE_VERSION
    assert app.title == "Macro Reasoning Engine"


def test_the_service_constants_are_module_level_and_single() -> None:
    """The version string appears exactly once in the tree's api_layer.

    A second copy is the mechanism by which the two readers drift; asserting the
    count is the structural version of the test above.
    """
    api_layer = Path(reasoning_stream.__file__).parent
    declarations: list[str] = []
    for path in sorted(api_layer.glob("*.py")):
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "SERVICE_VERSION":
                        declarations.append(f"{path.name}:{node.lineno}")

    assert len(declarations) == 1, (
        f"SERVICE_VERSION is declared {len(declarations)} times "
        f"({declarations}); it must be declared once so /health and the app "
        f"factory cannot drift."
    )
    assert declarations[0].startswith("routes_health.py:"), (
        f"SERVICE_VERSION must live in routes_health.py (the module both readers "
        f"already import); found it in {declarations[0]}."
    )


# ---------------------------------------------------------------------------
# 6. The routers that must not build a second thesis definition
# ---------------------------------------------------------------------------


def test_no_router_imports_the_builder_before_the_orchestration() -> None:
    """Every router gets its arguments from ``snapshot_to_thesis_inputs``.

    A router that called ``build_us_macro_thesis`` with its own hand-assembled
    arguments would be a second definition of the derivation — and the one place
    this project's incumbents have repeatedly found literals
    (``live_builder_check.py``: ``0.2 / 0.3 / 0.1 / -0.4``). This guard asserts
    that each module which *calls* the builder also *imports* the orchestration.
    """
    for module, source in (
        (routes_thesis, _THESIS_SOURCE),
        (reasoning_stream, _STREAM_SOURCE),
    ):
        tree = ast.parse(source)
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        calls_builder = "build_us_macro_thesis" in {
            ast.unparse(call.func) for call in ast.walk(tree) if isinstance(call, ast.Call)
        }
        if calls_builder:
            assert "snapshot_to_thesis_inputs" in imported, (
                f"{module.__name__} calls the builder without importing the "
                f"orchestration that derives its required arguments — the module "
                f"would have to assemble them itself."
            )


def test_the_stream_and_the_rest_endpoint_share_the_orchestration_entry_point() -> None:
    """``/thesis`` and ``/thesis/.../stream`` must not diverge.

    They build the same object by different routes; if one grew its own
    derivation the two endpoints would answer the same question differently and
    nothing would say so. This is the structural half of that — the behavioural
    half is ``test_routes.py``'s cross-check against a separately built thesis.
    """
    thesis_calls = _calls_in(_function_node(_THESIS_SOURCE, "get_thesis"))
    # Follow the delegation: the derivation call lives in the stream's body
    # function, which the outer terminator guard wraps. See ``_stream_body_node``.
    stream_calls = _calls_in(_stream_body_node())

    for name, calls in (
        ("get_thesis", thesis_calls),
        ("the stream's body function", stream_calls),
    ):
        assert "snapshot_to_thesis_inputs" in calls, (
            f"{name} does not call snapshot_to_thesis_inputs(); it must obtain the "
            f"builder's six required arguments from the one derivation module."
        )


def test_the_orchestration_is_the_only_module_that_reads_snapshot_fields_for_the_builder() -> None:
    """``snapshot.iorb`` / ``snapshot.pce_core`` belong in one file.

    If a router read a snapshot field directly, the unit traps this increment
    measured (thousands vs percent; rate vs percentile; persons vs 4-week percent
    change) would be re-opened one endpoint at a time. This is structural: only
    ``orchestration.py`` may attribute a snapshot series for a builder argument.
    """
    guarded_fields = ("iorb", "pce_core", "jolts_openings", "jolts_quits", "initial_claims")

    for module in (routes_thesis, routes_dashboard, routes_query, reasoning_stream, routes_health):
        source = inspect.getsource(module)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute) or node.attr not in guarded_fields:
                continue
            value = node.value
            is_snapshot_read = isinstance(value, ast.Name) and value.id in {"snapshot", "snap"}
            assert not is_snapshot_read, (
                f"{module.__name__} reads snapshot.{node.attr} directly. The unit "
                f"conversions for these series are the orchestration's job; a "
                f"router that reads them re-opens the measured unit traps."
            )


# ---------------------------------------------------------------------------
# 7. The routing admission is always passed, never defaulted
# ---------------------------------------------------------------------------


def test_every_query_response_construction_passes_the_routing_flag_explicitly() -> None:
    """``is_keyword_routing`` must never be inherited from its default.

    ``M7.1`` flips ``Field(default=True)`` to ``False``. Two separate properties
    are asserted here, because either alone leaves a hole:

    1. **Every construction site states it.** The handler passes
       ``is_keyword_routing=True`` explicitly on both return paths, so the
       default is unreachable *today* — but that is a fact about the current call
       sites, not a guarantee. A third site that omitted the flag would silently
       take the default.
    2. **The default itself is the safe value.** Even with every site explicit,
       the field default is what any future caller inherits, and the safe
       direction is ``True``: this field is an admission that no inference
       happened, and defaulting it to ``False`` claims a model spoke when one did
       not. A client gating on the flag would render a routing description as an
       answer.
    """
    tree = ast.parse(Path(routes_query.__file__).read_text(encoding="utf-8"))
    sites = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and ast.unparse(node.func).endswith("QueryResponse")
    ]

    assert sites, (
        "no QueryResponse construction found — this guard is scanning the wrong "
        "module and its green result would be meaningless (lesson 80)."
    )
    for call in sites:
        passed = {keyword.arg for keyword in call.keywords}
        assert "is_keyword_routing" in passed, (
            f"QueryResponse(...) at line {call.lineno} omits is_keyword_routing, "
            f"so the response silently inherits the field default. The admission "
            f"that no inference happened must be stated at every construction "
            f"site, not defaulted (M7.1)."
        )

    # The default, read off the real field rather than the source text (lesson
    # 5bf: pin structure, not spelling).
    field = QueryResponse.model_fields["is_keyword_routing"]

    assert field.default is True, (
        f"is_keyword_routing defaults to {field.default!r}. It must default to "
        f"True: an unset field means the caller did not say a model reasoned, and "
        f"the honest reading of silence is 'no inference', not 'a model spoke' "
        f"(M7.1)."
    )


# ---------------------------------------------------------------------------
# The live check talks to its own server, not through a proxy
# ---------------------------------------------------------------------------


_LIVE_CHECK_SOURCE = Path(
    Path(__file__).resolve().parents[2] / "scripts" / "live_api_check.py"
).read_text(encoding="utf-8")


def _httpx_client_calls(tree: ast.AST) -> list[ast.Call]:
    """Every ``httpx.Client(...)`` construction in the module."""
    found: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "Client"
            and isinstance(func.value, ast.Name)
            and func.value.id == "httpx"
        ):
            found.append(node)
    return found


def test_the_live_check_does_not_route_its_loopback_traffic_through_a_proxy() -> None:
    """Every ``httpx.Client`` in the live check must set ``trust_env=False``.

    This is the guard for the defect the check found in D-070, and it is a
    **source** property for the same reason every other guard here is.

    The defect: this environment exports ``HTTP_PROXY``/``HTTPS_PROXY``. ``httpx``
    honours them by default (``trust_env=True``), so the check's requests went
    through a forward proxy. A proxy must receive the **absolute-URI** request
    form (RFC 7230 §5.3.2), it forwards that URI to the origin, uvicorn unquotes
    the whole thing into the path, no route matches, and ``GET /health`` returned

        404 {"detail": "Not Found"}

    Doubly deceptive: the *first* request on a fresh connection survived, so it
    read as an intermittent routing bug in a route that is registered and correct.

    Why this cannot be a behavioural test: the unit suite drives ``TestClient``,
    which never opens a socket — so no unit test can observe it. And a behavioural
    guard would have to *be* the live check, which the default test run excludes.
    Reading the source is the only place left, and it is sufficient: the property
    is "the client was constructed without honouring the proxy environment", which
    is exactly what the source says.
    """
    calls = _httpx_client_calls(ast.parse(_LIVE_CHECK_SOURCE))

    assert calls, (
        "no httpx.Client construction found in scripts/live_api_check.py — this "
        "guard is scanning the wrong file and its green result would be "
        "meaningless (lesson 80)."
    )

    for call in calls:
        keywords = {keyword.arg: keyword.value for keyword in call.keywords}
        trust_env = keywords.get("trust_env")

        assert trust_env is not None, (
            f"httpx.Client(...) at scripts/live_api_check.py:{call.lineno} does not "
            f"set trust_env explicitly. httpx defaults to trust_env=True, which "
            f"honours HTTP_PROXY/HTTPS_PROXY — and a proxied request goes out as an "
            f"absolute URI, which uvicorn reads as the path, producing a 404 from a "
            f"route that exists."
        )
        assert not (isinstance(trust_env, ast.Constant) and trust_env.value is True), (
            f"httpx.Client(...) at scripts/live_api_check.py:{call.lineno} sets "
            f"trust_env=True. The live check's only peer is a loopback socket it "
            f"opened itself; routing that through a third party measures the proxy, "
            f"not the service."
        )


def test_the_live_check_prints_the_proxy_environment_it_is_ignoring() -> None:
    """The check must disclose the proxy variables rather than silently skip them.

    ``trust_env=False`` fixes the request, but it also means the run's behaviour
    depends on an environment fact that is otherwise invisible — and a check whose
    result depends on an unprinted environment variable is a check nobody can
    reproduce. So the guard requires the names to appear in the module: if the
    disclosure is ever dropped, this fails, and the failure says why.
    """
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        assert f'"{name}"' in _LIVE_CHECK_SOURCE, (
            f"scripts/live_api_check.py no longer references {name}. `trust_env=False` "
            f"ignores the proxy, but the run must still REPORT that these variables "
            f"were present and ignored — a result that depends on an unprinted "
            f"environment is not reproducible."
        )
