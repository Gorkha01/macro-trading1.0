"""``thesis_layer/schemas.py`` — the MacroThesis contract, and four measured defects.

Why this file exists
--------------------
Before the 2026-10-06 review **this module had no test of its own**: `MacroThesis`
and `TradeIdea` were referenced by ZERO tests, and `ProductionUniverse` by exactly
one (``tests/models/test_instrument_selection.py``). Every ``model_validator`` on
``MacroThesis`` — the LTCM invalidation gate, the CONFLICTED-blocks-trade gate, the
scenario-sum gate, the status/distribution consistency gate — was therefore
unexercised, which is how the four defects below survived.

The defects, all MEASURED rather than argued:

(F-TSC-001) ``category_for``'s note gave ``"US HY credit index"`` as the example
    the exclusion-first ordering guards. That string carries no keyword at all
    (bare ``"index"`` is not one), so it was never the case being guarded. The
    ordering is still right; the example was not.
(F-TSC-002) The no-trade sentinel was compared case-SENSITIVELY in ``TradeIdea``
    and case-INSENSITIVELY in ``ProductionUniverse``, so ``"none"`` meant "no
    trade" in one class and "a live trade that must state a direction and a
    falsifier" in the other — D-058 probe P17's one-character split, re-created
    one class away.
(F-TSC-003) ``ProductionUniverse._G10_CURRENCIES`` was declared and never read;
    its own comment explains that the set lives at MODULE scope, which is what
    makes the class attribute redundant.
(F-TSC-004) The scenario-sum gate read ``validation.prob_tolerance`` while its
    consumer ``expected_value`` (and ``risk_budget``) read
    ``probability.probability_sum_tolerance`` — two independent ``CalibratedValue``
    leaves with the same meaning and different ``calibration_status``.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from macro_engine.models.policy_rules import MarketPricingGap
from macro_engine.thesis_layer import schemas
from macro_engine.thesis_layer import signals as signals_module
from macro_engine.thesis_layer.schemas import (
    NO_PRODUCTION_INSTRUMENT,
    ConfirmationSignal,
    ConvergenceClassification,
    MacroThesis,
    ProductionUniverse,
    ScenarioOutcome,
    TradeIdea,
    is_no_production_instrument,
)


def _gap() -> MarketPricingGap:
    return MarketPricingGap(
        model_implied_value=4.0,
        market_implied_value=4.5,
        raw_gap=-0.5,
        dispersion=0.25,
        is_meaningful=True,
        interpretation="market prices fewer cuts than the rule implies",
    )


def _live_idea(**overrides: Any) -> TradeIdea:
    fields: dict[str, Any] = {
        "instrument": "UST cash (2yr, 5yr, 10yr, 30yr)",
        "direction": "long",
        "stop_or_invalidation": "10y UST yield above 4.75%",
    }
    fields.update(overrides)
    return TradeIdea(**fields)


def _thesis(**overrides: Any) -> MacroThesis:
    fields: dict[str, Any] = {
        "thesis_id": "T-0001",
        "regime": {"label": "late-cycle"},
        "growth_view": {"direction": "cooling"},
        "inflation_view": {"direction": "sticky"},
        "policy_view": {"direction": "easing"},
        "market_pricing_gap": _gap(),
        "convergence_classification": ConvergenceClassification.HIGH,
        "trade_idea": _live_idea(),
    }
    fields.update(overrides)
    return MacroThesis(**fields)


def _distribution(total: float) -> list[ScenarioOutcome]:
    """Two branches summing to ``total`` (each individually a valid probability)."""
    return [
        ScenarioOutcome(name="base", probability=total - 0.2, payoff_estimate=1.0),
        ScenarioOutcome(name="tail", probability=0.2, payoff_estimate=-3.0),
    ]


# ---------------------------------------------------------------------------
# the gates that had no test at all
# ---------------------------------------------------------------------------


def test_a_live_trade_idea_must_carry_a_falsifier() -> None:
    """Section 15 Module 1 (LTCM): no stated falsifier, no position."""
    with pytest.raises(ValidationError, match="stop_or_invalidation"):
        _live_idea(stop_or_invalidation="   ")


def test_a_live_trade_idea_must_specify_a_direction() -> None:
    with pytest.raises(ValidationError, match="direction 'long' or 'short'"):
        _live_idea(direction="maybe")


def test_a_no_trade_idea_must_not_carry_a_direction() -> None:
    """A direction on a no-trade would render as "short, 6-12 months" in a UI."""
    with pytest.raises(ValidationError, match=r"must not specify a direction"):
        TradeIdea(instrument=NO_PRODUCTION_INSTRUMENT, direction="short")


def test_a_thesis_with_a_live_trade_must_carry_a_falsifier() -> None:
    """The same gate, enforced on the parent so it cannot be bypassed."""
    idea = _live_idea()
    object.__setattr__(idea, "stop_or_invalidation", "")  # simulate a bypass attempt
    with pytest.raises(ValidationError, match="stop_or_invalidation"):
        _thesis(trade_idea=idea)


def test_conflicted_convergence_blocks_trade_construction() -> None:
    """Section 22.10 / Finding #10 — a hard error, not advice."""
    with pytest.raises(ValidationError, match="CONFLICTED must block trade construction"):
        _thesis(convergence_classification=ConvergenceClassification.CONFLICTED)


