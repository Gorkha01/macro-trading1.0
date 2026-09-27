"""Hand-verified tests for ``ppp_valuation`` — Module 9.2, Section 20.9.

PPP is the module's **multi-year anchor**, and the tests are organised around
the three things that make it different from the interest-parity functions
beside it — each of which is invisible in the output and easy to undo:

1. **It is a PRICE-LEVEL relation, not an interest-parity one.** It shares no
   input with ``cip_check`` or ``uip_expected_move``; the arithmetic is a
   deviation of an observed market rate from a CONSTRUCTED level. The identity
   tests below pin that: the deviation is recomputed from the two published
   levels, not restated from the function's own intermediate.
2. **The horizon is load-bearing.** PPP carries no timing information, so the
   model WARNS below the configured tactical horizon rather than publishing a
   confident number at a timescale at which the relationship has no content.
   The horizon gates a WARNING only — never a label — and
   ``test_the_status_does_not_depend_on_the_horizon`` holds that separation.
3. **It has exactly THREE states, and two of them are not interchangeable.**
   ``at_parity`` is a real state (the deviation is exactly zero), not a missing
   value; ``_ppp_status`` is derived from the published deviation's SIGN so the
   label and the number cannot disagree.

The hand-derived values are computed with the PPP leg FIXED at ``1.25`` so each
expected number is checkable by hand:

* ``1.30 / 1.25`` -> ``(1.30 - 1.25) / 1.25 * 100 == +4.0``   (overvalued)
* ``1.20 / 1.25`` -> ``-4.0``                                  (undervalued)
* ``1.25 / 1.25`` -> ``0.0``                                   (at parity)

Every assertion is against the PUBLISHED value (``round(deviation_pct, 2)``),
because the raw quotient carries floating-point dust (``4.0000000000000036``)
that the published number deliberately does not.

**Boundary fixtures are built so their exactness is asserted, never assumed**
(lesson 5o). Where a test probes an exactly-equal-to-zero case, it asserts the
input is exactly zero first, so a rebuilt fixture that drifted off the point
fails at the fixture rather than silently testing a different case.
"""

from __future__ import annotations

import math
from typing import get_args

import pytest
from pydantic import ValidationError

from macro_engine.config import CalibratedValue, FxCarrySettings, get_settings
from macro_engine.models.contracts import EvidenceSourceFamily, ModelResult
from macro_engine.models.fx_carry import (
    PPPInputs,
    PPPStatus,
    ppp_valuation,
)
from tests.helpers import as_float, as_str

#: The PPP leg of every fixture, held constant so the expected numbers are
#: checkable by hand. It is also the spot of the parity case.
_PPP_LEG = 1.25

#: A horizon comfortably above the shipped tactical minimum, so the
#: no-tactical-timing warning does NOT fire and a test that wants it must ask
#: for it explicitly.
_LONG_HORIZON = 5.0

#: A horizon plainly below any sane tactical minimum, so the warning fires.
_TACTICAL_HORIZON = 1.0


def _inputs(spot: float, *, horizon_years: float = _LONG_HORIZON, **overrides: object) -> PPPInputs:
    """A ``PPPInputs`` against the fixed ``_PPP_LEG``."""
    base: dict[str, object] = {
        "spot_rate": spot,
        "ppp_implied_rate": _PPP_LEG,
        "horizon_years": horizon_years,
    }
    base.update(overrides)
    return PPPInputs.model_validate(base)


def _dev(result: ModelResult) -> float:
    return as_float(result, key="deviation_pct")


def _status(result: ModelResult) -> str:
    return as_str(result, key="status")


# ---------------------------------------------------------------------------
# The arithmetic, against hand-derived values.
# ---------------------------------------------------------------------------


def test_the_deviation_matches_the_hand_computation() -> None:
    """``(1.30 - 1.25) / 1.25 * 100 == +4`` — the specification's own formula."""
    result = ppp_valuation(_inputs(1.30))
    assert _dev(result) == pytest.approx(4.0)


