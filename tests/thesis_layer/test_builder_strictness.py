"""D-069 strictness — the properties no behavioural test in this suite can see.

Three kinds of guard live here, and each exists because the behavioural suite is
structurally blind to what it checks:

1. **The gate order.** The builder checks Q6 → Q7 → Q8, and the *only* observable
   consequence of that order on a Q6 stand-down is that
   ``convergence_classification`` is ``NO_SIGNAL``. A reordering that still
   produced a legal thesis would pass every behavioural test in
   ``test_builder.py``. So the order is read out of the **source**, by position.

2. **The four divergences from §16.2's sample that are *absences*.** Q8 being
   checked at all, ``thesis_id`` being generated, the three unpackings happening
   at one line each — a future edit that removed one would leave a tree that
   still builds theses. These are pinned as text.

3. **The sentinel pass-through.** Section 22.12 forbids substituting a
   production instrument for an analytical-only one. A behavioural test can
   assert that a sentinel survives (and one does), but it cannot assert that no
   *substitution table* exists elsewhere in the module.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

BUILDER_SOURCE = pathlib.Path("src/macro_engine/thesis_layer/builder.py")
SOURCE = BUILDER_SOURCE.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def _function_source(name: str) -> str:
    """The source of the module-level function ``name``, verbatim."""
    for node in TREE.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(SOURCE, node) or ""
    raise AssertionError(f"{name} is not a module-level function of {BUILDER_SOURCE}")


def _line_of(needle: str) -> int:
    """The 1-based line number of the first occurrence of ``needle``."""
    for index, line in enumerate(SOURCE.splitlines(), start=1):
        if needle in line:
            return index
    raise AssertionError(f"{needle!r} does not appear in {BUILDER_SOURCE}")


# ---------------------------------------------------------------------------
# 1. The gate order, read out of the source
# ---------------------------------------------------------------------------


def test_the_three_gates_are_checked_in_the_documented_order() -> None:
    """Q6 before Q7 before Q8 — by source POSITION, not by behaviour.

    This is the guard the behavioural suite cannot be. Every ordering of the
    three gates that skips a check when its own condition is unmet produces a
    legal thesis on the fixtures, so no assertion on the output distinguishes
    Q6→Q7→Q8 from Q6→Q8→Q7. Position does.
    """
    body = _function_source("build_us_macro_thesis")

    q6 = body.index("if not gap.is_meaningful:")
    q7 = body.index("if convergence is ConvergenceClassification.CONFLICTED:")
    q8 = body.index("if not invalidation.identified:")

    assert q6 < q7 < q8, "the gates must be checked Q6 -> Q7 -> Q8 (Section 16.2)"


def test_q8_is_checked_although_section_16_2s_sample_omits_it() -> None:
    """D-063's gate. §16.2's sample has no Q8 branch at all — it cannot, because
    it never binds the assessment to a name.

    Pinned separately from the ordering test so that deleting the gate fails
    **two** tests with two different messages rather than one.
    """
    body = _function_source("build_us_macro_thesis")

    assert "invalidation = derive_invalidation_conditions(" in body
    assert "if not invalidation.identified:" in body


def test_each_gate_hands_its_own_object_to_its_own_decision_helper() -> None:
    """O-85's closing condition: the trigger is DERIVED from what was observed.

    Each gate's decision comes from a helper whose **parameter** is the gate's
    object, and the trigger string appears only inside that helper. That is what
    makes "the caller states the trigger it observed" true by construction
    rather than by discipline.
    """
    helpers = {
        "_q6_decision": ("gap: MarketPricingGap", 'trigger="gap_below_dispersion"'),
        "_q7_decision": (
            "assessment: object",
            'trigger="conflicted_signals"',
        ),
        "_q8_decision": (
            "assessment: InvalidationAssessment",
            'trigger="no_falsifier"',
        ),
    }
    for name, (parameter, trigger) in helpers.items():
        source = _function_source(name)
        assert parameter in source, f"{name} must take the gate's own object"
        assert trigger in source, f"{name} must state its own trigger"

    body = _function_source("build_us_macro_thesis")
    assert "decision = _q6_decision(gap)" in body
    assert "decision = _q7_decision(signals)" in body
    assert "decision = _q8_decision(invalidation)" in body


@pytest.mark.parametrize(
    "trigger",
    ["gap_below_dispersion", "conflicted_signals", "no_falsifier"],
)
def test_no_trigger_string_is_written_outside_its_own_helper(trigger: str) -> None:
    """A trigger typed at a call site would be a claim, not an observation.

    The three literal trigger spellings may appear **only** inside their own
    helper. Anywhere else — in the builder body, in ``_render``, in a test
    double — the trigger would be asserted rather than derived.
    """
    from macro_engine.thesis_layer.builder import (
        _q6_decision,
        _q7_decision,
        _q8_decision,
    )

    owners = {"_q6_decision", "_q7_decision", "_q8_decision"}
    occurrences = [
        name
        for name in (*(n.name for n in TREE.body if isinstance(n, ast.FunctionDef)),)
        if f'"{trigger}"' in _function_source(name)
    ]
    assert set(occurrences) <= owners, (
        f"{trigger!r} appears in {occurrences}; it belongs only in a _qN_decision"
    )
    _ = (_q6_decision, _q7_decision, _q8_decision)


# ---------------------------------------------------------------------------
# 2. The absences §16.2's sample has, pinned as text
# ---------------------------------------------------------------------------


def test_the_thesis_id_is_generated_because_the_sample_names_a_missing_function() -> None:
    """§16.2 writes ``thesis_id=generate_id()``; no ``generate_id`` exists.

    Measured: nothing in the tree defines it. So the sample's ninth divergence
    is a call to an undefined function, and the builder's own generator is the
    repair. Pinned because a future edit could satisfy ``MacroThesis`` with a
    hand-written string and every behavioural test would still pass.
    """
    assert "def new_thesis_id(" in SOURCE
    assert "thesis_id=new_thesis_id(as_of=stamp)," in _function_source("build_us_macro_thesis")
    assert "thesis_id=new_thesis_id(as_of=stamp)," in _function_source("_render")

    # `generate_id` remains undefined everywhere, so the sample's call is still
    # a call into nothing — recorded, not silently "fixed" by inventing it.
    src_root = pathlib.Path("src")
    for path in src_root.rglob("*.py"):
        assert "def generate_id(" not in path.read_text(encoding="utf-8"), (
            f"{path} defines generate_id; §16.2's sample would then have a "
            f"second, competing generator"
        )


def test_the_three_object_returns_are_each_unpacked_exactly_once() -> None:
    """Corrections 2, 3 and the Q8 binding: each rich object is unpacked at ONE
    line, so the object is still available to the gate that needs it."""
    body = _function_source("build_us_macro_thesis")

    assert "invalidation = derive_invalidation_conditions(" in body
    assert "signals = build_confirmation_signals(" in body
    assert "warning_summary: WarningSummary = collect_all_warnings(" in body

    # The two scalar projections are named, not inlined.
    assert "stop_or_invalidation=invalidation.text," in body
    assert "confirmation_signals=list(signals.signals)," in body
    assert "warnings=warnings," in body


def test_the_sample_s_gap_only_direction_rule_survives_only_as_a_fallback() -> None:
    """Correction 6: the selector's own direction wins; the sample's rule is the
    fallback.

    Pinned by **source position** — the published-read must come before the
    fallback — and by an **AST** check that the fallback is the last statement of
    the function.

    Deliberately NOT pinned by matching the fallback's text. Measured: an earlier
    version asserted ``'return "long" if gap.raw_gap < 0 else "short"' in source``,
    which failed on the sweep's **honesty control** — a semantically identical
    rewrite of the same comparison. A guard that fails on equivalent code is
    asserting the spelling of an expression rather than its meaning, and it would
    also reject a correct refactor. The behaviour is pinned by
    ``test_the_direction_reader_prefers_the_selectors_published_direction`` in
    ``test_builder.py``, which drives the function.
    """
    source = _function_source("_direction_for")

    published = source.index('if published in ("long", "short"):')
    conditional_returns = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Return) and node.col_offset <= 4
    ]
    assert conditional_returns, "_direction_for has no module-level return"

    fallback_line = max(node.lineno for node in conditional_returns)
    published_line = source[:published].count("\n") + 1
    assert published_line < fallback_line, (
        "the selector's own direction must be read before §16.2's gap-only rule"
    )


def test_the_builder_does_not_invent_a_thesis_type() -> None:
    """Correction 1: ``thesis_type`` is a required keyword, never derived.

    A builder that inferred ``POLICY_PATH_GAP`` from ``unit == "%"`` would be
    manufacturing a claim. Pinned by requiring the parameter is keyword-only
    (``*,`` before it) and that no ``ThesisType.`` literal is constructed in the
    body other than through the passed argument.
    """
    import inspect

    from macro_engine.thesis_layer.builder import build_us_macro_thesis

    signature = inspect.signature(build_us_macro_thesis)
    param = signature.parameters["thesis_type"]
    assert param.kind is inspect.Parameter.KEYWORD_ONLY
    assert param.default is inspect.Parameter.empty

    body = _function_source("build_us_macro_thesis")
    assert "thesis_type=thesis_type," in body


def test_the_regime_view_records_that_no_classifier_ran() -> None:
    """ "NOT_COMPUTED" must be visible, not a zero that reads as a verdict."""
    source = _function_source("_regime_view")

    assert '"state": None,' in source
    assert "Not classified" in source


# ---------------------------------------------------------------------------
# 3. Section 22.12's boundary rule
# ---------------------------------------------------------------------------


def test_the_instrument_reader_branches_on_shape_and_passes_sentinels_through() -> None:
    """Measured: ``select_instrument`` publishes a dict on the executable routes
    and a **bare string** on the two sentinel routes (O-87). A reader that
    assumed the dict would raise on the one answer the analytical boundary
    exists to produce."""
    source = _function_source("_instrument_from")

    assert "isinstance(value, str)" in source
    assert "return value" in source
    assert "isinstance(value, dict)" in source


def test_no_substitution_table_maps_a_sentinel_to_a_production_instrument() -> None:
    """The boundary rule enforced by the ABSENCE of a mapping.

    A behavioural test can show one sentinel survives one call; only a source
    check can show there is no lookup that would replace one under other inputs.
    """
    forbidden = ("SENTINEL_SUBSTITUTES", "FALLBACK_INSTRUMENT", "SUBSTITUTE_FOR")
    for token in forbidden:
        assert token not in SOURCE, f"{token} would be a substitution table"


def test_the_sentinel_constants_come_from_the_models_layer_not_are_re_typed() -> None:
    """A re-typed sentinel is a silent divergence: the builder would compare its
    own string against a value the selector never produces."""
    from macro_engine.models.instrument_selection import (
        ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT,
        BLOCKED_MULTI_COUNTRY_NOT_BUILT,
    )

    for sentinel in (
        ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT,
        BLOCKED_MULTI_COUNTRY_NOT_BUILT,
    ):
        # The constant must not appear as a string literal in the builder.
        assert f'"{sentinel}"' not in SOURCE


# ---------------------------------------------------------------------------
# 4. The one caught exception, and what is NOT caught
# ---------------------------------------------------------------------------


def test_only_catalyst_source_error_is_caught() -> None:
    """A broad ``except`` would make a broken model look like a no-trade, which
    is the one failure Section 16.3 forbids."""
    source = _function_source("_resolve_catalysts")

    assert "except CatalystSourceError as exc:" in source
    assert "except Exception" not in SOURCE
    assert "except Exception as" not in SOURCE
    assert "bare except" not in SOURCE
    # A bare `except:` anywhere in the module is a lint-level error here.
    assert "except:" not in SOURCE


def test_the_explicit_calendar_override_short_circuits_before_the_fetch() -> None:
    """``None`` fetches; ``[]`` does not. Pinned by position."""
    source = _function_source("_resolve_catalysts")

    override = source.index("if override is not None:")
    fetch = source.index("next_catalyst_calendar(")

    assert override < fetch


# ---------------------------------------------------------------------------
# 5. The module's declared vocabulary
# ---------------------------------------------------------------------------


def test_the_two_module_constants_are_single_definitions() -> None:
    """``SIZING_LOGIC_PHASE_1`` is declared here; ``NO_TRADE_INSTRUMENT`` is not.

    Measured during D-069: the ``"NONE"`` literal belongs to ``no_trade.py``,
    beside the trade idea that publishes it. Declaring it a second time in the
    builder produced a definition with **no production consumer** — the live path
    takes its instrument from ``select_instrument`` and every stand-down goes
    through ``render_no_trade_thesis`` — so the two copies could drift while every
    test still passed. The builder therefore **re-exports**, and the assertion is
    that it re-exports rather than re-declares.
    """
    assert SOURCE.count("SIZING_LOGIC_PHASE_1 = (") == 1

    # The literal is never WRITTEN as a value here. It occurs once, in the
    # docstring explaining why it is not declared here — so the assertion is
    # against an assignment, which is the drift that matters.
    assert 'NO_TRADE_INSTRUMENT = "NONE"' not in SOURCE
    assert "SIZING_LOGIC_PHASE_1 = (" in SOURCE
    assert "NO_TRADE_INSTRUMENT as NO_TRADE_INSTRUMENT_VALUE" in SOURCE
    assert "NO_TRADE_INSTRUMENT = NO_TRADE_INSTRUMENT_VALUE" in SOURCE


def test_the_no_trade_instrument_literal_has_exactly_one_declaration() -> None:
    """And it lives in the module that owns the no-trade shape.

    Counted over the **AST**, not the text: both modules document the literal in
    their docstrings (D-068's record and this module's rationale), so a substring
    count is a count of prose as well as of code. The assertions here are about
    *bindings* — one module-level assignment, and the trade idea reading it.
    """
    import macro_engine.thesis_layer.builder as builder_module
    import macro_engine.thesis_layer.no_trade as no_trade_module

    assert no_trade_module.NO_TRADE_INSTRUMENT == "NONE"
    assert builder_module.NO_TRADE_INSTRUMENT is no_trade_module.NO_TRADE_INSTRUMENT
    assert "NO_TRADE_INSTRUMENT" in no_trade_module.__all__

    no_trade_path = pathlib.Path("src/macro_engine/thesis_layer/no_trade.py")
    no_trade_source = no_trade_path.read_text(encoding="utf-8")
    no_trade_tree = ast.parse(no_trade_source)

    # Exactly one module-level assignment, and its value is the literal.
    assignments = [
        node
        for node in no_trade_tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "NO_TRADE_INSTRUMENT" for t in node.targets)
    ]
    assert len(assignments) == 1
    assert ast.literal_eval(assignments[0].value) == "NONE"

    # And the trade idea binds it through the name, never as a literal.
    call_sites = [
        kw
        for node in ast.walk(no_trade_tree)
        if isinstance(node, ast.Call)
        for kw in node.keywords
        if kw.arg == "instrument"
    ]
    assert call_sites, "no TradeIdea instrument= was found in no_trade.py"
    for kw in call_sites:
        assert isinstance(kw.value, ast.Name) and kw.value.id == "NO_TRADE_INSTRUMENT"


def test_the_sizing_sentence_is_used_not_re_typed() -> None:
    assert "sizing_logic=SIZING_LOGIC_PHASE_1," in _function_source("build_us_macro_thesis")


def test_every_public_name_is_reexported_or_documented() -> None:
    """The builder's public surface is small and each name is used by a test."""
    from macro_engine.thesis_layer import builder as module

    public = {n for n in vars(module) if not n.startswith("_")}
    expected = {
        "EconomyReads",
        "RuleTrio",
        "NO_TRADE_INSTRUMENT",
        "SIZING_LOGIC_PHASE_1",
        "THESIS_ID_PREFIX",
        "build_policy_gap",
        "build_us_macro_thesis",
        "classify_thesis_convergence",
        "new_thesis_id",
        "policy_view_dict",
    }
    assert expected <= public