def test_a_conflicted_thesis_with_no_trade_is_allowed() -> None:
    """The block is on constructing a POSITION, not on recording the verdict."""
    thesis = _thesis(
        convergence_classification=ConvergenceClassification.CONFLICTED,
        trade_idea=TradeIdea(instrument=NO_PRODUCTION_INSTRUMENT),
    )
    assert thesis.trade_idea.is_trade is False


def test_scenario_probabilities_must_sum_to_one() -> None:
    with pytest.raises(ValidationError, match=r"must sum to 1\.0"):
        _thesis(
            scenario_distribution=_distribution(1.2),
            scenario_distribution_status="calibrated",
        )


def test_a_distribution_within_tolerance_is_accepted() -> None:
    """The gate is a tolerance, not an equality — so it must admit 1.0 + eps."""
    thesis = _thesis(
        scenario_distribution=_distribution(1.005),
        scenario_distribution_status="calibrated",
    )
    assert len(thesis.scenario_distribution) == 2


def test_a_non_empty_distribution_may_not_be_labelled_empty_no_trade() -> None:
    with pytest.raises(ValidationError, match=r"non-empty distribution"):
        _thesis(scenario_distribution=_distribution(1.0))


def test_an_empty_distribution_may_not_claim_a_distribution_status() -> None:
    with pytest.raises(ValidationError, match="scenario_distribution is empty but"):
        _thesis(scenario_distribution_status="calibrated")


def test_scenario_sizing_is_permitted_only_when_calibrated() -> None:
    """The single question a sizer must ask (Section 25)."""
    unavailable = _thesis(
        scenario_distribution=_distribution(1.0),
        scenario_distribution_status="SCENARIO_DISTRIBUTION_UNAVAILABLE",
    )
    assert unavailable.scenario_sizing_permitted is False
    calibrated = _thesis(
        scenario_distribution=_distribution(1.0),
        scenario_distribution_status="calibrated",
    )
    assert calibrated.scenario_sizing_permitted is True
    # The default is the SAFE value, so a thesis that never states its
    # provenance is treated as unsizable rather than silently sized.
    assert _thesis().scenario_sizing_permitted is False


def test_confirmation_signal_direction_is_a_closed_vocabulary() -> None:
    """Section 22.10: free strings made `classify_convergence` unreliable."""
    assert (
        ConfirmationSignal(source_model="m", direction="confirms", detail="d").direction
        == "confirms"
    )
    with pytest.raises(ValidationError, match="direction must be one of"):
        ConfirmationSignal(source_model="m", direction="bullish", detail="d")


# ---------------------------------------------------------------------------
# the production universe matcher
# ---------------------------------------------------------------------------


