"""Tests for Module 15 / Section 16.4 — ``select_instrument`` (Tier 4, D-058).

This module has an unusual shape for this suite: most of what it must prove is
**not arithmetic**. ``select_instrument`` is a router, so its failure modes are
not numerical errors but *category* errors — a name published for something the
desk cannot trade, a parameter accepted and ignored, a routing table entry that
disagrees with the matcher it claims to satisfy.

Three groups of tests, in order of how much they would have caught:

1. **The universe contract** (``ProductionUniverse``). D-058 is the first
   increment to give this class any tests at all — the probe found it had zero
   tests and zero callers (P8), while Section 22.12 makes it the production
   boundary every instrument must pass. Every finding in the probe's P1-P3 and
   P9-P11 rows is a statement about *this* class, so the tests live here.

2. **The emitted instrument must be in universe.** The function's failure
   direction is toward *false executability*: a plausible name for an
   untradeable thing, which then reaches ``TradeIdea.instrument`` where Section
   22.12 says credit/EM/commodity names must never appear. So every executable
   branch is asserted *through* the real matcher, not against a literal.

3. **The routing table itself.** The config declares an instrument template, a
   universe category and a rationale per thesis type; the tests check that each
   route's declared category agrees with what the matcher says about the
   template it emits. A config that disagrees with the matcher makes its note a
   claim rather than a fact.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from macro_engine.config import get_settings
from macro_engine.models.contracts import ModelResult
from macro_engine.models.instrument_selection import (
    ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT,
    BLOCKED_MULTI_COUNTRY_NOT_BUILT,
    GapDirection,
    InstrumentSelectionInputs,
    ThesisType,
    _build_curve_instrument,
    _parse_tenor_years,
    select_instrument,
)
from macro_engine.thesis_layer.schemas import ProductionUniverse
from tests.helpers import as_bool, as_str

# The real boundary object, not a stub: a test that passes a fake universe
# proves the function works with the fake, which is not the claim.
UNIVERSE = ProductionUniverse()


def _select(
    thesis_type: ThesisType,
    direction: GapDirection = GapDirection.POSITIVE,
    *,
    short: str | None = None,
    long: str | None = None,
) -> ModelResult:
    """Call the function with the shipped universe, as the caller eventually will."""
    return select_instrument(
        InstrumentSelectionInputs(
            thesis_type=thesis_type,
            gap_direction=direction,
            curve_short_tenor=short,
            curve_long_tenor=long,
        ),
        UNIVERSE,
    )


def _instrument(result: ModelResult) -> str:
    """Read the instrument name from either result shape.

    The two branch families publish *different value types*, and that is
    deliberate rather than an inconsistency: an executable result carries a
    structured dict (instrument, category, rationale, direction word), while a
    sentinel is a bare verdict string. A sentinel is not a degenerate dict — it
    has no category and no rationale, and manufacturing empty ones would make
    "no instrument" look like an instrument with missing fields.
    """
    if isinstance(result.value, str):
        return result.value
    return as_str(result, key="instrument")


# ---------------------------------------------------------------------------
# The routing table is complete and honest
# ---------------------------------------------------------------------------


def test_every_thesis_type_has_a_route_or_a_sentinel() -> None:
    """No ``ThesisType`` member may fall through to the "unhandled" ``ValueError``.

    The probe's structural finding was that four members route to an instrument
    and three route to a sentinel. This asserts the *total*: every declared
    member produces a result, so a member added to the enum without a route
    fails here rather than raising at a desk.
    """
    for member in ThesisType:
        result = _select(member)
        assert result.model_name == "select_instrument"
        assert _instrument(result)


def test_the_analytical_and_blocked_members_are_the_sentinels() -> None:
    """The three non-executable members return their documented sentinel.

    Named as a table rather than asserted one by one so that *which* members
    are analytical-only is a stated fact. ``credit_quality_gap`` and
    ``em_vulnerability`` are analytical (Section 22.12); the third is blocked
    because it needs a country this system has not built (Section 22.3).

    The value *shape* is part of the assertion: a sentinel is a bare verdict
    string, not a dict with an ``executable: False`` key. Asserting the bare
    string is what makes "there is a shape difference between a routed
    instrument and a refusal" a pinned fact rather than a comment.
    """
    expected = {
        ThesisType.CREDIT_QUALITY_GAP: ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT,
        ThesisType.EM_VULNERABILITY: ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT,
        ThesisType.CROSS_COUNTRY_DIVERGENCE: BLOCKED_MULTI_COUNTRY_NOT_BUILT,
    }
    for member, sentinel in expected.items():
        result = _select(member)
        assert result.value == sentinel, member
        assert isinstance(result.value, str), member


def test_the_four_executable_routes_name_tradeable_instruments() -> None:
    """Every executable branch emits a name the real matcher admits.

    This is the asserted two-sided guard the module docstring describes. It uses
    the shipped ``ProductionUniverse`` rather than a fixed set of strings, so a
    template edited to name an out-of-universe instrument fails here.
    """
    for member in (
        ThesisType.POLICY_PATH_GAP,
        ThesisType.CURVE_SHAPE_GAP,
        ThesisType.INFLATION_EXPECTATIONS_GAP,
        ThesisType.EQUITY_MACRO,
    ):
        result = _select(member)
        instrument = _instrument(result)
        assert isinstance(result.value, dict), member
        assert as_bool(result, key="executable") is True, member
        assert instrument != ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT, member
        assert UNIVERSE.permits(instrument), (member, instrument)


def test_each_route_declares_the_category_the_matcher_observes() -> None:
    """A route's declared ``universe_category`` must equal the matcher's verdict.

    Section 22.3.1's own ``assert universe in PRODUCTION_UNIVERSE`` was vacuous
    (probe P4): it compared a hand-written literal to the set that literal was
    transcribed from. This compares the *emitted name* to the real matcher, which
    is the claim that can actually fail.
    """
    routes = get_settings().instrument_selection.routes
    for member in (
        ThesisType.POLICY_PATH_GAP,
        ThesisType.CURVE_SHAPE_GAP,
        ThesisType.INFLATION_EXPECTATIONS_GAP,
        ThesisType.EQUITY_MACRO,
    ):
        observed = UNIVERSE.category_for(_instrument(_select(member)))
        assert observed == routes[member.value]["universe_category"], member


def test_no_route_declares_equity_index_which_is_not_a_shipped_category() -> None:
    """Section 22.3.1 writes ``"equity_index"``; the shipped vocabulary is ``"equity"``.

    Probe P3/P11. The distinction matters because the config's category is
    checked against ``category_for``'s return value: a category the matcher can
    never return would make every equity route fail its own assertion.
    """
    category = get_settings().instrument_selection.routes[ThesisType.EQUITY_MACRO.value][
        "universe_category"
    ]
    assert category == "equity"
    assert category in {"rates", "fx", "equity"}


def test_an_unroutable_thesis_type_raises_rather_than_defaulting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A routing-table gap must raise, not silently pick a fallback.

    Section 22.3.1 replaced Section 16.2's single-fallback placeholder precisely
    so that no thesis type quietly borrows another's instrument. The config
    routing table is patched to *omit* this type, which is the only way to
    reach the branch — with the shipped YAML every type has a route, so an
    unpatched call would test nothing.

    The patch targets ``macro_engine.models.instrument_selection.get_settings``
    — the name the module bound at import time. Patching
    ``macro_engine.config.get_settings`` would leave the module looking at the
    real settings and the test would silently pass for the wrong reason.
    """
    import macro_engine.models.instrument_selection as module

    real = get_settings().instrument_selection
    # A routing table missing POLICY_PATH_GAP but otherwise real, so the
    # failure is caused by the absent entry rather than by a broken config.
    routes = {k: v for k, v in real.routes.items() if k != ThesisType.POLICY_PATH_GAP.value}
    bare = real.model_copy(update={"thesis_type_routes": {"routes": routes}})

    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: get_settings().model_copy(update={"instrument_selection": bare}),
    )

    inputs = InstrumentSelectionInputs(
        thesis_type=ThesisType.POLICY_PATH_GAP, gap_direction=GapDirection.POSITIVE
    )
    with pytest.raises(ValueError, match="Unhandled thesis_type"):
        select_instrument(inputs, UNIVERSE)


