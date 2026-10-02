"""Hand-computed tests for Module 15 / Section 16.4 — ``select_instrument``.

Every expected value below comes from the CONFIG leaves or from arithmetic, not
from running the code:

    instrument_selection.default_short_tenor     = "2y"
    instrument_selection.default_long_tenor      = "10y"
    instrument_selection.minimum_leg_gap_years   = 1.0
    instrument_selection.maximum_leg_years       = 30.0
    instrument_selection.heuristic_not_calibrated = True
    instrument_selection.independence_count      = 0

    confidence = 0.70 - 0.20 (heuristic) + min(0 * 0.05, 0.25) = 0.50
    — the SAME value on the executable and the sentinel branches, because a
      routing decision carries no corroboration either way.

Routes (4): policy_path_gap, curve_shape_gap, inflation_expectations_gap,
equity_macro. Sentinels (3): cross_country_divergence -> BLOCKED;
credit_quality_gap and em_vulnerability -> ANALYTICAL_ONLY.
"""

from __future__ import annotations

import pytest

from macro_engine.config import get_settings
from macro_engine.models.instrument_selection import (
    ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT,
    BLOCKED_MULTI_COUNTRY_NOT_BUILT,
    GapDirection,
    InstrumentSelectionInputs,
    ThesisType,
    select_instrument,
    _parse_tenor_years,
    _selection_value,
)
from macro_engine.thesis_layer.schemas import ProductionUniverse

UNIVERSE = ProductionUniverse()


def sel(thesis_type, gap_direction=GapDirection.POSITIVE, **kw):
    return select_instrument(
        InstrumentSelectionInputs(
            thesis_type=thesis_type, gap_direction=gap_direction, **kw
        ),
        UNIVERSE,
    )


# ---------------------------------------------------------------------------
# F-IS-001 — the `direction` field must not leak the string "None"
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "thesis_type",
    [
        ThesisType.POLICY_PATH_GAP,
        ThesisType.INFLATION_EXPECTATIONS_GAP,
        ThesisType.EQUITY_MACRO,
    ],
)
def test_direction_does_not_leak_none_on_non_curve_routes(thesis_type):
    """`direction` was an f-string on `direction_word`, which is None off the curve.

    The three non-curve executable routes therefore published literally
    "None: the thesis's gap direction, expressed through <instrument>" — a
    None-leak that also reads as a *finding* (the direction was evaluated and
    found absent) when in fact gap_direction is required, validated and listed in
    `inputs_used`. The module's own decision_prohibition says the result "MUST
    NOT be consumed without `direction_word`", so the branch produced the one
    field that prohibition depends on, containing the word "None".
    """
    res = sel(thesis_type)
    assert res.direction is not None
    assert "None" not in res.direction, f"direction leaked None: {res.direction!r}"
    # The direction is genuinely known and must still be stated.
    assert "positive" in res.direction.lower()


def test_direction_states_the_sign_on_non_curve_routes():
    res = sel(ThesisType.EQUITY_MACRO, gap_direction=GapDirection.NEGATIVE)
    assert "negative" in res.direction.lower()
    assert "down" in res.direction.lower()


def test_direction_uses_the_slope_word_on_the_curve_route():
    res = sel(ThesisType.CURVE_SHAPE_GAP, gap_direction=GapDirection.POSITIVE)
    assert res.direction.startswith("steepener")


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------
def test_every_thesis_type_routes_without_raising():
    """All 7 members: 4 executable, 1 blocked, 2 analytical."""
    routed = {}
    for t in ThesisType:
        res = sel(t)
        routed[t] = res.value
    assert len(routed) == 7


def test_blocked_multi_country_sentinel():
    res = sel(ThesisType.CROSS_COUNTRY_DIVERGENCE)
    assert res.value == BLOCKED_MULTI_COUNTRY_NOT_BUILT


@pytest.mark.parametrize(
    "thesis_type", [ThesisType.CREDIT_QUALITY_GAP, ThesisType.EM_VULNERABILITY]
)
def test_analytical_only_sentinel(thesis_type):
    res = sel(thesis_type)
    assert res.value == ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT


def test_sentinel_value_is_a_bare_string_not_a_dict():
    """The two-shape contract (O-87) — sentinels are NOT the dict shape."""
    res = sel(ThesisType.CREDIT_QUALITY_GAP)
    assert isinstance(res.value, str)