def test_the_universe_permits_its_own_declared_instruments() -> None:
    """The lists are authoritative, not decorative."""
    universe = ProductionUniverse()
    for instrument in universe.all_instruments:
        assert universe.permits(instrument), instrument


def test_excluded_categories_are_checked_before_keywords() -> None:
    """(F-TSC-001) The ordering, demonstrated with a string that needs it.

    ``"US HY credit index futures"`` carries an equity keyword (``"index
    futures"``) AND an excluded word (``"credit"``). With the exclusion checked
    second it would be admitted as equity; measured, it is refused.
    """
    universe = ProductionUniverse()
    assert universe.category_for("index futures") == "equity"
    assert universe.category_for("US HY credit index futures") is None
    assert universe.permits("US HY credit index futures") is False


def test_a_bare_ticker_is_matched_only_as_a_standalone_token() -> None:
    """``"es"`` must not match inside ``"futures"`` or ``"treasury"``."""
    universe = ProductionUniverse()
    assert universe.category_for("ES futures") == "equity"
    assert universe.category_for("TU futures") == "rates"
    # "ES" is not a token here, so this is an ordinary phrase, not a ticker.
    assert universe.category_for("ESG index") is None


def test_a_concatenated_spot_pair_is_recognised() -> None:
    """``"EURUSD spot"`` tokenises to one token, so ``"eur"`` alone misses it."""
    universe = ProductionUniverse()
    assert universe.category_for("EURUSD spot") == "fx"
    assert universe.category_for("EUR/USD forward") == "fx"


# ---------------------------------------------------------------------------
# (F-TSC-002) the sentinel means the same thing in every class
# ---------------------------------------------------------------------------


def test_the_no_trade_sentinel_is_case_insensitive_everywhere() -> None:
    """(F-TSC-002) ``"none"`` must not mean "no trade" in one class and "live trade"
    in another.

    ``ProductionUniverse`` compared the sentinel case-insensitively (D-058 P17)
    while ``TradeIdea`` compared it exactly, so ``"none"`` was simultaneously
    "permitted as no trade" and "a live trade missing a direction".
    """
    universe = ProductionUniverse()
    for spelling in ("NONE", "none", "None", "  none  "):
        assert universe.permits(spelling) is True, spelling
        assert universe.category_for(spelling) == "none", spelling
        assert is_no_production_instrument(spelling) is True, spelling

        idea = TradeIdea(instrument=spelling, direction="n/a")
        assert idea.is_trade is False, spelling

    # ...and a real instrument is still a trade.
    assert _live_idea().is_trade is True
    assert is_no_production_instrument("UST cash (2yr, 5yr, 10yr, 30yr)") is False


# ---------------------------------------------------------------------------
# (F-TSC-004) the gate and its consumer share ONE tolerance leaf
# ---------------------------------------------------------------------------