def test_a_spot_below_the_ppp_leg_gives_a_negative_deviation() -> None:
    """The sign is the verdict: below PPP is a NEGATIVE deviation."""
    result = ppp_valuation(_inputs(1.20))
    assert _dev(result) == pytest.approx(-4.0)


def test_a_spot_at_the_ppp_leg_is_exactly_at_parity() -> None:
    """The parity case is EXACT, and the fixture proves it is exactly the leg.

    A fixture built as ``1.25 + 1e-9`` would still pass a sloppy assertion but
    would not be the case this test names, so the input is asserted first.
    """
    spot = _PPP_LEG
    assert spot == 1.25  # the fixture is exactly on the leg, not near it
    result = ppp_valuation(_inputs(spot))
    assert _dev(result) == 0.0
    assert _status(result) == "at_parity"


def test_the_deviation_is_the_ratio_minus_one_times_a_hundred() -> None:
    """The two published forms are the same number, at the published precision.

    ``ratio - 1`` reconstructs the deviation in FRACTION form and ``* 100``
    recovers the percent — so this is an IDENTITY between two published fields,
    not a restatement of the implementation. The tolerance is set by the COARSER
    side's published precision: ``ratio`` is ``round(ratio, 6)``, so a unit in
    the sixth decimal moves the percent by ~1e-4 (lesson 5cu — a tolerance comes
    from the coarser side's published precision, never from the finer one).
    """
    result = ppp_valuation(_inputs(1.30))
    ratio = as_float(result, key="ratio")
    assert ratio == 1.04
    assert _dev(result) == pytest.approx((ratio - 1.0) * 100.0, abs=1e-3)


def test_the_status_is_derived_from_the_sign_of_the_published_deviation() -> None:
    """Every status is reachable, and each is paired with the right sign.

    The three cases are NOT symmetric: ``at_parity`` is a distinct state, not a
    fallback, so a rewrite that used ``>=`` in the wrong place would merge it
    into ``overvalued`` and this test would catch it.
    """
    over = ppp_valuation(_inputs(1.30))
    under = ppp_valuation(_inputs(1.20))
    par = ppp_valuation(_inputs(1.25))

    assert (_status(over), _dev(over) > 0.0) == ("overvalued", True)
    assert (_status(under), _dev(under) < 0.0) == ("undervalued", True)
    assert (_status(par), _dev(par) == 0.0) == ("at_parity", True)


def test_the_status_vocabulary_is_fully_covered_by_the_fixtures() -> None:
    """The three fixtures above reach every member of ``PPPStatus``.

    Without this, a status could be added to the Literal and no fixture would
    reach it — the vocabulary would grow while the suite stayed silent (the D-037
    class, applied to an output vocabulary rather than a config leaf).
    """
    reached = {_status(ppp_valuation(_inputs(spot))) for spot in (1.30, 1.20, 1.25)}
    assert reached == set(get_args(PPPStatus))


def test_the_published_deviation_is_the_rounded_quotient_not_the_raw_one() -> None:
    """The published field is ``round(x, 2)``; the raw quotient is not published.

    The raw quotient for ``1.30 / 1.25`` is ``4.0000000000000036``. Publishing
    it unrounded would leak floating-point dust into a number a reader is meant
    to quote, so the test pins the ROUNDED value and proves the dust is gone.
    """
    result = ppp_valuation(_inputs(1.30))
    assert _dev(result) == 4.0
    assert _dev(result) != 4.0000000000000036


def test_the_rounding_boundary_follows_rounds_of_the_raw_value() -> None:
    """A raw value just below the .xx5 tie rounds DOWN; one at/above rounds UP.

    This is the only test that can tell ``round(raw, 2)`` from a re-derivation
    of the rounded number: both boundary spots publish a TWO-DECIMAL value that
    is not the naive truncation. The two raw values are computed here and
    asserted, so a rebuilt fixture that drifted off the boundary fails loudly.
    """
    below_raw = (1.3000625 - _PPP_LEG) / _PPP_LEG * 100.0
    above_raw = (1.3001250 - _PPP_LEG) / _PPP_LEG * 100.0

    # Assert the fixtures sit where the test claims: strictly either side of
    # 4.005, so `round` must send them in opposite directions.
    assert below_raw < 4.005 < above_raw, (below_raw, above_raw)

    below = ppp_valuation(_inputs(1.3000625))
    above = ppp_valuation(_inputs(1.3001250))
    assert _dev(below) == round(below_raw, 2)
    assert _dev(above) == round(above_raw, 2)
    # And the shipped rounding really did move them in opposite directions.
    assert _dev(below) == 4.0
    assert _dev(above) == 4.01


