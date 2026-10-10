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
    (F-TSC-007, closed 2026-10-10) The orphaned duplicate leaf was then deleted
    outright, so the two copies can no longer drift apart.
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

    The stub makes the leaf WIDE, so reading the wrong one is visible rather
    than coincidentally identical (both copies read 0.01 in the shipped config).
    A distribution summing to 1.2 is inside the 0.5 stub and far outside the
    real 0.01, so accepting it proves the gate read the stub at all.

    F-TSC-007 (CLOSED): the stub used to carry a SECOND leaf
    (``validation.prob_tolerance``) and set the two to disagree, because the
    defect was reading the wrong one. That duplicate leaf has now been deleted
    from ``settings.yaml`` and ``ValidationSettings``, so the disagreement
    cannot be constructed — and, more to the point, it cannot recur: there is
    only one leaf left to read. What this test still pins is that the gate
    consults *config* rather than a literal.
    """
    monkeypatch.setattr(
        schemas,
        "get_settings",
        lambda: SimpleNamespace(
            probability=SimpleNamespace(probability_sum_tolerance=0.5),
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


# ---------------------------------------------------------------------------
# Section 22.3 — the GB instrument plan (Workstream 3 of the multi-country
# increment). A country's instrument set must be its OWN, not the US set with a
# different label. These tests assert the plan is genuinely distinct in BOTH
# directions — the UK admits UK instruments the US refuses, and the US admits US
# instruments the UK refuses — because a one-directional test would pass on a
# union (which is the relabel the section rejects).
# ---------------------------------------------------------------------------


def test_the_gb_universe_lists_uk_instruments_not_us_ones() -> None:
    """(§22.3) ``country='gb'`` names gilts / short sterling / SONIA / FTSE 100.

    The literal lists are asserted, not just "differs from us": a plan that
    differed by omission (empty) would pass a naive inequality and fail the
    point, which is that the UK has its OWN tradable set.
    """
    gb = ProductionUniverse(country="gb")
    joined = " ".join(gb.all_instruments).lower()
    for token in ("gilt", "sterling", "sonia", "ftse"):
        assert token in joined, f"the gb plan omits {token!r}: {gb.all_instruments}"
    # ...and no US instrument leaks into the UK plan.
    for token in ("ust", "sofr", "fed funds", "tips", "s&p", "nasdaq"):
        assert token not in joined, f"the gb plan relabels a US instrument: {token!r}"


def test_the_gb_and_us_plans_admit_their_own_and_refuse_each_others() -> None:
    """(§22.3) both directions: US refuses gilt, GB refuses UST.

    This is the anti-relabel test. A universe that admitted BOTH countries'
    instruments would let a gb thesis name a UST (serving US data to a UK
    trade), and vice versa — the failure the section names explicitly.

    The cases below are the **disjoint** ones only, measured rather than
    assumed. The shared *shape* words (``swap``, ``ois``, and the generic
    ``index futures``/``equity index``) are deliberately common to the plans, so
    a string built on them is admitted by both — measured:
    ``us.category_for("SONIA OIS swap") == "rates"``. Asserting the US refused
    SONIA would be false and would fail. The disjoint vocabulary is where the
    anti-relabel claim actually lives: ``ust``/``sofr``/``fed funds``/``tips``
    are US-only, ``gilt``/``sonia``/``short sterling`` are UK-only.
    """
    us = ProductionUniverse()
    gb = ProductionUniverse(country="gb")

    # Each admits its own, on its DISJOINT vocabulary.
    assert us.category_for("UST futures") == "rates"
    assert us.category_for("SOFR futures") == "rates"
    assert gb.category_for("10yr gilt futures") == "rates"
    assert gb.category_for("SONIA swap") == "rates"
    assert gb.category_for("short sterling futures") == "rates"
    assert gb.category_for("FTSE 100 index futures") == "equity"

    # Each refuses the other's disjoint vocabulary.
    assert gb.category_for("UST futures") is None
    assert gb.category_for("SOFR futures") is None
    assert gb.category_for("Fed funds futures") is None
    assert us.category_for("10yr gilt futures") is None
    assert us.category_for("short sterling futures") is None


def test_the_gb_universe_rejects_a_us_only_rates_instrument() -> None:
    """(§22.3) the UK plan's RATES vocabulary is the UK's, not a superset.

    RATES is the sharp case, and the reason is structural rather than
    stylistic: a UST and a gilt are different instruments backed by different
    sovereigns, so admitting a UST into a gb thesis would serve US data to a UK
    trade. ``ust``/``sofr``/``fed funds``/``tips`` are therefore deliberately
    absent from ``_GB_RATES_KEYWORDS`` and a gb universe must refuse them.

    EQUITY is deliberately NOT asserted the same way, and the asymmetry is
    MEASURED rather than assumed: ``index futures`` and ``equity index`` are
    shared generic shape admissions, so BOTH plans admit any *named* index
    (measured: ``gb.category_for("S&P 500 index futures") == "equity"`` and
    ``us.category_for("FTSE 100 index futures") == "equity"``). That is the
    pre-existing, uniform behaviour of the matcher — it admits an equity SHAPE
    and leaves the country to the plan's named list (``gb.equity == ["FTSE 100
    index futures"]``). An earlier draft of this test asserted the UK refused
    the S&P, which was simply false: the refusal lives in the named list and the
    country-specific keyword vocabulary, not in the generic phrase.
    """
    gb = ProductionUniverse(country="gb")
    assert gb.category_for("UST futures") is None
    assert gb.category_for("SOFR futures") is None
    assert gb.category_for("Fed funds futures") is None
    assert gb.category_for("TIPS breakevens") is None
    # ...and the UK's own rates vocabulary IS admitted.
    assert gb.category_for("10yr gilt futures") == "rates"
    assert gb.category_for("SONIA OIS swap") == "rates"


def test_an_unimplemented_country_is_rejected_not_defaulted_to_us() -> None:
    """(§22.3) a country without a plan must raise, not silently borrow the US one.

    The dangerous alternative — falling back to the US plan — produces an
    internally consistent universe that serves US instruments to another
    country's thesis, invisibly. Raising makes "no instrument set" a loud fact.

    ``de``/``jp`` were used as the examples here until 2026-10-10; both now HAVE
    plans (§22.3, D-149) so they are no longer evidence of anything. ``fr`` is
    the genuinely-unimplemented code — see the companion test below, which pins
    the other half of the boundary (an implemented country must NOT raise).
    """
    for code in ("fr", ""):
        with pytest.raises(ValidationError):
            ProductionUniverse(country=code)


def test_de_and_jp_have_their_own_plans_not_a_borrowed_one() -> None:
    """(§22.3, D-149) the two newest countries resolve to their OWN instruments.

    Complements the refusal test above: that one pins "an unimplemented code
    raises", this one pins "an implemented code does not, and does not silently
    get the US plan". Together they are the boundary — either half alone passes
    under a mutant that hardcodes the other.
    """
    de = ProductionUniverse(country="de")
    jp = ProductionUniverse(country="jp")
    us = ProductionUniverse(country="us")

    assert de.country == "de"
    assert jp.country == "jp"

    # Each is distinct from the US plan in rates AND equity (the two categories
    # §22.3 requires to differ; fx is shared by design).
    assert de.rates != us.rates
    assert jp.rates != us.rates
    assert de.equity != us.equity
    assert jp.equity != us.equity
    assert de.rates != jp.rates
    assert de.equity != jp.equity

    # ...and each names its own market's vocabulary.
    assert any("Bund" in i for i in de.rates)
    assert any("JGB" in i for i in jp.rates)
    assert "Nikkei 225 index futures" in jp.equity


def test_the_us_plan_is_unchanged_by_the_country_field() -> None:
    """(backwards compatibility) the default country still yields the US plan.

    The country field was added defaulting to "us" precisely so that every
    existing ``ProductionUniverse()`` construction — 6 in ``src/``, 5 in tests —
    keeps its exact prior behaviour.
    """
    us = ProductionUniverse()
    assert us.country == "us"
    assert us.rates[0] == "UST cash (2yr, 5yr, 10yr, 30yr)"
    assert us.equity == ["Broad equity indices (ES, NQ, RTY)"]
    # The US plan's rates/equity are identical to a default-constructed universe.
    assert ProductionUniverse(country="us").all_instruments == us.all_instruments


def test_the_two_plans_share_only_fx() -> None:
    """(§22.3) ``fx`` is shared by design; ``rates`` and ``equity`` are not.

    The asymmetry is the section's point: a category that genuinely differs
    must not be faked by relabelling. G10 FX is one market, so its instruments
    are the same tradeable objects either way.
    """
    us = ProductionUniverse()
    gb = ProductionUniverse(country="gb")
    assert us.fx == gb.fx, "G10 FX is one market and must be shared"
    assert us.rates != gb.rates, "the rates sets differ (this is the whole section)"
    assert us.equity != gb.equity, "the equity sets differ"


def test_every_country_plan_is_internally_consistent() -> None:
    """(§22.3) each plan permits every instrument it declares.

    The registry-driven companion to ``..._permits_its_own_declared_instruments``:
    the US universe happened to pass that test while the gb list did not exist.
    Iterating the PLANS (not the one default) means a future country cannot be
    added with lists its own matcher would reject.
    """
    for country in ("us", "gb"):
        universe = ProductionUniverse(country=country)
        assert universe.all_instruments, f"{country} declared no instruments"
        for instrument in universe.all_instruments:
            assert universe.permits(instrument), f"{country} rejects its own {instrument!r}"


def test_the_bare_ticker_table_is_country_aware() -> None:
    """(§22.3, mutation-killed) a UK ticker is not a US ticker.

    The bare-ticker roots are market-specific and must be selected by country:
    ``GL`` is the generic gilt-futures root and ``TU`` the US 2yr-note root.
    A gb universe that read the US table would admit ``"TU futures"`` into a UK
    thesis; a us universe that read the UK table would admit ``"GL futures"``.

    Asserted through the public matcher with a shape that carries NO generic
    keyword (so the ticker is the only admissible path): ``"GL futures"`` and
    ``"TU futures"`` reach the country plan, not the shared shape vocabulary.
    """
    us = ProductionUniverse()
    gb = ProductionUniverse(country="gb")
    assert gb.category_for("GL futures") == "rates"
    assert us.category_for("GL futures") is None
    assert us.category_for("TU futures") == "rates"
    assert gb.category_for("TU futures") is None


def test_the_equity_keyword_vocabulary_is_country_aware() -> None:
    """(§22.3, mutation-killed) the UK equity vocabulary is not the US one.

    Asserted on the selected keyword SETS, because ``category_for`` cannot
    distinguish them: the shared generic phrases (``index futures``, ``equity
    index``) admit any named index in both plans, so a string test is masked.
    The discriminating claim is structural — the gb plan must read the UK set,
    and the two sets must not be identical. A mutant that made ``_equity_keywords``
    return the US set unconditionally would leave every string test green while
    silently dropping ``ftse`` from the UK plan's own vocabulary.
    """
    us = ProductionUniverse()
    gb = ProductionUniverse(country="gb")
    assert us._equity_keywords is us._EQUITY_KEYWORDS
    assert gb._equity_keywords is gb._GB_EQUITY_KEYWORDS
    assert set(us._equity_keywords) != set(gb._equity_keywords)
    # The country-specific terms are where the claim lives.
    assert "ftse" in gb._equity_keywords
    assert "ftse" not in us._equity_keywords
    assert "nasdaq" in us._equity_keywords
    assert "nasdaq" not in gb._equity_keywords


# ---------------------------------------------------------------------------
# Section 22.3 — the euro-area universe (country "eu")
#
# The third country, and the one whose instrument structure is genuinely unlike
# the other two: the euro area has no single sovereign, so its defining rates
# feature is the SOVEREIGN SPREAD (BTP-Bund, OAT-Bund) that neither the US nor
# the UK has. The tests below pin, in both directions, that a eu universe admits
# its own vocabulary and refuses the US's and the UK's.
# ---------------------------------------------------------------------------


def test_the_eu_universe_lists_euro_instruments_not_us_or_uk_ones() -> None:
    """(§22.3) ``country='eu'`` names Bunds / BTPs / ESTR / Euro Stoxx.

    The literal lists are asserted, not just "differs from us": a plan that
    differed by omission (empty) would pass a naive inequality and fail the
    point, which is that the euro area has its OWN tradable set.

    The euro-area-specific token is ``btp``/``bund``/``estr`` — and the SOVEREIGN
    SPREAD vocabulary (``btp-bund``) is the euro area's defining feature, absent
    from both the US and the UK because neither has an intra-area credit
    structure.
    """
    eu = ProductionUniverse(country="eu")
    joined = " ".join(eu.all_instruments).lower()
    for token in ("bund", "btp", "oat", "estr", "stoxx", "spread"):
        assert token in joined, f"the eu plan omits {token!r}: {eu.all_instruments}"
    # ...and no US or UK instrument leaks into the euro-area plan.
    for token in ("ust", "sofr", "fed funds", "tips", "s&p", "nasdaq", "gilt", "sonia"):
        assert token not in joined, f"the eu plan relabels another market's instrument: {token!r}"


def test_the_eu_and_us_and_gb_plans_admit_their_own_and_refuse_each_others() -> None:
    """(§22.3) three-way: eu refuses UST/gilt, us refuses ESTR/BTP, gb refuses ESTR/BTP.

    This is the anti-relabel test extended to the third country. A universe that
    admitted another market's instruments would let a eu thesis name a UST or a
    gilt (serving US or UK data to a euro trade), and vice versa.

    The cases are the **disjoint** ones only, measured rather than assumed. ESTR
    is the sharpest: it is the euro area's policy rate and appears in NO other
    plan, so a eu universe must admit it and the us/gb universes must refuse it.
    The shared shape words (``swap``, ``ois``, ``index futures``) are deliberately
    common, so a string built only on them is admitted by all three — the
    discriminating vocabulary is where the anti-relabel claim lives.
    """
    us = ProductionUniverse()
    gb = ProductionUniverse(country="gb")
    eu = ProductionUniverse(country="eu")

    # Each admits its own, on its DISJOINT vocabulary.
    assert eu.category_for("ESTR futures") == "rates"
    assert eu.category_for("BTP-Bund spread") == "rates"
    assert eu.category_for("Euro Stoxx 50 index futures") == "equity"
    assert us.category_for("UST futures") == "rates"
    assert gb.category_for("10yr gilt futures") == "rates"

    # Each refuses the other two markets' disjoint vocabulary.
    assert eu.category_for("UST futures") is None
    assert eu.category_for("SOFR futures") is None
    assert eu.category_for("10yr gilt futures") is None
    assert eu.category_for("short sterling futures") is None
    assert us.category_for("ESTR futures") is None
    assert gb.category_for("ESTR futures") is None


def test_the_eu_bare_ticker_table_is_country_aware() -> None:
    """(§22.3, mutation-killed) a Eurex root is not a US or UK ticker.

    The bare-ticker roots are market-specific and must be selected by country:
    ``FGBL`` is the Eurex Euro-Bund root and ``TU`` the US 2yr-note root. A eu
    universe that read the US table would admit ``"ES futures"``/``"TU futures"``
    into a euro thesis (the exact §22.3 relabel); a us universe that read the
    eu table would admit ``"FGBL futures"``.

    Asserted through the public matcher with a shape carrying NO generic keyword
    (so the ticker is the only admissible path).
    """
    us = ProductionUniverse()
    gb = ProductionUniverse(country="gb")
    eu = ProductionUniverse(country="eu")
    assert eu.category_for("FGBL futures") == "rates"
    assert eu.category_for("FBTP futures") == "rates"
    assert eu.category_for("FESX futures") == "equity"
    assert us.category_for("FGBL futures") is None
    assert gb.category_for("FGBL futures") is None
    assert eu.category_for("ES futures") is None
    assert eu.category_for("TU futures") is None


def test_the_eu_plan_is_internally_consistent() -> None:
    """(§22.3) the eu plan permits every instrument it declares.

    The registry-driven companion: iterating the PLANS means a future country
    cannot be added with lists its own matcher would reject.
    """
    universe = ProductionUniverse(country="eu")
    assert universe.all_instruments, "eu declared no instruments"
    for instrument in universe.all_instruments:
        assert universe.permits(instrument), f"eu rejects its own {instrument!r}"


def test_the_three_plans_share_only_fx() -> None:
    """(§22.3) ``fx`` is shared by design; ``rates`` and ``equity`` are not.

    The asymmetry is the section's point: a category that genuinely differs must
    not be faked by relabelling. G10 FX is one market, so its instruments are the
    same tradeable objects for every country; rates and equity are not.
    """
    us = ProductionUniverse()
    gb = ProductionUniverse(country="gb")
    eu = ProductionUniverse(country="eu")
    assert us.fx == gb.fx == eu.fx, "G10 FX is one market and must be shared"
    assert us.rates != eu.rates, "the eu rates set differs from the US one"
    assert gb.rates != eu.rates, "the eu rates set differs from the UK one"
    assert us.equity != eu.equity, "the eu equity set differs"


def test_every_country_plan_is_internally_consistent_across_three_countries() -> None:
    """(§22.3) each of the THREE plans permits every instrument it declares."""
    for country in ("us", "gb", "eu"):
        universe = ProductionUniverse(country=country)
        assert universe.all_instruments, f"{country} declared no instruments"
        for instrument in universe.all_instruments:
            assert universe.permits(instrument), f"{country} rejects its own {instrument!r}"