def test_an_out_of_universe_template_is_refused_at_the_call() -> None:
    """A template naming something untradeable must raise here, not at the desk.

    The stand-in universe permits the *other* routes but not the one under test,
    so the failure is caused by this route's emitted name rather than by every
    name failing.
    """
    inputs = InstrumentSelectionInputs(
        thesis_type=ThesisType.POLICY_PATH_GAP, gap_direction=GapDirection.POSITIVE
    )
    with pytest.raises(ValueError, match="OUTSIDE the production execution universe"):
        select_instrument(inputs, _UniverseRejectingPolicyPathGap())


def test_a_route_whose_category_disagrees_with_the_matcher_is_refused() -> None:
    """A declared category the matcher contradicts must raise.

    This is the config-honesty half of the guard. It is also *why* the published
    ``universe_category`` cannot lie: because the function refuses to proceed
    when declared and observed disagree, the two are equal on every result that
    is ever returned — so publishing either one yields the same value, and the
    D-058 sweep's ``M6.4`` is provably inert rather than unpinned.

    Exercised through a universe that classifies the policy-path instrument as
    ``fx`` while the config declares ``rates`` — a single mis-labelled routing
    table entry, which is what this guard exists to catch.
    """
    inputs = InstrumentSelectionInputs(
        thesis_type=ThesisType.POLICY_PATH_GAP, gap_direction=GapDirection.POSITIVE
    )
    with pytest.raises(ValueError, match="classified"):
        select_instrument(inputs, _UniverseReclassifyingEverything())