def test_sentinel_confidence_is_computed_not_zero():
    """A sentinel is a CONFIDENT negative; 0.0 would report it as unknown."""
    res = sel(ThesisType.CROSS_COUNTRY_DIVERGENCE)
    assert res.confidence == pytest.approx(0.50)
    assert res.confidence > 0.0


def test_executable_confidence_matches_the_sentinel_confidence():
    """Same inputs to compute_confidence, so the same number."""
    a = sel(ThesisType.CROSS_COUNTRY_DIVERGENCE).confidence
    b = sel(ThesisType.POLICY_PATH_GAP).confidence
    assert a == pytest.approx(b)


def test_executable_value_has_the_documented_keys():
    res = sel(ThesisType.POLICY_PATH_GAP)
    assert set(res.value) == {
        "instrument",
        "universe_category",
        "executable",
        "rationale",
        "direction_word",
    }
    assert res.value["executable"] is True
    assert res.value["universe_category"] == "rates"


def test_equity_route_is_classified_equity():
    res = sel(ThesisType.EQUITY_MACRO)
    assert res.value["universe_category"] == "equity"
    assert res.value["instrument"] == "Broad equity indices (ES, NQ, RTY)"


def test_policy_path_instrument_names_the_tu_contract():
    res = sel(ThesisType.POLICY_PATH_GAP)
    assert res.value["instrument"] == "UST 2yr note futures"


# ---------------------------------------------------------------------------
# gap_direction is CONSUMED, not merely carried (D-037 / D-058 defect 2)
# ---------------------------------------------------------------------------
def test_gap_direction_changes_the_curve_instrument():
    up = sel(ThesisType.CURVE_SHAPE_GAP, gap_direction=GapDirection.POSITIVE)
    down = sel(ThesisType.CURVE_SHAPE_GAP, gap_direction=GapDirection.NEGATIVE)
    assert up.value["direction_word"] == "steepener"
    assert down.value["direction_word"] == "flattener"
    assert up.value["instrument"] != down.value["instrument"]
    assert "steepener" in up.value["instrument"]
    assert "flattener" in down.value["instrument"]


def test_gap_direction_is_recorded_as_consumed():
    assert "gap_direction" in sel(ThesisType.POLICY_PATH_GAP).inputs_used


# ---------------------------------------------------------------------------
# Tenors
# ---------------------------------------------------------------------------
def test_default_legs_are_the_configured_2y_10y():
    res = sel(ThesisType.CURVE_SHAPE_GAP)
    assert res.value["instrument"] == "Duration-weighted 2y/10y UST steepener"


def test_both_legs_supplied():
    res = sel(
        ThesisType.CURVE_SHAPE_GAP, curve_short_tenor="5y", curve_long_tenor="30y"
    )
    assert res.value["instrument"] == "Duration-weighted 5y/30y UST steepener"


def test_one_leg_supplied_defaults_the_other():
    res = sel(ThesisType.CURVE_SHAPE_GAP, curve_short_tenor="5y")
    assert res.value["instrument"] == "Duration-weighted 5y/10y UST steepener"
    res = sel(ThesisType.CURVE_SHAPE_GAP, curve_long_tenor="5y")
    assert res.value["instrument"] == "Duration-weighted 2y/5y UST steepener"


def test_tenors_on_a_non_curve_route_are_refused():
    """Silently dropping them is how a caller thinks they were honoured."""
    with pytest.raises(ValueError, match="no curve legs"):
        sel(ThesisType.POLICY_PATH_GAP, curve_short_tenor="2y")


def test_inverted_legs_are_refused():
    with pytest.raises(ValueError, match="short-to-long"):
        sel(ThesisType.CURVE_SHAPE_GAP, curve_short_tenor="10y", curve_long_tenor="2y")


def test_equal_legs_are_refused():
    with pytest.raises(ValueError, match="short-to-long"):
        sel(ThesisType.CURVE_SHAPE_GAP, curve_short_tenor="2y", curve_long_tenor="2y")


def test_legs_closer_than_the_configured_minimum_are_refused():
    """2y to 2.5y is a 0.5y gap against a 1.0y minimum."""
    with pytest.raises(ValueError, match="minimum"):
        sel(ThesisType.CURVE_SHAPE_GAP, curve_short_tenor="2y", curve_long_tenor="2.5y")


def test_long_leg_beyond_the_configured_maximum_is_refused():
    with pytest.raises(ValueError, match="maximum"):
        sel(ThesisType.CURVE_SHAPE_GAP, curve_long_tenor="50y")


