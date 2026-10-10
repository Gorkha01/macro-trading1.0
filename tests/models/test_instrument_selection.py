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

Routes (5): policy_path_gap, curve_shape_gap, inflation_expectations_gap,
equity_macro, cross_country_divergence (D-150 — routes to a cross-market RV
pair when a divergence is supplied, or refuses with a NARROWED sentinel when the
gap is inside the noise band). Sentinels (2 still analytical):
credit_quality_gap and em_vulnerability -> ANALYTICAL_ONLY.
"""

from __future__ import annotations

from typing import Any

import pytest

from macro_engine.config import get_settings
from macro_engine.models.contracts import ModelResult
from macro_engine.models.instrument_selection import (
    ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT,
    BLOCKED_MULTI_COUNTRY_NOT_BUILT,
    GapDirection,
    InstrumentSelectionInputs,
    ThesisType,
    _parse_tenor_years,
    _selection_value,
    select_instrument,
)
from macro_engine.thesis_layer.schemas import ProductionUniverse

UNIVERSE = ProductionUniverse()


def sel(
    thesis_type: str, gap_direction: GapDirection = GapDirection.POSITIVE, **kw: Any
) -> ModelResult:
    return select_instrument(
        InstrumentSelectionInputs(
            thesis_type=thesis_type,  # type: ignore[arg-type]
            gap_direction=gap_direction,
            **kw,
        ),
        UNIVERSE,
    )


def _divergence(*, meaningful: bool = True) -> dict[str, Any]:
    """A well-formed divergence record, as ``cross_country_divergence`` publishes.

    Built here rather than by calling the model so THIS test file stays a test of
    the selector, not of the divergence arithmetic (which
    ``tests/models/test_cross_country.py`` owns).
    """
    divergence_bp = 88.0 if meaningful else 8.0
    return {
        "verdict": "MEANINGFUL_DIVERGENCE" if meaningful else "NO_MEANINGFUL_DIVERGENCE",
        "divergence_bp": divergence_bp,
        "nominal_spread_bp": 190.0,
        "real_rate_a": 1.28,
        "real_rate_b": 0.40,
        "long_leg_country": "us",
        "short_leg_country": "eu",
        "threshold_bp": 25.0,
    }


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
def test_direction_does_not_leak_none_on_non_curve_routes(thesis_type: str) -> None:
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
    assert "None" not in (res.direction or ""), f"direction leaked None: {res.direction!r}"
    # The direction is genuinely known and must still be stated.
    assert "positive" in (res.direction or "").lower()


def test_direction_states_the_sign_on_non_curve_routes() -> None:
    res = sel(ThesisType.EQUITY_MACRO, gap_direction=GapDirection.NEGATIVE)
    assert "negative" in (res.direction or "").lower()
    assert "down" in (res.direction or "").lower()


def test_direction_uses_the_slope_word_on_the_curve_route() -> None:
    res = sel(ThesisType.CURVE_SHAPE_GAP, gap_direction=GapDirection.POSITIVE)
    assert (res.direction or "").startswith("steepener")


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------
def test_every_thesis_type_routes_without_raising() -> None:
    """All 7 members route; the cross-country one needs its divergence supplied."""
    routed: dict[ThesisType, Any] = {}
    for t in ThesisType:
        if t is ThesisType.CROSS_COUNTRY_DIVERGENCE:
            routed[t] = sel(t, cross_country=_divergence()).value
        else:
            routed[t] = sel(t).value
    assert len(routed) == 7


def test_blocked_multi_country_sentinel_now_only_on_a_malformed_record() -> None:
    """D-150: the ``BLOCKED_MULTI_COUNTRY_NOT_BUILT`` sentinel survives, NARROWED.

    Before D-150 this route returned the sentinel for EVERY cross-country call —
    the sentinel's meaning was "no second country exists". Now the branch is
    built: a well-formed divergence names an instrument, and the sentinel fires
    only on a MALFORMED divergence record (one missing the keys the selector
    reads). The widening/narrowing is the point — the sentinel must not be
    deleted, because an un-reconcilable pair is still not expressible.
    """
    res = sel(ThesisType.CROSS_COUNTRY_DIVERGENCE, cross_country={"not": "a record"})
    assert res.value == BLOCKED_MULTI_COUNTRY_NOT_BUILT


@pytest.mark.parametrize(
    "thesis_type", [ThesisType.CREDIT_QUALITY_GAP, ThesisType.EM_VULNERABILITY]
)
def test_analytical_only_sentinel(thesis_type: str) -> None:
    res = sel(thesis_type)
    assert res.value == ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT


def test_sentinel_value_is_a_bare_string_not_a_dict() -> None:
    """The two-shape contract (O-87) — sentinels are NOT the dict shape."""
    res = sel(ThesisType.CREDIT_QUALITY_GAP)
    assert isinstance(res.value, str)


def test_sentinel_confidence_is_computed_not_zero() -> None:
    """A sentinel is a CONFIDENT negative; 0.0 would report it as unknown."""
    res = sel(ThesisType.CREDIT_QUALITY_GAP)
    assert res.confidence == pytest.approx(0.50)
    assert res.confidence > 0.0


def test_executable_confidence_matches_the_sentinel_confidence() -> None:
    """Same inputs to compute_confidence, so the same number."""
    a = sel(ThesisType.CROSS_COUNTRY_DIVERGENCE, cross_country=_divergence()).confidence
    b = sel(ThesisType.POLICY_PATH_GAP).confidence
    assert a == pytest.approx(b)


def test_executable_value_has_the_documented_keys() -> None:
    res = sel(ThesisType.POLICY_PATH_GAP)
    assert set(res.value_dict()) == {
        "instrument",
        "universe_category",
        "executable",
        "rationale",
        "direction_word",
    }
    assert res.value_dict()["executable"] is True
    assert res.value_dict()["universe_category"] == "rates"


def test_equity_route_is_classified_equity() -> None:
    res = sel(ThesisType.EQUITY_MACRO)
    assert res.value_dict()["universe_category"] == "equity"
    assert res.value_dict()["instrument"] == "Broad equity indices (ES, NQ, RTY)"


def test_policy_path_instrument_names_the_tu_contract() -> None:
    res = sel(ThesisType.POLICY_PATH_GAP)
    assert res.value_dict()["instrument"] == "UST 2yr note futures"


# ---------------------------------------------------------------------------
# gap_direction is CONSUMED, not merely carried (D-037 / D-058 defect 2)
# ---------------------------------------------------------------------------
def test_gap_direction_changes_the_curve_instrument() -> None:
    up = sel(ThesisType.CURVE_SHAPE_GAP, gap_direction=GapDirection.POSITIVE)
    down = sel(ThesisType.CURVE_SHAPE_GAP, gap_direction=GapDirection.NEGATIVE)
    assert up.value_dict()["direction_word"] == "steepener"
    assert down.value_dict()["direction_word"] == "flattener"
    assert up.value_dict()["instrument"] != down.value_dict()["instrument"]
    assert "steepener" in up.value_dict()["instrument"]
    assert "flattener" in down.value_dict()["instrument"]


def test_gap_direction_is_recorded_as_consumed() -> None:
    assert "gap_direction" in sel(ThesisType.POLICY_PATH_GAP).inputs_used


# ---------------------------------------------------------------------------
# Tenors
# ---------------------------------------------------------------------------
def test_default_legs_are_the_configured_2y_10y() -> None:
    res = sel(ThesisType.CURVE_SHAPE_GAP)
    assert res.value_dict()["instrument"] == "Duration-weighted 2y/10y UST steepener"


def test_both_legs_supplied() -> None:
    res = sel(ThesisType.CURVE_SHAPE_GAP, curve_short_tenor="5y", curve_long_tenor="30y")
    assert res.value_dict()["instrument"] == "Duration-weighted 5y/30y UST steepener"


def test_one_leg_supplied_defaults_the_other() -> None:
    res = sel(ThesisType.CURVE_SHAPE_GAP, curve_short_tenor="5y")
    assert res.value_dict()["instrument"] == "Duration-weighted 5y/10y UST steepener"
    res = sel(ThesisType.CURVE_SHAPE_GAP, curve_long_tenor="5y")
    assert res.value_dict()["instrument"] == "Duration-weighted 2y/5y UST steepener"


def test_tenors_on_a_non_curve_route_are_refused() -> None:
    """Silently dropping them is how a caller thinks they were honoured."""
    with pytest.raises(ValueError, match="no curve legs"):
        sel(ThesisType.POLICY_PATH_GAP, curve_short_tenor="2y")


def test_inverted_legs_are_refused() -> None:
    with pytest.raises(ValueError, match="short-to-long"):
        sel(ThesisType.CURVE_SHAPE_GAP, curve_short_tenor="10y", curve_long_tenor="2y")


def test_equal_legs_are_refused() -> None:
    with pytest.raises(ValueError, match="short-to-long"):
        sel(ThesisType.CURVE_SHAPE_GAP, curve_short_tenor="2y", curve_long_tenor="2y")


def test_legs_closer_than_the_configured_minimum_are_refused() -> None:
    """2y to 2.5y is a 0.5y gap against a 1.0y minimum."""
    with pytest.raises(ValueError, match="minimum"):
        sel(ThesisType.CURVE_SHAPE_GAP, curve_short_tenor="2y", curve_long_tenor="2.5y")


def test_long_leg_beyond_the_configured_maximum_is_refused() -> None:
    with pytest.raises(ValueError, match="maximum"):
        sel(ThesisType.CURVE_SHAPE_GAP, curve_long_tenor="50y")


def test_unparseable_tenor_is_refused() -> None:
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
def test_tenor_parser_units(text: str, years: float) -> None:
    assert _parse_tenor_years(text) == years


def test_tenor_parser_rejects_a_bare_word() -> None:
    with pytest.raises(ValueError, match="Unrecognised tenor"):
        _parse_tenor_years("long end")


# ---------------------------------------------------------------------------
# The universe boundary (Section 22.12) — exercised with stubs
# ---------------------------------------------------------------------------
class _StubUniverse:
    def __init__(self, category: str = "rates", permits: bool = True) -> None:
        self._category = category
        self._permits = permits

    def category_for(self, instrument: str) -> str:
        return self._category

    def permits(self, instrument: str) -> bool:
        return self._permits


def _select_with(universe: object, **kw: Any) -> ModelResult:
    return select_instrument(
        InstrumentSelectionInputs(
            thesis_type=ThesisType.POLICY_PATH_GAP,
            gap_direction=GapDirection.POSITIVE,
            **kw,
        ),
        universe,  # type: ignore[arg-type]
    )


def test_out_of_universe_instrument_is_refused() -> None:
    with pytest.raises(ValueError, match="OUTSIDE the production execution universe"):
        _select_with(_StubUniverse(category=None))  # type: ignore[arg-type]


def test_category_disagreeing_with_the_route_is_refused() -> None:
    with pytest.raises(ValueError, match="declares universe_category"):
        _select_with(_StubUniverse(category="fx"))


def test_classified_but_not_permitted_is_refused() -> None:
    """The third guard: `permits` is checked in addition to `category_for`."""
    with pytest.raises(ValueError, match="does not"):
        _select_with(_StubUniverse(category="rates", permits=False))


def test_the_real_universe_accepts_all_four_executable_routes() -> None:
    """The shipped templates must survive their own matcher."""
    for t in (
        ThesisType.POLICY_PATH_GAP,
        ThesisType.CURVE_SHAPE_GAP,
        ThesisType.INFLATION_EXPECTATIONS_GAP,
        ThesisType.EQUITY_MACRO,
    ):
        res = sel(t)
        assert res.value_dict()["executable"] is True
        assert UNIVERSE.permits(res.value_dict()["instrument"])


# ---------------------------------------------------------------------------
# F-IS-003 — `_selection_value` must not claim a shape the function violates
# ---------------------------------------------------------------------------
def test_selection_value_accepts_the_executable_shape() -> None:
    res = sel(ThesisType.POLICY_PATH_GAP)
    assert _selection_value(res)["instrument"] == "UST 2yr note futures"


def test_selection_value_rejects_the_sentinel_shape() -> None:
    """A sentinel is a bare str, so the dict-only helper must raise on it."""
    res = sel(ThesisType.CREDIT_QUALITY_GAP)
    with pytest.raises(TypeError):
        _selection_value(res)


def test_selection_value_does_not_claim_always_dict() -> None:
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
def test_thresholds_come_from_config() -> None:
    s = get_settings().instrument_selection
    assert s.default_short_tenor == "2y"
    assert s.default_long_tenor == "10y"
    assert s.minimum_leg_gap_years == pytest.approx(1.0)
    assert s.maximum_leg_years == pytest.approx(30.0)
    assert s.heuristic_not_calibrated is True
    assert s.independence_count == 0


def test_all_four_route_templates_come_from_config() -> None:
    s = get_settings().instrument_selection
    assert set(s.routes) == {
        "policy_path_gap",
        "curve_shape_gap",
        "inflation_expectations_gap",
        "equity_macro",
    }
    for _name, route in s.routes.items():
        assert "instrument_template" in route
        assert "universe_category" in route


# ---------------------------------------------------------------------------
# Section 22.3 — country-aware routing (the WS3 instrument set per country)
#
# `routes_for(country)` overlays a country's overrides onto the base (US) table.
# The claim each country's table must satisfy is two-sided: every template it
# names must be PERMITTED by that country's own ProductionUniverse, and the
# country's policy-path template must NOT be the base table's — otherwise the
# country is the US relabelled, which is exactly what §22.3 rejects.
# ---------------------------------------------------------------------------
def _country_universe(country: str) -> ProductionUniverse:
    return ProductionUniverse(country=country)


def test_every_country_route_names_an_instrument_its_own_universe_permits() -> None:
    """(§22.3) each country's templates survive ITS OWN universe's matcher.

    This is the config-vs-universe contract: a route table that named an
    instrument outside the country's plan would be caught at call time by
    ``select_instrument``'s own guard, but making it a config-level test means a
    bad template fails review rather than a live run.

    The curve route's template carries ``{short}``/``{long}``/``{direction_word}``
    placeholders, so it is formatted with the configured default legs before the
    membership check — the string a caller would actually receive.
    """
    settings = get_settings().instrument_selection
    for country in ("us", "gb", "eu"):
        universe = _country_universe(country)
        routes = settings.routes_for(country)
        # The base table must carry all four routes; a country overlay may add
        # nothing, but a missing base route is a routing-table gap.
        assert set(routes) == {
            "policy_path_gap",
            "curve_shape_gap",
            "inflation_expectations_gap",
            "equity_macro",
        }, f"{country} is missing a route: {sorted(routes)}"
        for name, route in routes.items():
            instrument = route["instrument_template"]
            if name == "curve_shape_gap":
                instrument = instrument.format(
                    short=settings.default_short_tenor,
                    long=settings.default_long_tenor,
                    direction_word="steepener",
                )
            assert universe.category_for(instrument) == route["universe_category"], (
                f"{country}.{name} names {instrument!r}, which its universe "
                f"classifies {universe.category_for(instrument)!r} but the route "
                f"declares {route['universe_category']!r}"
            )
            assert universe.permits(instrument), (
                f"{country}.{name} names {instrument!r}, which its own universe "
                f"refuses — this is the §22.12 boundary failure"
            )


def test_each_countrys_policy_path_template_is_not_the_base_tables() -> None:
    """(§22.3) gb and eu do NOT route ``policy_path_gap`` to the US instrument.

    The anti-relabel test at the ROUTE level. The base table's policy-path
    template names a UST; a country that inherited it unchanged would serve the
    US instrument to a non-US thesis. Measured, each of gb/eu overrides it with
    its own policy-expectations contract (short sterling / ESTR).
    """
    settings = get_settings().instrument_selection
    base = settings.routes_for("us")["policy_path_gap"]["instrument_template"]
    assert base == "UST 2yr note futures"

    for country, expected in (
        ("gb", "Short-sterling futures (SONIA 3m)"),
        ("eu", "ESTR futures"),
    ):
        overridden = settings.routes_for(country)["policy_path_gap"]["instrument_template"]
        assert overridden == expected, (
            f"{country}'s policy-path template is {overridden!r}, expected "
            f"{expected!r} — an inherited US template is the §22.3 relabel"
        )
        assert overridden != base


def test_the_eu_policy_path_instrument_is_refused_by_the_us_and_gb_universes() -> None:
    """(§22.3) ESTR is the euro area's, and no other country's.

    The load-bearing isolation for the eu routes: the policy-path instrument the
    eu table names must be admissible ONLY in the eu universe. Measured, ``ESTR``
    appears in no US or UK keyword set, so both refuse it.

    The curve and equity templates are deliberately NOT asserted this way,
    because their discriminating words (``steepener``, ``index futures``) are the
    SHARED shape vocabulary — a known and documented design decision, not a leak.
    The ROUTE TABLE is what keeps a eu template out of a us/gb thesis.
    """
    eu = _country_universe("eu")
    us = _country_universe("us")
    gb = _country_universe("gb")
    assert eu.category_for("ESTR futures") == "rates"
    assert us.category_for("ESTR futures") is None
    assert gb.category_for("ESTR futures") is None