class _UniverseRejectingPolicyPathGap(ProductionUniverse):
    """Stand-in for a config whose POLICY_PATH_GAP template drifted out of universe.

    Rejects only this route's emitted name; every other instrument behaves as
    the shipped matcher says. That is what a single mis-edited
    ``instrument_template`` looks like from the router's point of view.
    """

    def permits(self, instrument: str) -> bool:
        return instrument != "UST 2yr note futures"

    def category_for(self, instrument: str) -> str | None:
        if instrument == "UST 2yr note futures":
            return None
        return super().category_for(instrument)


class _UniverseReclassifyingEverything(ProductionUniverse):
    """Reports every instrument as ``fx``, whatever its real category.

    The strongest form of the disagreement: no route's declared category can
    match, so *every* executable type exercises the guard.
    """

    def permits(self, instrument: str) -> bool:
        return True

    def category_for(self, instrument: str) -> str | None:
        return "fx"


# ---------------------------------------------------------------------------
# gap_direction is consumed, not merely carried (probe P5)
# ---------------------------------------------------------------------------


def test_gap_direction_selects_the_curve_slope_word() -> None:
    """``positive`` -> steepener, ``negative`` -> flattener.

    Before D-058 the direction reached only ``inputs_used`` — a provenance string
    rather than a consumer — so flipping it changed nothing observable. This
    pins the consumption, and the pair is asserted in both directions so a
    one-way test cannot pass on a function that hardcodes the optimistic word.
    """
    for direction, word in (
        (GapDirection.POSITIVE, "steepener"),
        (GapDirection.NEGATIVE, "flattener"),
    ):
        result = _select(ThesisType.CURVE_SHAPE_GAP, direction)
        assert as_str(result, key="direction_word") == word
        assert word in _instrument(result)


def test_the_curve_direction_word_actually_reaches_the_instrument_name() -> None:
    """The published ``direction_word`` and the name must agree.

    A function could publish the right word and emit the wrong one; this reads
    both and requires consistency.
    """
    result = _select(ThesisType.CURVE_SHAPE_GAP, GapDirection.NEGATIVE)
    assert _instrument(result).endswith(as_str(result, key="direction_word"))