def test_the_ratio_is_spot_over_the_ppp_leg() -> None:
    """``ratio == spot / ppp_implied``, published to six places."""
    result = ppp_valuation(_inputs(1.20))
    assert as_float(result, key="ratio") == pytest.approx(0.96, abs=1e-9)


def test_the_published_ratio_is_rounded_to_six_places() -> None:
    """``ratio`` is ``round(x, 6)``, not the raw quotient.

    Every fixture whose spot is a short decimal happens to have a raw ratio that
    IS its own 6-place rounding (``1.30 / 1.25 == 1.04`` exactly), so those
    cases cannot tell the rounded field from the raw one — a mutation that
    dropped the ``round`` would survive them. This test uses a spot with a
    LONGER quotient (``1.23456789 / 1.25 == 0.9876543119999999``) so the rawness
    is visible. The tolerance is the COARSER side's published precision — a unit
    in the sixth decimal is ``5e-7`` (lesson 5cu), not the finer side's.
    """
    spot = 1.23456789
    raw = spot / _PPP_LEG
    assert raw != round(raw, 6), "fixture must have a quotient the rounding moves"

    published = as_float(ppp_valuation(_inputs(spot)), key="ratio")
    assert published == round(raw, 6)
    assert abs(published - raw) <= 5e-7  # within a unit in the sixth decimal


# ---------------------------------------------------------------------------
# The inputs round-trip into ``value``.
# ---------------------------------------------------------------------------


def test_both_levels_and_the_quote_are_published_so_the_sign_is_readable() -> None:
    """The levels travel with the verdict, so no caller context is needed.

    Publishing only ``deviation_pct`` would make an isolated reader unable to
    tell a transposed pair from a genuine valuation gap.
    """
    result = ppp_valuation(_inputs(1.30, quote="foreign_per_domestic"))
    assert as_float(result, key="spot_rate") == pytest.approx(1.30)
    assert as_float(result, key="ppp_implied_rate") == pytest.approx(1.25)
    assert as_str(result, key="quote") == "foreign_per_domestic"


def test_the_ppp_leg_is_published_for_a_pair_that_is_not_the_fixture_leg() -> None:
    """A NON-1.25 leg must round-trip, so a hardcoded default is caught.

    Every other fixture pins the PPP leg at ``1.25``, so a mutation that
    hardcoded ``1.25`` into the published ``ppp_implied_rate`` would survive
    them all. This test uses a different leg (a JPY-per-USD-scale number) and
    checks BOTH that it is echoed back and that the deviation is recomputed
    against IT rather than against the fixture constant — which is also the
    case a unit-confusion splice would break.
    """
    spot, leg = 147.0, 102.0
    result = ppp_valuation(PPPInputs(spot_rate=spot, ppp_implied_rate=leg, horizon_years=10.0))
    assert as_float(result, key="ppp_implied_rate") == pytest.approx(leg)
    assert as_float(result, key="spot_rate") == pytest.approx(spot)
    assert _dev(result) == pytest.approx((spot - leg) / leg * 100.0, abs=1e-2)


def test_the_default_quote_convention_is_domestic_per_foreign() -> None:
    """The default is stated in the published ``quote`` rather than left implicit."""
    result = ppp_valuation(_inputs(1.30))
    assert as_str(result, key="quote") == "domestic_per_foreign"