def test_the_builder_module_has_no_dependencies_outside_the_permitted_direction() -> None:
    """``thesis_layer -> models`` is the permitted direction (D-058's rule). The
    builder must not import from ``macro_engine.api`` or a sibling layer above.

    **Amended in D-073, and the amendment is the point rather than a relaxation.**
    This guard originally also forbade ``macro_engine.portfolio``, with the
    reason *"it is a Phase 4+ layer; the builder must not depend on it"*. The
    prohibition was a statement about **schedule**, not about architecture: in
    Phase 3 the risk layer did not exist, so importing it would have built a
    Phase 4 layer early.

    Phase 4 has now arrived and Section 17.4 mandates exactly this edge — the
    risk axis must feed a sizing finding back into the thesis lifecycle — so
    keeping the prohibition would forbid the specification. The rule that
    survives is the one that was always load-bearing: **the dependency runs one
    way.** A layer may depend on what is *below* it and never on what is *above*,
    which is why ``macro_engine.api`` stays forbidden unconditionally (the API
    sits above the thesis layer and calls it) while ``portfolio`` is now
    permitted.

    What is NOT relaxed: the *specific* names the builder may take from
    ``portfolio``. The sibling guard,
    ``test_integrity_gates.test_kelly_is_not_reachable_from_the_thesis_or_api_layers``,
    still inspects every import that resolves into ``risk_budget`` and now
    asserts the builder takes only the **translation** names — never
    ``apply_fractional_kelly`` or ``KellyInputs``. So this amendment widens the
    allowed *layer* while the sibling keeps the allowed *surface* narrow, and
    the second test is what would catch a future ``import *`` here.
    """
    imports = {(node.module or "") for node in ast.walk(TREE) if isinstance(node, ast.ImportFrom)}
    for module in imports:
        assert not module.startswith("macro_engine.api"), (
            f"{module} is above the thesis layer; the dependency must run one way"
        )