def test_non_curve_routes_publish_no_direction_word() -> None:
    """``direction_word`` is ``None`` where no slope trade was built.

    ``None`` rather than an empty string, matching the "absent is not zero"
    convention the suite uses elsewhere: no direction word was used, which is
    different from a word that happened to be blank.
    """
    for member in (
        ThesisType.POLICY_PATH_GAP,
        ThesisType.INFLATION_EXPECTATIONS_GAP,
        ThesisType.EQUITY_MACRO,
    ):
        result = _select(member)
        assert result.value is not None
        assert isinstance(result.value, dict)
        assert result.value["direction_word"] is None, member


def test_an_unrecognised_direction_is_rejected_at_construction() -> None:
    """``gap_direction`` is a validated vocabulary, not a bare ``str``.

    Section 22.3.1 types it ``str`` with a comment, and the probe found a typo
    would have fallen through to a default branch reporting the optimistic
    answer. ``extra="forbid"`` covers unknown *keys*; the enum covers unknown
    *values*.
    """
    with pytest.raises(ValidationError):
        InstrumentSelectionInputs(
            thesis_type=ThesisType.CURVE_SHAPE_GAP,
            gap_direction="steepening",  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# The curve branch: defaults, custom legs, and the degenerate cases
# ---------------------------------------------------------------------------


def test_curve_defaults_come_from_config_not_from_a_literal() -> None:
    """An omitted leg uses the configured default.

    Section 22.3.1 interpolated the raw ``Optional`` field, producing
    ``"Duration-weighted None/None ..."`` — a string naming no instrument
    (probe P7). The defaults are read from config so a recalibration moves both
    the value and this test.
    """
    settings = get_settings().instrument_selection
    result = _select(ThesisType.CURVE_SHAPE_GAP)
    instrument = _instrument(result)
    assert settings.default_short_tenor in instrument
    assert settings.default_long_tenor in instrument
    assert "None" not in instrument


def test_the_default_tenors_are_read_from_config_not_hardcoded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Moving the config leaf must move the emitted instrument.

    The previous test cannot distinguish a hardcoded ``"2y"`` from a config
    read, because the shipped config value *is* ``"2y"`` — and the D-058 sweep
    proved it: ``CX1``/``CX2`` (which hardcode exactly those strings) survived
    the whole suite. This test changes the leaves to values no literal would
    contain and requires the output to follow, which is the only form that can
    falsify a literal.
    """
    import macro_engine.models.instrument_selection as module

    real = get_settings().instrument_selection
    moved = real.model_copy(
        update={
            "curve_default_short_tenor": real.curve_default_short_tenor.model_copy(
                update={"value": "3y"}
            ),
            "curve_default_long_tenor": real.curve_default_long_tenor.model_copy(
                update={"value": "7y"}
            ),
        }
    )
    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: get_settings().model_copy(update={"instrument_selection": moved}),
    )

    instrument = _instrument(_select(ThesisType.CURVE_SHAPE_GAP))
    assert "3y" in instrument
    assert "7y" in instrument
    assert "2y" not in instrument
    assert "10y" not in instrument


def test_supplying_both_legs_overrides_both_defaults() -> None:
    """Both legs supplied -> both honoured, in the emitted name."""
    result = _select(ThesisType.CURVE_SHAPE_GAP, short="5y", long="30y")
    instrument = _instrument(result)
    assert "5y" in instrument
    assert "30y" in instrument


def test_supplying_one_leg_defaults_only_the_other() -> None:
    """One leg supplied -> the omitted leg falls back, the supplied one is kept.

    The docstring states this is the behaviour because it is what a caller
    editing one leg expects; without this test "supplying one and not the other
    is accepted" would be prose only.
    """
    settings = get_settings().instrument_selection
    result = _select(ThesisType.CURVE_SHAPE_GAP, short="5y")
    instrument = _instrument(result)
    assert "5y" in instrument
    assert settings.default_long_tenor in instrument


def test_tenors_supplied_to_a_non_curve_route_are_refused() -> None:
    """A curve leg on a non-curve route is a category error, not an ignored extra.

    Silently dropping the tenors is how a caller concludes their legs were
    honoured when they were never read.
    """
    with pytest.raises(ValidationError, match="curve legs"):
        InstrumentSelectionInputs(
            thesis_type=ThesisType.POLICY_PATH_GAP,
            gap_direction=GapDirection.POSITIVE,
            curve_short_tenor="2y",
        )


@pytest.mark.parametrize(
    ("short", "long", "match"),
    [
        ("2y", "2y", "ordered short-to-long"),
        ("10y", "2y", "ordered short-to-long"),
        ("2y", "2.5y", "below the configured minimum"),
        ("2y", "50y", "exceeds the configured maximum"),
        ("long", "10y", "Unrecognised tenor"),
    ],
)
def test_degenerate_curve_pairs_are_refused(short: str, long: str, match: str) -> None:
    """Every pair Section 22.3.1's bare f-string accepted is refused, **for the
    stated reason**.

    Parameterised on the exception *message* rather than merely on "it raised",
    because several of these guards overlap: ``("10y", "2y")`` is caught by the
    ordering check in the shipped code but would *equally* be caught by the gap
    check (the gap is ``-8y``, below the minimum), so a test asserting only
    "raises" cannot tell the two apart — and the D-058 sweep proved exactly that,
    reporting ``M2.1`` (ordering check deleted) as an unexplained survivor.

    The lesson is that an overlapping-guard fixture must pin *which* guard fired.
    Asserting the message does that.
    """
    with pytest.raises(ValueError, match=match):
        _build_curve_instrument(
            short,
            long,
            GapDirection.POSITIVE,
            "Duration-weighted {short}/{long} UST {direction_word}",
        )


def test_the_minimum_gap_boundary_lands_off_the_boundary() -> None:
    """A gap *exactly* at the configured minimum is accepted; one below is not.

    The probe's boundary lesson (D-057 lesson 63): a fixture grid that lands on
    the boundary tests the fixture, not the guard. This asserts the accept side
    explicitly and derives the reject side by one step, so the comparison's
    direction is pinned rather than assumed.
    """
    settings = get_settings().instrument_selection
    gap = settings.minimum_leg_gap_years
    # A leg pair exactly `gap` apart: accepted.
    accepted = _build_curve_instrument(
        "2y",
        f"{2.0 + gap:g}y",
        GapDirection.POSITIVE,
        "{short}/{long} UST {direction_word}",
    )
    assert accepted
    # HALF the gap: refused. Requiring `>= gap` and requiring `> gap/2` differ
    # on exactly this input, so the pair distinguishes the shipped bound from a
    # plausible-looking neighbour.
    with pytest.raises(ValueError, match="below the configured minimum"):
        _build_curve_instrument(
            "2y",
            f"{2.0 + gap / 2.0:g}y",
            GapDirection.POSITIVE,
            "{short}/{long} UST {direction_word}",
        )


def test_the_maximum_leg_boundary_is_a_ceiling_not_a_strict_inequality() -> None:
    """A leg exactly at the configured maximum is accepted; beyond it is not.

    ``long_years > maximum`` and ``long_years >= maximum`` agree everywhere
    except on the maximum itself, so the fixture must land there — otherwise the
    test passes for both spellings.
    """
    settings = get_settings().instrument_selection
    maximum = settings.maximum_leg_years
    accepted = _build_curve_instrument(
        "2y",
        f"{maximum:g}y",
        GapDirection.POSITIVE,
        "{short}/{long} UST {direction_word}",
    )
    assert accepted
    with pytest.raises(ValueError, match="exceeds the configured maximum"):
        _build_curve_instrument(
            "2y",
            f"{maximum + 1.0:g}y",
            GapDirection.POSITIVE,
            "{short}/{long} UST {direction_word}",
        )


@pytest.mark.parametrize(
    ("tenor", "expected_years"),
    [
        ("2y", 2.0),
        ("10yr", 10.0),
        ("6m", 0.5),
        ("3mo", 0.25),
        ("30Y", 30.0),
        (" 5y ", 5.0),
    ],
)
def test_tenor_parsing_accepts_the_desk_spellings(tenor: str, expected_years: float) -> None:
    """The parser reads what a desk writes, including case and padding."""
    assert _parse_tenor_years(tenor) == pytest.approx(expected_years)


def test_an_unparseable_tenor_raises_rather_than_returning_none() -> None:
    """Raising keeps the failure at the input boundary.

    A ``None`` return would flow into a comparison that silently passes, so the
    contract is "raise with the accepted forms".
    """
    with pytest.raises(ValueError, match="Unrecognised tenor"):
        _parse_tenor_years("long")


# ---------------------------------------------------------------------------
# Confidence is computed, never asserted (§22.8)
# ---------------------------------------------------------------------------


def test_confidence_is_computed_for_executable_branches() -> None:
    """The published confidence equals ``compute_confidence`` on the config leaves.

    Recomputing it here rather than asserting a number: the point is that the
    value is a *function of config*, so moving a leaf moves the output.
    """
    settings = get_settings().instrument_selection
    result = _select(ThesisType.POLICY_PATH_GAP)
    assert result.confidence == _expected_confidence()
    assert result.confidence > 0.0
    assert settings.heuristic_not_calibrated is True


def test_sentinels_carry_computed_confidence_not_zero() -> None:
    """A sentinel is a confident negative, so it must not report confidence 0.

    Section 22.3.1 returned a hardcoded ``0.0`` for the sentinel branches. That
    is worse than a literal: presenting a *known* structural answer at zero
    confidence states the opposite of the truth (probe P6).
    """
    for member in (
        ThesisType.CREDIT_QUALITY_GAP,
        ThesisType.EM_VULNERABILITY,
        ThesisType.CROSS_COUNTRY_DIVERGENCE,
    ):
        result = _select(member)
        assert result.confidence == _expected_confidence(), member
        assert result.confidence > 0.0, member


def test_the_sentinel_confidence_matches_the_executable_branches() -> None:
    """No hand-set penalty distinguishes them.

    The docstring claims the difference between a sentinel and an instrument is
    a difference of *no* factors. If a later edit adds a sentinel penalty, this
    fails — which is the point: the claim is asserted rather than described.
    """
    executable = _select(ThesisType.POLICY_PATH_GAP).confidence
    sentinel = _select(ThesisType.CREDIT_QUALITY_GAP).confidence
    assert executable == sentinel


def _expected_confidence() -> float:
    """Recompute the confidence from config, so the test tracks recalibration."""
    from macro_engine.models.contracts import ConfidenceInputs, compute_confidence

    settings = get_settings().instrument_selection
    return compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=False,
            is_heuristic_not_calibrated=settings.heuristic_not_calibrated,
            source_independence_count=settings.independence_count,
            depends_on_unobservable=False,
        )
    )


# ---------------------------------------------------------------------------
# The result shape
# ---------------------------------------------------------------------------


def test_the_result_publishes_the_documented_keys() -> None:
    """The five documented keys are present on every executable branch."""
    result = _select(ThesisType.CURVE_SHAPE_GAP)
    assert isinstance(result.value, dict)
    assert set(result.value) == {
        "instrument",
        "universe_category",
        "executable",
        "rationale",
        "direction_word",
    }


def test_the_universe_category_is_the_shipped_vocabulary() -> None:
    """``universe_category`` is one of the three real categories, or absent.

    Read only on the executable branches: a sentinel's value is a bare string
    with no category key at all, which is the shape this function documents.
    """
    for member in ThesisType:
        result = _select(member)
        if not isinstance(result.value, dict):
            assert result.value in {
                ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT,
                BLOCKED_MULTI_COUNTRY_NOT_BUILT,
            }, member
            continue
        assert result.value["universe_category"] in {"rates", "fx", "equity"}, member


def test_sentinels_carry_a_warning_naming_the_constraint() -> None:
    """Each sentinel states *why*, so the caller is not left with a bare string.

    "Not permitted" is not actionable; "credit indices are not in the production
    execution universe" is.
    """
    for member in (
        ThesisType.CREDIT_QUALITY_GAP,
        ThesisType.EM_VULNERABILITY,
        ThesisType.CROSS_COUNTRY_DIVERGENCE,
    ):
        result = _select(member)
        assert result.warnings, member


def test_as_of_is_timezone_aware() -> None:
    """No naive datetimes (project non-negotiable)."""
    result = _select(ThesisType.POLICY_PATH_GAP)
    assert result.as_of.tzinfo is not None