def test_the_scenario_sum_gate_reads_the_consumers_tolerance_leaf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(F-TSC-004) The validator must read the leaf ``expected_value`` reads.

    The stub makes the two leaves DISAGREE, so reading the wrong one is visible
    rather than coincidentally identical (both are 0.01 in the shipped config).
    A distribution summing to 1.2 is inside the probability leaf's 0.5 and far
    outside the validation leaf's 0.0, so the two stubs must give opposite
    verdicts — which also proves the stub is discriminating at all.
    """
    monkeypatch.setattr(
        schemas,
        "get_settings",
        lambda: SimpleNamespace(
            probability=SimpleNamespace(probability_sum_tolerance=0.5),
            validation=SimpleNamespace(prob_tolerance=0.0),
        ),
    )
    accepted = _thesis(
        scenario_distribution=_distribution(1.2),
        scenario_distribution_status="calibrated",
    )
    assert len(accepted.scenario_distribution) == 2

    monkeypatch.setattr(
        schemas,
        "get_settings",
        lambda: SimpleNamespace(
            probability=SimpleNamespace(probability_sum_tolerance=0.0),
            validation=SimpleNamespace(prob_tolerance=0.5),
        ),
    )
    with pytest.raises(ValidationError, match=r"must sum to 1\.0"):
        _thesis(
            scenario_distribution=_distribution(1.2),
            scenario_distribution_status="calibrated",
        )


# ---------------------------------------------------------------------------
# (F-TSC-003) the dead class attribute, and (F-TSC-001) the note
# ---------------------------------------------------------------------------


def test_the_dead_g10_class_attribute_is_gone() -> None:
    """(F-TSC-003) ``_G10_CURRENCIES`` was declared and never read.

    Its own comment says the set lives at MODULE scope so ``_keyword_match`` can
    consult it — which is precisely why the class attribute duplicated it and no
    reader ever resolved it.
    """
    assert not hasattr(ProductionUniverse, "_G10_CURRENCIES"), (
        "ProductionUniverse._G10_CURRENCIES is back; it is never read — "
        "_keyword_match consults the module-level _G10_CURRENCY_CODES (F-TSC-003)."
    )
    source = Path(inspect.getfile(schemas)).read_text(encoding="utf-8")
    assert "_G10_CURRENCIES" not in source


def test_the_exclusion_note_gives_a_measured_example() -> None:
    """(F-TSC-001) The note must not cite a string that carries no keyword.

    The replaced sentence claimed ``"US HY credit index"`` would "otherwise match
    the equity category" on the word "index" — measured, bare ``"index"`` is not
    a keyword, so that string was never the case being guarded.
    """
    source = Path(inspect.getfile(schemas)).read_text(encoding="utf-8")
    assert 'contains "index", which would otherwise match the' not in source
    assert "US HY credit index futures" in source, (
        "the note must cite the measured example (a string carrying both an "
        "equity keyword and an excluded word), not one that carries neither."
    )


def test_the_expression_note_does_not_name_a_sentinel_it_cannot_hold() -> None:
    """(F-TSC-005) ``InstrumentExpression`` carries "NONE", not the ANALYTICAL sentinel.

    The class docstring said credit/EM/commodity views "return
    ``ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT`` here", while its own ``instrument``
    field description named ``"NONE"`` — two different sentinels for one field, and
    neither is ever put there (nothing constructs the class; ``TradeIdea.expression``
    is always ``None``). The ANALYTICAL sentinel is a *models*-layer value that
    reaches a thesis through ``TradeIdea.instrument``, which is precisely the
    confusion O-53 records — so a note pointing a reader at the wrong one is the
    first step of that defect.
    """
    source = Path(inspect.getfile(schemas)).read_text(encoding="utf-8")
    assert "return ``ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT`` here" not in source
    assert "ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT" in source, (
        "the correction must NAME the models-layer sentinel so a reader can tell the "
        "two apart, not merely delete the wrong one."
    )
    assert "O-53" in source, (
        "the note must point at O-53, which records where that sentinel actually travels."
    )
    # The measured fact the note records.
    assert _thesis().trade_idea.expression is None


def test_the_confirmation_family_note_names_a_consumer_that_can_see_it() -> None:
    """(F-TSC-006) ``ConfirmationSignal.source_family`` is NOT read by
    ``count_independent_families()``.

    That function is typed ``list[ModelResult]`` and reads each result's OWN
    ``source_family``; a ``ConfirmationSignal`` is never passed to it. The field
    IS populated by ``signals.py`` and published on the thesis, but measured over
    ``src/`` nothing READS it — so the old description pointed a reader at a
    consumer that cannot see the field.
    """
    source = Path(inspect.getfile(schemas)).read_text(encoding="utf-8")
    assert "Module 13 family. Used by count_independent_families()" not in source
    assert "list[ModelResult]" in source, (
        "the correction must state the type that function actually takes."
    )
    # ...and the field is still PRODUCED, so the note is not describing a dead
    # field: signals.py carries it through from the ModelResult.
    producer = Path(inspect.getfile(signals_module)).read_text(encoding="utf-8")
    assert "source_family=_family_of(result)" in producer