def test_unparseable_tenor_is_refused():
    with pytest.raises(ValueError, match="Unrecognised tenor"):
        sel(ThesisType.CURVE_SHAPE_GAP, curve_short_tenor="long")


@pytest.mark.parametrize(
    "text,years",
    [
        ("2y", 2.0),
        ("10yr", 10.0),
        ("6m", 0.5),
        ("3mo", 0.25),
        ("1w", pytest.approx(1 / 52)),
        ("2 Y", 2.0),
    ],
)
def test_tenor_parser_units(text, years):
    assert _parse_tenor_years(text) == years


def test_tenor_parser_rejects_a_bare_word():
    with pytest.raises(ValueError, match="Unrecognised tenor"):
        _parse_tenor_years("long end")


# ---------------------------------------------------------------------------
# The universe boundary (Section 22.12) — exercised with stubs
# ---------------------------------------------------------------------------
class _StubUniverse:
    def __init__(self, category="rates", permits=True):
        self._category = category
        self._permits = permits

    def category_for(self, instrument):
        return self._category

    def permits(self, instrument):
        return self._permits


def _select_with(universe, **kw):
    return select_instrument(
        InstrumentSelectionInputs(
            thesis_type=ThesisType.POLICY_PATH_GAP,
            gap_direction=GapDirection.POSITIVE,
            **kw,
        ),
        universe,
    )


def test_out_of_universe_instrument_is_refused():
    with pytest.raises(ValueError, match="OUTSIDE the production execution universe"):
        _select_with(_StubUniverse(category=None))


def test_category_disagreeing_with_the_route_is_refused():
    with pytest.raises(ValueError, match="declares universe_category"):
        _select_with(_StubUniverse(category="fx"))


def test_classified_but_not_permitted_is_refused():
    """The third guard: `permits` is checked in addition to `category_for`."""
    with pytest.raises(ValueError, match="does not"):
        _select_with(_StubUniverse(category="rates", permits=False))


def test_the_real_universe_accepts_all_four_executable_routes():
    """The shipped templates must survive their own matcher."""
    for t in (
        ThesisType.POLICY_PATH_GAP,
        ThesisType.CURVE_SHAPE_GAP,
        ThesisType.INFLATION_EXPECTATIONS_GAP,
        ThesisType.EQUITY_MACRO,
    ):
        res = sel(t)
        assert res.value["executable"] is True
        assert UNIVERSE.permits(res.value["instrument"])


# ---------------------------------------------------------------------------
# F-IS-003 — `_selection_value` must not claim a shape the function violates
# ---------------------------------------------------------------------------
def test_selection_value_accepts_the_executable_shape():
    res = sel(ThesisType.POLICY_PATH_GAP)
    assert _selection_value(res)["instrument"] == "UST 2yr note futures"


def test_selection_value_rejects_the_sentinel_shape():
    """A sentinel is a bare str, so the dict-only helper must raise on it."""
    res = sel(ThesisType.CREDIT_QUALITY_GAP)
    with pytest.raises(TypeError):
        _selection_value(res)


def test_selection_value_does_not_claim_always_dict():
    """O-87: the helper's RAISE text asserts 'always returns a dict value'.

    select_instrument returns TWO shapes — a dict on the executable routes and a
    bare sentinel string on the refused ones — so the claim is false, and it
    fires on precisely the case a caller most needs explained. A reader who hits
    this TypeError is told the function broke a contract the function never made.
    """
    res = sel(ThesisType.CREDIT_QUALITY_GAP)
    with pytest.raises(TypeError) as exc:
        _selection_value(res)
    assert "always returns a dict value" not in str(exc.value)


# ---------------------------------------------------------------------------
# LAW 1 — no literals
# ---------------------------------------------------------------------------
def test_thresholds_come_from_config():
    s = get_settings().instrument_selection
    assert s.default_short_tenor == "2y"
    assert s.default_long_tenor == "10y"
    assert s.minimum_leg_gap_years == pytest.approx(1.0)
    assert s.maximum_leg_years == pytest.approx(30.0)
    assert s.heuristic_not_calibrated is True
    assert s.independence_count == 0


def test_all_four_route_templates_come_from_config():
    s = get_settings().instrument_selection
    assert set(s.routes) == {
        "policy_path_gap",
        "curve_shape_gap",
        "inflation_expectations_gap",
        "equity_macro",
    }
    for name, route in s.routes.items():
        assert "instrument_template" in route
        assert "universe_category" in route