def test_the_stated_horizon_and_the_configured_threshold_are_both_published() -> None:
    """A reader can see whether and WHY the no-tactical-timing warning fired.

    Both numbers are needed to make the warning auditable: the stated horizon
    alone is not enough to know the threshold, and the threshold alone is not
    enough to know the horizon that was compared against it.
    """
    result = ppp_valuation(_inputs(1.30, horizon_years=_TACTICAL_HORIZON))
    assert as_float(result, key="horizon_years") == pytest.approx(_TACTICAL_HORIZON)
    assert as_float(result, key="tactical_horizon_years") == pytest.approx(
        get_settings().fx_carry.ppp_tactical_horizon_value
    )


def test_the_published_threshold_is_read_from_the_leaf_not_a_literal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Perturbing the leaf must move the PUBLISHED threshold (D-050's trap).

    The shipped leaf is ``3.0``, so the comparison above — against the live
    leaf, itself ``3.0`` — cannot tell a value read from config from a hardcoded
    ``3.0``; the mutation ``tactical_horizon_years = 3.0`` SURVIVED the first
    sweep for exactly this reason. This test moves the leaf to a value no
    retyped literal would equal, so the hardcoded form diverges and is caught.
    The leaf is perturbed on the SHIPPED settings object so the function under
    test reads the same object the test moved.
    """
    leaf = get_settings().fx_carry.ppp_tactical_horizon_years
    monkeypatch.setattr(leaf, "value", 4.75, raising=False)

    result = ppp_valuation(_inputs(1.30, horizon_years=_TACTICAL_HORIZON))
    assert as_float(result, key="tactical_horizon_years") == pytest.approx(4.75)

    monkeypatch.setattr(leaf, "value", 0.5, raising=False)
    moved = ppp_valuation(_inputs(1.30))
    assert as_float(moved, key="tactical_horizon_years") == pytest.approx(0.5)


def test_the_contemporaneous_inputs_are_recorded() -> None:
    assert ppp_valuation(_inputs(1.30)).inputs_used == [
        "spot_rate",
        "ppp_implied_rate",
        "horizon_years",
        "quote",
    ]


# ---------------------------------------------------------------------------
# The horizon gates a WARNING, never a LABEL.
# ---------------------------------------------------------------------------


def test_the_status_does_not_depend_on_the_horizon() -> None:
    """The same input at a tactical and a long horizon carries the SAME label.

    This is the separation the whole function rests on: the horizon decides
    whether the number is USABLE, never what the number IS. A model that let the
    horizon move the label would be silently discarding a well-defined valuation
    because it was asked at an inconvenient timescale.
    """
    tactical = ppp_valuation(_inputs(1.30, horizon_years=_TACTICAL_HORIZON))
    long_run = ppp_valuation(_inputs(1.30, horizon_years=_LONG_HORIZON))
    assert _status(tactical) == _status(long_run) == "overvalued"
    assert _dev(tactical) == _dev(long_run) == 4.0


# ---------------------------------------------------------------------------
# The warning paths. Each branch of ``_ppp_warnings`` gets its own case, and
# each has a negative control that exercises the SAME input with the condition
# removed — so a warning that fired unconditionally would fail the control.
# ---------------------------------------------------------------------------


def test_a_tactical_horizon_warns_that_ppp_cannot_speak_to_it() -> None:
    result = ppp_valuation(_inputs(1.30, horizon_years=_TACTICAL_HORIZON))
    assert any("shorter than PPP's tactical minimum" in w for w in result.warnings)


def test_a_long_horizon_is_silent_about_tactical_timing() -> None:
    """The negative control: the tactical warning must NOT fire at a long horizon."""
    result = ppp_valuation(_inputs(1.30, horizon_years=_LONG_HORIZON))
    assert not any("tactical minimum" in w for w in result.warnings)


def test_a_horizon_exactly_at_the_threshold_does_not_warn() -> None:
    """The guard is STRICTLY below the threshold, so the equal case is silent.

    This is the boundary control that separates ``horizon < threshold`` from
    ``horizon <= threshold`` — with only a 1.0-year and a 5.0-year fixture
    against a 3.0-year threshold, neither probe sits on the boundary and a
    ``<=`` mutation would survive. The horizon is read from the live leaf so the
    fixture cannot drift off the threshold it claims to probe.
    """
    threshold = get_settings().fx_carry.ppp_tactical_horizon_value
    at = ppp_valuation(_inputs(1.30, horizon_years=threshold))
    just_below = ppp_valuation(_inputs(1.30, horizon_years=threshold - 1e-6))
    assert not any("tactical minimum" in w for w in at.warnings)
    assert any("tactical minimum" in w for w in just_below.warnings)


def test_an_overvaluation_at_a_tactical_horizon_carries_the_extra_warning() -> None:
    """The 6.7 misuse stated as its own line: '30 % overvalued' read at 3 months.

    This warning requires TWO conditions — overvalued AND tactical — so it must
    not fire for an UNDERVALUATION at the same horizon.
    """
    result = ppp_valuation(_inputs(1.30, horizon_years=_TACTICAL_HORIZON))
    assert any("mean-reversion story" in w for w in result.warnings)


def test_an_undervaluation_at_a_tactical_horizon_does_not_get_the_overvaluation_line() -> None:
    """The negative control that proves the overvaluation warning is CONDITIONAL.

    An undervaluation at the same tactical horizon still gets the generic
    tactical warning but must NOT get the overvaluation-specific one.
    """
    result = ppp_valuation(_inputs(1.20, horizon_years=_TACTICAL_HORIZON))
    assert any("shorter than PPP's tactical minimum" in w for w in result.warnings)
    assert not any("mean-reversion story" in w for w in result.warnings)


def test_a_deviation_beyond_a_hundred_percent_warns_of_a_data_error() -> None:
    """A four-figure gap is more often a convention error than a market state."""
    result = ppp_valuation(_inputs(2.60))  # (2.60 - 1.25)/1.25*100 == +108 %
    assert _dev(result) == pytest.approx(108.0)
    assert any("UNIT OR CONVENTION ERROR" in w for w in result.warnings)


def test_a_deviation_exactly_at_one_hundred_percent_does_not_warn() -> None:
    """The guard is STRICTLY greater than 100, so exactly 100 % is silent.

    This is the boundary control: it separates ``abs(x) > 100`` from
    ``abs(x) >= 100``, which no ordinary case can distinguish.
    """
    result = ppp_valuation(_inputs(2.50))  # (2.50 - 1.25)/1.25*100 == +100.0 exactly
    assert _dev(result) == pytest.approx(100.0)
    assert not any("UNIT OR CONVENTION ERROR" in w for w in result.warnings)


def test_an_ordinary_long_horizon_call_carries_no_warnings() -> None:
    """The all-clear control: a plausible input at a long horizon warns nothing."""
    result = ppp_valuation(_inputs(1.30, horizon_years=_LONG_HORIZON))
    assert result.warnings == []


# ---------------------------------------------------------------------------
# The standing limitations — published on every call because they are
# STRUCTURAL, not conditional.
# ---------------------------------------------------------------------------


def test_the_callersupplied_ppp_leg_is_disclosed_in_the_limitations() -> None:
    """A caller-supplied leg must not be QUIETER than a fetched one.

    Until D-117 the PPP leg was BLOCKED -> MANUAL and the limitations said so.
    The leg is now FETCHED from the World Bank; a caller MAY override it with a
    literal (which is what keeps unit tests deterministic and offline). **The
    override path must still disclose**, in the same slot with the same weight —
    an override that said nothing would make "which number did the thesis use"
    unanswerable, which is the ambiguity Section 21.1 exists to remove.
    """
    limitations = " | ".join(ppp_valuation(_inputs(1.30)).limitations)
    assert "SUPPLIED BY THE CALLER" in limitations
    assert "vintage is unknown" in limitations


def test_the_fetched_ppp_leg_discloses_it_is_a_disclosed_vintage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The FETCH path discloses provenance AND the vintage distinction.

    The World Bank offers no point-in-time selector, so the fetched value is a
    DISCLOSED vintage rather than a vintage read (PLAN_ppp_source.md §6). The
    disclosure must say so, and must name the fetched provenance.
    """
    monkeypatch.setattr(
        "macro_engine.models.fx_carry.fetch_ppp_implied_rate",
        lambda *a, **k: (0.71, "World Bank PA.NUS.PPP (DEU), 2025 figure, published 2026-07-13."),
    )
    result = ppp_valuation(
        PPPInputs(spot_rate=1.30, domestic_iso3="DEU", foreign_iso3="USA", horizon_years=5.0)
    )
    limitations = " | ".join(result.limitations)
    assert "DISCLOSED VINTAGE" in limitations
    assert "no point-in-time selector" in limitations
    assert "World Bank PA.NUS.PPP (DEU), 2025 figure" in limitations
    assert as_float(result, key="ppp_implied_rate") == pytest.approx(0.71)


def test_omitting_the_rate_without_a_pair_is_refused() -> None:
    """The fetch path needs BOTH legs; an incomplete request fails at validation.

    Refused in the validator rather than at fetch time, so the failure is
    identical offline and online and no network call happens for a malformed
    request.
    """
    with pytest.raises(ValidationError, match="BOTH domestic_iso3 and foreign_iso3"):
        PPPInputs(spot_rate=1.30, horizon_years=5.0)
    with pytest.raises(ValidationError, match="BOTH domestic_iso3 and foreign_iso3"):
        PPPInputs(spot_rate=1.30, domestic_iso3="DEU", horizon_years=5.0)
    with pytest.raises(ValidationError, match="BOTH domestic_iso3 and foreign_iso3"):
        PPPInputs(spot_rate=1.30, foreign_iso3="USA", horizon_years=5.0)


def test_the_limitations_and_prohibitions_are_structural_and_non_empty() -> None:
    """The same five limitations and four prohibitions on every input."""
    long_run = ppp_valuation(_inputs(1.30, horizon_years=_LONG_HORIZON))
    tactical = ppp_valuation(_inputs(1.20, horizon_years=_TACTICAL_HORIZON))
    assert len(long_run.limitations) == 5
    assert long_run.limitations == tactical.limitations
    assert len(long_run.decision_prohibition) == 4
    assert long_run.decision_prohibition == tactical.decision_prohibition


def test_the_balassa_samuelson_caveat_is_published() -> None:
    """The systematic-rich-country bias is named, because it flips a naive read."""
    limitations = " | ".join(ppp_valuation(_inputs(1.30)).limitations)
    assert "Balassa-Samuelson" in limitations


def test_the_prohibition_forbids_tactical_timing() -> None:
    """Section 6.7's 'NEVER use PPP for tactical timing' is carried as a prohibition."""
    prohibitions = " | ".join(ppp_valuation(_inputs(1.30)).decision_prohibition)
    assert "tactical timing" in prohibitions


# ---------------------------------------------------------------------------
# The result contract.
# ---------------------------------------------------------------------------


def test_the_result_names_the_model_family_and_a_percent_unit() -> None:
    result = ppp_valuation(_inputs(1.30))
    assert result.model_name == "ppp_valuation"
    assert result.source_family is EvidenceSourceFamily.MARKET_FX
    assert result.unit is not None
    assert "percent deviation" in result.unit


def test_the_judgement_is_percent_carrying_and_its_size_is_recomputed() -> None:
    """The interpretation states the magnitude the value already carries.

    It is recomputed from the raw deviation rather than read back from the
    rounded field, so a rounded-to-zero deviation still prints the true size.
    """
    result = ppp_valuation(_inputs(1.30))
    assert "4.0%" in result.interpretation
    assert "MULTI-YEAR anchor" in result.interpretation


# ---------------------------------------------------------------------------
# Confidence: a MODEL-SPECIFIC CAP, and the test must tell a leaf from a literal.
# ---------------------------------------------------------------------------


def test_ppp_confidence_is_low() -> None:
    """Section 21.3 requires this test by name. The cap is 0.2, well under 1.

    A bare assertion on the number cannot tell a hardcoded literal from a value
    read from config (D-050's trap). The next test closes that.
    """
    assert ppp_valuation(_inputs(1.30)).confidence == pytest.approx(0.2)


def test_the_confidence_comes_from_the_config_leaf_not_a_literal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Perturbing the leaf must move the published confidence (D-050's trap).

    If the function hardcoded ``0.2``, this test fails — which is the whole
    point. The perturbed value is deliberately one no retyped literal would
    accidentally equal.

    The leaf is perturbed on the SHIPPED settings object rather than by
    rebuilding one, so the function under test reads the same object the test
    moved — a rebuilt ``FxCarrySettings`` would leave the function reading the
    original and the test would pass for the wrong reason.
    """
    leaf = get_settings().fx_carry.ppp_reliability_cap
    monkeypatch.setattr(leaf, "value", 0.037, raising=False)

    result = ppp_valuation(_inputs(1.30))
    assert result.confidence == pytest.approx(0.037)

    monkeypatch.setattr(leaf, "value", 0.611, raising=False)
    assert ppp_valuation(_inputs(1.30)).confidence == pytest.approx(0.611)


def test_the_confidence_is_the_documented_ppp_cap_not_the_uip_cap() -> None:
    """PPP's cap is deliberately ABOVE UIP's, and the ordering is the claim.

    A copy-paste that read ``uip_reliability_value`` here would publish 0.15 and
    this test would catch it — the two leaves are adjacent and easy to confuse.
    """
    fx = get_settings().fx_carry
    result = ppp_valuation(_inputs(1.30))
    assert result.confidence == pytest.approx(fx.ppp_reliability_value)
    assert result.confidence != pytest.approx(fx.uip_reliability_value)
    assert fx.ppp_reliability_value > fx.uip_reliability_value


# ---------------------------------------------------------------------------
# The input domain.
# ---------------------------------------------------------------------------


def test_a_non_positive_ppp_leg_is_refused_by_the_field_bound() -> None:
    """The denominator must be a price level, and the bound catches zero."""
    with pytest.raises(ValidationError, match="ppp_implied_rate"):
        PPPInputs(spot_rate=1.30, ppp_implied_rate=0.0, horizon_years=5.0)


def test_a_negative_ppp_leg_is_refused() -> None:
    """A negative denominator would invert every sign."""
    with pytest.raises(ValidationError, match="ppp_implied_rate"):
        PPPInputs(spot_rate=1.30, ppp_implied_rate=-1.25, horizon_years=5.0)


def test_a_non_positive_horizon_is_refused() -> None:
    with pytest.raises(ValidationError, match="horizon_years"):
        PPPInputs(spot_rate=1.30, ppp_implied_rate=1.25, horizon_years=0.0)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_spot_rate_is_refused(bad: float) -> None:
    """``nan`` passes every ``<=`` comparison, so it needs a finiteness test.

    A guard built only from comparisons never fires for ``nan``: the deviation
    would be published as ``nan`` while the ``status`` comparison silently fell
    to one arm (D-078). ``inf`` passes ``> 0`` and is caught by the same check.
    """
    with pytest.raises(ValidationError, match="spot_rate"):
        PPPInputs(spot_rate=bad, ppp_implied_rate=1.25, horizon_years=5.0)


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_a_non_finite_ppp_leg_is_refused_even_though_it_passes_the_bound(bad: float) -> None:
    """``inf > 0`` satisfies the field bound, so the finiteness check is the guard.

    This is the case the ``gt=0.0`` bound CANNOT see — the reason the validator
    exists rather than trusting the field constraint.
    """
    with pytest.raises(ValidationError, match="ppp_implied_rate"):
        PPPInputs(spot_rate=1.30, ppp_implied_rate=bad, horizon_years=5.0)


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_a_non_finite_horizon_is_refused(bad: float) -> None:
    with pytest.raises(ValidationError, match="horizon_years"):
        PPPInputs(spot_rate=1.30, ppp_implied_rate=1.25, horizon_years=bad)


def test_an_unknown_quote_convention_is_refused() -> None:
    """The convention is a CLOSED vocabulary, checked against ``QuoteConvention``.

    A free string would let a caller record a convention the rest of the module
    does not recognise, and the deviation's sign would then be interpreted under
    a name nothing else honours.
    """
    with pytest.raises(ValidationError, match="quote"):
        PPPInputs(
            spot_rate=1.30,
            ppp_implied_rate=1.25,
            horizon_years=5.0,
            quote="dollars_per_euro",
        )


def test_an_extra_field_is_refused() -> None:
    """``extra='forbid'`` — a typoed input must fail rather than be ignored."""
    with pytest.raises(ValidationError):
        PPPInputs.model_validate(
            {
                "spot_rate": 1.30,
                "ppp_implied_rate": 1.25,
                "horizon_years": 5.0,
                "vintage": "2024",
            }
        )


def test_a_finite_input_is_accepted() -> None:
    """The negative control for the whole domain guard: an ordinary call builds."""
    assert ppp_valuation(_inputs(1.30)).confidence == pytest.approx(0.2)


# ---------------------------------------------------------------------------
# The settings validator for the two new leaves.
# ---------------------------------------------------------------------------


def _fx_carry_settings(**overrides: object) -> FxCarrySettings:
    """The shipped ``fx_carry`` block, so a new required field arrives for free.

    Seeded from ``get_settings().fx_carry`` rather than hand-listed; the
    hand-listed form broke at D-109, D-110 and D-112, and D-114 is the first to
    use the generating form (see the sibling helpers for the full note).
    """
    base: dict[str, object] = dict(get_settings().fx_carry)
    base.update(overrides)
    return FxCarrySettings.model_validate(base)


def test_the_settings_validator_refuses_a_cap_above_one() -> None:
    with pytest.raises(ValidationError, match="ppp_reliability_cap"):
        _fx_carry_settings(
            ppp_reliability_cap=CalibratedValue(
                value=1.5, calibration_status="uncalibrated_illustrative"
            )
        )


def test_the_settings_validator_refuses_a_negative_cap() -> None:
    with pytest.raises(ValidationError, match="ppp_reliability_cap"):
        _fx_carry_settings(
            ppp_reliability_cap=CalibratedValue(
                value=-0.1, calibration_status="uncalibrated_illustrative"
            )
        )


def test_the_settings_validator_admits_the_boundary_caps() -> None:
    """0 and 1 are both admissible — the closed interval's own endpoints."""
    for value in (0.0, 1.0):
        settings = _fx_carry_settings(
            ppp_reliability_cap=CalibratedValue(
                value=value, calibration_status="uncalibrated_illustrative"
            )
        )
        assert settings.ppp_reliability_value == pytest.approx(value)


def test_the_settings_validator_refuses_a_non_positive_tactical_horizon() -> None:
    """A non-positive horizon makes the warning condition unreachable (D-037's class).

    ``horizon_years < 0`` is never true for a positive input, so the safety
    mechanism would be dead vocabulary while the model looked compliant.
    """
    with pytest.raises(ValidationError, match="ppp_tactical_horizon_years"):
        _fx_carry_settings(
            ppp_tactical_horizon_years=CalibratedValue(
                value=0.0, calibration_status="uncalibrated_illustrative"
            )
        )


def test_the_settings_validator_accepts_a_positive_tactical_horizon() -> None:
    """The negative control: an ordinary horizon must construct."""
    settings = _fx_carry_settings()
    assert settings.ppp_tactical_horizon_value == pytest.approx(3.0)


def test_the_tactical_horizon_is_positive_in_the_shipped_config() -> None:
    """The shipped leaf is strictly positive, so the warning is reachable."""
    assert get_settings().fx_carry.ppp_tactical_horizon_value > 0.0


def test_the_shipped_cap_is_inside_the_unit_interval() -> None:
    assert 0.0 <= get_settings().fx_carry.ppp_reliability_value <= 1.0


def test_the_shipped_specification_confidence_is_retained() -> None:
    """The spec's own ``0.2`` is retained verbatim (Section 20.9)."""
    assert math.isclose(get_settings().fx_carry.ppp_reliability_value, 0.2)
