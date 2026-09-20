"""Unit tests for ``translate_thesis_to_position`` — Section 9.3 (Phase 4).

The function's whole job is to **refuse well**: nine of its outputs are decided
by gates rather than by arithmetic, and five of them are refusals. The tests are
organised the same way, because the defects this file pins are all *wrong
reasons* rather than wrong numbers — a class the project keeps finding and one
that no numeric assertion can catch.

The defects pinned here
-----------------------

1. **A risk budget is not convertible into a notional, and the first
   implementation assumed it was.** §9.3 supplies no covariance, so
   ``RC_i = w_i(Sigma w)_i / sigma_p^2`` cannot be evaluated; multiplying the
   capital fraction by the risk share returned **0.018** where the answer was
   0.12 — a 6.7x understatement that is invisible because 0.018 is a plausible
   position size. ``test_the_risk_budget_does_not_scale_the_notional`` pins the
   corrected behaviour and
   ``test_no_notional_relation_holds_between_weight_and_risk_share`` records the
   *measurement* that closes off the tempting repair.

2. **``is_trade`` is not the universe check, and the gap produced a right
   refusal with a wrong reason.** ``"HY credit spread"`` is not ``"NONE"``, so
   the thesis calls itself a trade; on the first draft that input was refused as
   ``refused_scenarios_uncalibrated``, telling a reader to calibrate their
   probabilities when the truth is that the desk cannot execute the instrument.
   ``test_an_out_of_universe_instrument_is_refused_as_a_trade`` pins it.

3. **``"NONE"`` is a legal ``TradeIdea.instrument`` value, and the two sentinels
   are both strings** (**O-53**). A comparison against a re-typed literal is the
   one place the false-executability risk O-53 names becomes real, so the
   sentinels are compared against their *constants* and
   ``test_the_two_sentinels_are_refused_for_different_reasons`` proves the
   distinction survives.

4. **A refusal with a size on it is a proposal wearing a refusal's label.** The
   schema enforces zero-size-plus-no-binding-constraint on every ``refused_*``
   outcome rather than trusting each construction site.

5. **The sign-off gate must survive every path**, including the refusals. §9.3's
   gate is the difference between a reasoning layer and a signal generator
   (Section 1.1), so it is asserted on *all* outcomes rather than on the happy
   one — a property that a single-path test would leave open.

6. **A budget line for a different instrument is a caller error, not a
   refusal.** Sizing one instrument against another's allocation publishes a
   proposal claiming a portfolio check it never performed, with nothing on the
   output to show the mismatch.
"""

from __future__ import annotations

import random
from typing import Any, get_args

import pytest
from pydantic import ValidationError

from macro_engine.config import get_settings
from macro_engine.models.contracts import ModelResult, utc_now
from macro_engine.models.instrument_selection import (
    ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT,
)
from macro_engine.models.probability import ScenarioOutcome
from macro_engine.models.risk import marginal_risk_contributions
from macro_engine.portfolio.risk_budget import (
    SIGN_OFF_REQUIRED,
    KellyInputs,
    PositionBinding,
    PositionTranslationOutcome,
    ProposedPosition,
    RiskBudgetTarget,
    RiskLimits,
    ThesisPositionInputs,
    apply_fractional_kelly,
    translate_thesis_to_position,
)
from macro_engine.thesis_layer.schemas import (
    NO_PRODUCTION_INSTRUMENT,
    ConvergenceClassification,
    MacroThesis,
    MarketPricingGap,
    ProductionUniverse,
    ThesisStatus,
    TradeIdea,
)
from tests.helpers import as_bool, as_float, as_str

#: A real §22.12 instrument. **Not** an ETF ticker: measured, ``ProductionUniverse``
#: rejects ``"SPY"``/``"TLT"``/``"GLD"`` because §22.12 permits index roots and
#: futures, not ETF shares. Using a ticker here would test the refusal path by
#: accident in every test that follows.
_IN_UNIVERSE = "TY futures"

#: A real out-of-universe instrument — §22.12 excludes credit.
_OUT_OF_UNIVERSE = "US HY credit spread"


def _thesis(
    *,
    instrument: str = _IN_UNIVERSE,
    direction: str = "long",
    scenarios: list[ScenarioOutcome] | None = None,
    status: str = "SCENARIO_DISTRIBUTION_UNAVAILABLE",
    sizing_logic: str = "Phase 1: human-determined",
    trade_with_no_scenarios: bool = False,
) -> MacroThesis:
    """A thesis shaped exactly as ``build_us_macro_thesis`` shapes one.

    ``status`` defaults to the **live** value
    (``SCENARIO_DISTRIBUTION_UNAVAILABLE``), because that is what the builder
    actually produces today — a fixture defaulting to ``"calibrated"`` would
    test a state the system cannot currently reach and would hide gate 2.

    ``trade_with_no_scenarios`` builds the one combination that reaches gate 3's
    empty branch: a thesis that **is** a trade *and* carries no distribution.
    That combination is schema-legal (``MacroThesis`` validates the status
    against the distribution, not the instrument against either) but not
    builder-producible, so it needs to be asked for explicitly rather than
    implied by ``status="empty_no_trade"`` — which would be refused a gate
    earlier. See ``_every_outcome``.
    """
    # A no-trade thesis may not carry a direction (TradeIdea's own validator),
    # so the sentinel forces "n/a" rather than making every caller remember.
    if instrument == NO_PRODUCTION_INSTRUMENT:
        direction = "n/a"

    if status == "empty_no_trade":
        resolved: list[ScenarioOutcome] = []
    elif scenarios is None:
        resolved = []
        if not trade_with_no_scenarios:
            resolved = [
                ScenarioOutcome(name="base", probability=0.5, payoff_estimate=0.10),
                ScenarioOutcome(name="bull", probability=0.3, payoff_estimate=0.20),
                ScenarioOutcome(name="bear", probability=0.2, payoff_estimate=-0.15),
            ]
    else:
        resolved = scenarios

    return MacroThesis(
        thesis_id="us-2026-09-20-deadbeef",
        country="us",
        created_at=utc_now(),
        as_of=utc_now(),
        regime={"state": None},
        growth_view={"output_gap": None},
        inflation_view={"breadth_score": None},
        policy_view={},
        market_pricing_gap=MarketPricingGap(
            model_implied_value=4.5,
            market_implied_value=4.0,
            raw_gap=0.5,
            unit="%",
            dispersion=0.1,
            is_meaningful=True,
            interpretation="model 50bp above market",
        ),
        confirmation_signals=[],
        convergence_classification=ConvergenceClassification.HIGH,
        trade_idea=TradeIdea(
            instrument=instrument,
            direction=direction,
            timeframe="6-12 months",
            sizing_logic=sizing_logic,
            stop_or_invalidation="growth read turns negative for two consecutive prints",
        ),
        scenario_distribution=resolved,
        scenario_distribution_status=status,  # type: ignore[arg-type]
        status=ThesisStatus.DRAFT,
        warnings=[],
    )


def _live() -> MacroThesis:
    """A calibrated, in-universe, positive-edge thesis — the one that sizes."""
    return _thesis(instrument=_IN_UNIVERSE, status="calibrated")


def _translate(
    thesis: MacroThesis, *, budget: float | None = None, budget_instrument: str | None = None
) -> ModelResult:
    target = (
        None
        if budget is None
        else RiskBudgetTarget(
            instrument=budget_instrument or thesis.trade_idea.instrument,
            target_risk_contribution_pct=budget,
        )
    )
    return translate_thesis_to_position(
        ThesisPositionInputs(thesis=thesis, risk_budget_target=target)
    )


# ---------------------------------------------------------------------------
# Gate 1 — is there anything to size?
# ---------------------------------------------------------------------------


def test_a_no_trade_thesis_is_refused_and_carries_no_size() -> None:
    """Section 16.3: NO TRADE is a first-class outcome, not a size of zero.

    The distinction the test defends is between "no position" (a decision) and
    "a position of size zero" (a number). A function that published a size for
    a stand-down would manufacture the exposure Q6/Q7/Q8 refused.
    """
    result = _translate(_thesis(instrument=NO_PRODUCTION_INSTRUMENT, status="empty_no_trade"))

    assert as_str(result, key="outcome") == "refused_not_a_trade"
    assert as_float(result, key="fraction_of_capital") == 0.0
    assert as_float(result, key="notional_fraction_after_constraints") == 0.0
    assert as_str(result, key="binding_constraint") == "none"
    assert "NO-TRADE" in result.interpretation


def test_an_analytical_only_instrument_is_refused_as_a_trade() -> None:
    """Section 22.12: the sentinel is a *permit* for "no instrument", not for
    "an instrument that happens to be uncodable".

    **The two sentinels are different strings, and the analytical one is the
    dangerous one** — this test originally asserted they were *equal*, citing
    O-53, and the assertion failed on a first run because the premise was a
    documentation error rather than a code fact (measured against every commit:
    see **O-93**). The measured pair is

    ``NO_PRODUCTION_INSTRUMENT == "NONE"`` and
    ``ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT ==
    "ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT"``.

    ``ProductionUniverse.permits`` returns **False** for the analytical
    sentinel (it is not a rate, an FX pair or an index root) and
    ``TradeIdea.is_trade`` returns **True** for it (it is not ``"NONE"``), so
    this input reaches gate 1 with *both* of its checks already failing — and
    which one fires is what decides the sentence the reader sees.

    **The mutation sweep found this test was one assertion short.**
    ``M1.3`` (delete the explicit sentinel comparison, leaving
    ``if not idea.is_trade``) SURVIVED the first run, because
    ``ProductionUniverse.permits`` is *also* ``False`` for this string and both
    checks lead to the same outcome. The two are distinguished only by their
    **reason**: the sentinel branch says "this view has no production
    expression", while the universe branch says "this instrument is not in
    rates, FX or equity indices". Those are different repairs, so the reason is
    asserted here — by name, on the sentinel path, where the mutation lands.
    """
    assert ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT != NO_PRODUCTION_INSTRUMENT, (
        "the premise of this test: the two sentinels are DIFFERENT strings, and "
        "the universe matcher plus `is_trade` disagree about the analytical one"
    )
    assert not ProductionUniverse().permits(ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT), (
        "the premise of this test: the universe does NOT permit the sentinel "
        "string, so a reader cannot tell the two checks apart from the outcome"
    )

    result = _translate(_thesis(instrument=ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT))

    assert as_str(result, key="outcome") == "refused_not_a_trade"
    assert as_float(result, key="fraction_of_capital") == 0.0
    # The SENTINEL's reason, not the universe's. Asserted on the exact phrase
    # the sentinel branch publishes, because that phrase is the only thing
    # M1.3 changes -- and unlike the universe branch's text it contains no
    # occurrence of the word "universe".
    assert "outside the production execution universe" in result.interpretation, (
        "the analytical-only sentinel must be refused by gate 1's explicit "
        "comparison, not by the universe matcher -- both reach this outcome, so "
        "only the reason can tell a reader which check fired"
    )


def test_an_out_of_universe_instrument_is_refused_as_a_trade_not_as_a_data_gap() -> None:
    """The right outcome with the wrong reason is still a defect.

    ``_OUT_OF_UNIVERSE`` is not the no-trade sentinel, so ``TradeIdea.is_trade``
    is True and gate 1's *first* check passes it. On the first draft this input
    fell through to gate 2 and published ``refused_scenarios_uncalibrated`` —
    which reads as "your probabilities need calibrating" when the desk in fact
    cannot execute the instrument at all. The reason is asserted, not just the
    outcome, because the outcome alone was already right.
    """
    result = _translate(_thesis(instrument=_OUT_OF_UNIVERSE))

    assert as_str(result, key="outcome") == "refused_not_a_trade"
    assert "universe" in result.interpretation
    assert "calibrat" not in result.interpretation.lower(), (
        "an out-of-universe instrument must not be refused on probability "
        "calibration grounds -- the reason drives the repair"
    )


def test_an_etf_ticker_is_out_of_universe_by_design() -> None:
    """§22.12 permits index roots and futures, **not** ETF shares.

    Measured, not assumed: ``"SPY"``, ``"TLT"`` and ``"GLD"`` all fail
    ``ProductionUniverse.permits``. This test exists because it is the fact that
    makes the *rest* of this file's fixtures honest — a test suite built on ETF
    tickers would exercise the refusal path everywhere and never reach Kelly.
    """
    universe = ProductionUniverse()
    for ticker in ("SPY", "TLT", "IEF", "GLD"):
        assert not universe.permits(ticker), f"{ticker} unexpectedly permitted"
    for permitted in ("ES", "NQ", "RTY", "TY futures", "SOFR futures", "EURUSD spot"):
        assert universe.permits(permitted), f"{permitted} unexpectedly refused"


def test_the_two_sentinels_are_refused_with_different_reasons() -> None:
    """**O-53 / O-93**: both sentinels are plain strings, they are **different**
    strings, and only one of them is a value ``TradeIdea`` treats as a no-trade.

    A consumer cannot tell which sentinel it holds from the *type* (both are
    ``str``), and the two mean different things — "this thesis stood itself
    down" versus "this view has no production expression". Both arrive here as
    ``refused_not_a_trade``, which is correct, so the discriminating assertion
    has to be the **interpretation** and the **published instrument** rather
    than the outcome.

    ``TradeIdea.is_trade`` is ``instrument != NO_PRODUCTION_INSTRUMENT``, so
    the analytical sentinel does *not* read as a no-trade to the schema — it
    reads as a live trade in something §22.12 forbids. This test is the reason
    the two are worth separating, and ``test_an_analytical_only_instrument_
    is_refused_as_a_trade`` is the assertion that this function closes that
    gap.
    """
    no_trade = _translate(_thesis(instrument=NO_PRODUCTION_INSTRUMENT, status="empty_no_trade"))
    analytical = _translate(_thesis(instrument=ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT))

    assert as_str(no_trade, key="outcome") == as_str(analytical, key="outcome")
    assert no_trade.interpretation != analytical.interpretation
    assert "NO-TRADE" in no_trade.interpretation
    assert "universe" in analytical.interpretation
    # The published instrument is passed through unchanged (Section 22.12), so
    # the sentinel survives to the caller rather than being blanked.
    assert as_str(no_trade, key="instrument") == NO_PRODUCTION_INSTRUMENT
    assert as_str(analytical, key="instrument") == ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT
    # The schema-level consequence, asserted rather than described -- this is the
    # half of O-53 that the documentation got backwards.
    assert (
        TradeIdea(
            instrument=NO_PRODUCTION_INSTRUMENT,
            direction="n/a",
            timeframe="n/a",
            stop_or_invalidation="n/a",
        ).is_trade
        is False
    )
    assert (
        TradeIdea(
            instrument=ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT,
            direction="long",
            timeframe="6-12 months",
            stop_or_invalidation="a stated falsifier",
        ).is_trade
        is True
    ), (
        "the analytical sentinel is NOT a no-trade to the schema -- which is "
        "why this function must refuse it explicitly rather than pass it through"
    )


# ---------------------------------------------------------------------------
# Gate 2/3 — Section 25 and the distribution
# ---------------------------------------------------------------------------


def test_the_live_thesis_is_refused_because_its_scenarios_are_uncalibrated() -> None:
    """Section 25's prohibition, on the state the system is **actually** in.

    Measured on every live thesis today: ``scenario_sizing_permitted`` is False,
    so this is the branch a real run takes. It is the most important test in the
    file for that reason — the sizing paths below it are reachable only after a
    calibration this project has not performed.
    """
    thesis = _thesis(status="SCENARIO_DISTRIBUTION_UNAVAILABLE")
    assert thesis.scenario_sizing_permitted is False
    assert len(thesis.scenario_distribution) > 0, (
        "the distribution is non-empty -- this is the UNCALIBRATED branch, not "
        "the empty one, which is what makes the two worth separating"
    )

    result = _translate(thesis)

    assert as_str(result, key="outcome") == "refused_scenarios_uncalibrated"
    assert as_float(result, key="fraction_of_capital") == 0.0
    assert as_bool(result, key="scenario_sizing_permitted") is False
    assert "Section 25" in result.interpretation


def test_an_empty_distribution_is_unreachable_so_its_outcome_was_removed() -> None:
    """**The second dead gate, and the one that took two passes to see.**

    The first draft's gate 3 duplicated ``MacroThesis``'s mass check and could
    never fire. The repair for that removed the *mass* half — and left the
    *emptiness* half, which was dead for a **different** reason, so it needed
    its own measurement rather than inheriting the previous one's conclusion.

    ``_enforce_scenario_status_matches_distribution`` is **two-directional**:

    * non-empty + ``empty_no_trade`` → raises
    * empty + (``calibrated`` | ``unavailable``) → raises

    So a ``MacroThesis`` reaching gate 2 is either non-empty, or empty *and*
    ``empty_no_trade``. Gate 2 refuses everything that is not ``calibrated``,
    and ``scenario_sizing_permitted`` is ``status == "calibrated"`` — a
    **status-only** predicate that never inspects the distribution. The empty
    case is therefore eliminated before Kelly is reached, and
    ``refused_no_scenarios`` was a ``Literal`` member no input could produce.

    This test is the enumeration, at a reduced scale so the suite stays fast:
    it constructs every reachable combination and asserts the outcome is never
    the removed one. A "no input reaches this line" claim is exactly the kind
    that has been wrong four times in this project (D-045/D-046/D-048, O-53),
    so it is measured here rather than argued in a comment.
    """
    assert "refused_no_scenarios" not in set(get_args(PositionTranslationOutcome)), (
        "the outcome was reinstated. If a MacroThesis can now be constructed "
        "with an empty calibrated distribution, D-071's reasoning is void and "
        "the gate must come back WITH a test that reaches it."
    )

    # The empty distribution is schema-illegal on every status that gate 2
    # would let through...
    for status in ("calibrated", "SCENARIO_DISTRIBUTION_UNAVAILABLE"):
        with pytest.raises(ValidationError, match="scenario_distribution is empty"):
            _thesis(status=status, trade_with_no_scenarios=True)

    # ...and the only status that PERMITS an empty distribution is refused by
    # gate 2, before any emptiness check could run.
    empty_stand_down = _translate(_thesis(status="empty_no_trade"))
    assert as_str(empty_stand_down, key="outcome") == "refused_scenarios_uncalibrated", (
        "the empty distribution's refusal must come from the CALIBRATION gate "
        "and not from an emptiness check -- that is what makes the emptiness "
        "check unreachable rather than merely redundant"
    )


def test_a_malformed_distribution_cannot_reach_this_function() -> None:
    """Gate 3's mass check was **dead code**, and this is the measurement.

    The first draft of gate 3 refused a distribution whose probabilities did not
    sum to 1.0, reading ``settings.probability.probability_sum_tolerance``.
    ``MacroThesis._enforce_scenario_probabilities`` already refuses exactly that,
    at construction, reading ``settings.validation.prob_tolerance`` — a
    **different leaf in a different config block**. So the check could never
    fire, and the duplicate leaf would have drifted silently.

    The test asserts the invariant is enforced one frame earlier, which is what
    makes the removal correct rather than a lost safety net.
    """
    with pytest.raises(ValidationError, match=r"must sum to 1\.0"):
        _thesis(
            status="calibrated",
            scenarios=[
                ScenarioOutcome(name="base", probability=0.5, payoff_estimate=0.10),
                ScenarioOutcome(name="bear", probability=0.2, payoff_estimate=-0.15),
            ],
        )

    # And the two leaves that encode this one rule are today equal, so the
    # duplicate was invisible -- exactly the condition under which a duplicated
    # rule drifts unnoticed.
    settings = get_settings()
    assert settings.validation.prob_tolerance == settings.probability.probability_sum_tolerance, (
        "the two tolerance leaves have diverged. One of the two enforcement "
        "points now disagrees with the other, and only one of them can fire."
    )


def test_the_uncalibrated_refusal_says_the_human_path_still_exists() -> None:
    """A refusal must not read as "this thesis is unusable".

    §9.3's whole point is that ``sizing_logic`` is prose a human acts on. The
    refusal declines to *derive* a number; it does not retract the thesis, and
    the interpretation has to say so or the obligation Section 25 discharges
    becomes an obligation to do nothing.
    """
    result = _translate(_thesis(status="SCENARIO_DISTRIBUTION_UNAVAILABLE"))
    assert "human may size it" in result.interpretation


# ---------------------------------------------------------------------------
# Gate 4 — Kelly
# ---------------------------------------------------------------------------


def test_a_calibrated_thesis_is_sized_by_kelly_and_matches_the_primitive() -> None:
    """The composed pipeline must agree with the primitive it calls.

    Asserting equality against ``apply_fractional_kelly`` rather than against a
    literal is deliberate: a literal pins today's divisor and cap as constants,
    so a config change would break the test for the wrong reason, while the
    equality pins the *contract* (this function adds gates, not arithmetic).
    """
    thesis = _live()
    limits = RiskLimits.from_settings()
    kelly = apply_fractional_kelly(
        KellyInputs(
            scenarios=thesis.scenario_distribution,
            payoff_unit="fraction_of_capital",
            limits=limits,
        )
    )

    result = _translate(thesis)

    assert as_str(result, key="outcome") == as_str(kelly, key="outcome")
    assert as_float(result, key="fraction_of_capital") == as_float(kelly, key="fraction_of_capital")
    assert as_float(result, key="requested_fraction_of_capital") == as_float(
        kelly, key="requested_fraction_of_capital"
    )


def test_no_edge_refuses_rather_than_publishing_a_zero_position() -> None:
    """Kelly's zero is a *decision*, and it is not any of the three refusals above.

    The scenario set has a positive expected value on some branches and a
    negative growth optimum, which is the LTCM point: positive EV is not
    sufficient. A function that published ``0.0`` with outcome
    ``sized_by_kelly`` would be indistinguishable from a limit binding at zero.
    """
    negative_edge = [
        ScenarioOutcome(name="base", probability=0.5, payoff_estimate=-0.05),
        ScenarioOutcome(name="bull", probability=0.3, payoff_estimate=0.02),
        ScenarioOutcome(name="bear", probability=0.2, payoff_estimate=-0.15),
    ]
    result = _translate(_thesis(status="calibrated", scenarios=negative_edge))

    assert as_str(result, key="outcome") == "refused_no_edge"
    assert as_float(result, key="fraction_of_capital") == 0.0
    assert "positive expected VALUE is not sufficient" in result.interpretation
    # Kelly ran, so the permission field must report that it did -- reporting
    # False here would understate what the function did.
    assert as_bool(result, key="scenario_sizing_permitted") is True


def test_the_pre_clip_request_is_published_beside_the_clipped_size() -> None:
    """D-057's P5: a binding cap destroys the conviction information.

    If only the clipped number were published, every view strong enough to
    exceed the cap would publish the same figure and the strength would be
    unreadable.
    """
    result = _translate(_live())

    requested = as_float(result, key="requested_fraction_of_capital")
    published = as_float(result, key="fraction_of_capital")
    assert requested > published, (
        "the fixture must exceed the cap, or this test does not exercise the clipping it is about"
    )
    assert as_str(result, key="outcome") == "clipped_by_position_limit"
    # The binding names what produced the NUMBER. It must not be overwritten by
    # the missing-budget fact -- that is a property of WHICH CHECKS RAN, and an
    # earlier draft assigning it here discarded the clipping entirely.
    assert as_str(result, key="binding_constraint") == "position_limit"
    assert as_float(result, key="permitted_risk_contribution") == 1.0


# ---------------------------------------------------------------------------
# Gate 5 — the risk budget (defect 1)
# ---------------------------------------------------------------------------


def test_the_risk_budget_does_not_scale_the_notional() -> None:
    """**The defect this increment's first draft shipped.**

    The draft computed ``multiplier = min(1.0, risk_share)``, multiplying a
    capital fraction by a risk fraction. Measured on the shipped configuration
    it returned **0.018** for a 12% risk allocation against a 15% position cap,
    where the answer is 0.12 — a 6.7x understatement invisible in the output,
    because 0.018 is a plausible position size.

    The function has no covariance (§9.3 supplies none), so the conversion
    cannot be performed. This test pins that it is **not attempted**: the
    published size is identical with and without a budget, and the allocation
    appears only as a bound.
    """
    thesis = _live()
    without = _translate(thesis)
    with_budget = _translate(thesis, budget=0.12)

    assert as_float(with_budget, key="fraction_of_capital") == as_float(
        without, key="fraction_of_capital"
    )
    assert as_float(with_budget, key="permitted_risk_contribution") == 0.12
    assert as_float(without, key="permitted_risk_contribution") == 1.0
    # And the 6.7x error is asserted to be absent by name, so a future
    # reinstatement of the multiplication fails here rather than silently
    # shipping a plausible-looking number.
    published = as_float(with_budget, key="fraction_of_capital")
    assert published != pytest.approx(0.15 * 0.12, abs=1e-9)


def test_no_notional_relation_holds_between_weight_and_risk_share() -> None:
    """The measurement that closes off the tempting repair.

    The intuition that would justify ``notional <= risk_budget`` is "a position's
    risk share is at least its notional share, so a risk budget bounds a
    notional". Probed over 20 000 random positive-definite covariances and
    random long-only weights, the claim fails in **100%** of trials — a 33.3%
    dollar weight contributed 29.9% / 27.0% / 43.1% of the risk in a
    three-instrument book, and a 20% weight contributed 6.8%.

    This test is the evidence, run at a reduced trial count so the suite stays
    fast. It is a *characterisation* test rather than a unit test, and it is
    here because a plausible-sounding false premise is more dangerous than an
    obvious error: the next reader who "fixes" gate 5 will reach for it.
    """
    rng = random.Random(20260920)  # noqa: S311 -- reproducible, not a secret
    violations = 0
    trials = 2_000

    for _ in range(trials):
        n = rng.randint(2, 5)
        vols = [rng.uniform(0.03, 0.60) for _ in range(n)]
        # A random factor structure, so the correlation matrix is PSD by
        # construction rather than by hope.
        k = rng.randint(1, 3)
        loadings = [[rng.uniform(-1.0, 1.0) for _ in range(k)] for _ in range(n)]
        covariance = [[0.0] * n for _ in range(n)]
        for i in range(n):
            for j in range(n):
                if i == j:
                    covariance[i][j] = vols[i] ** 2
                    continue
                num = sum(loadings[i][m] * loadings[j][m] for m in range(k))
                di = sum(loadings[i][m] ** 2 for m in range(k))
                dj = sum(loadings[j][m] ** 2 for m in range(k))
                rho = num / (di * dj) ** 0.5 if di > 0.0 and dj > 0.0 else 0.0
                covariance[i][j] = rho * vols[i] * vols[j]

        weights = [rng.random() for _ in range(n)]
        total = sum(weights)
        weights = [w / total for w in weights]

        shares = marginal_risk_contributions(weights, covariance)
        # ``value`` is the loose Section 22.9 union, so the keyed access needs an
        # assertion rather than an ignore -- an ignore here would hide a real
        # shape change in the primitive this test characterises.
        assert isinstance(shares.value, dict), "marginal_risk_contributions shape changed"
        pct = [float(x) / 100.0 for x in shares.value["risk_contribution_pct"]]
        if any(p < w - 1e-9 for w, p in zip(weights, pct, strict=True)):
            violations += 1

    assert violations == trials, (
        f"the `risk share >= notional share` premise held in "
        f"{trials - violations} of {trials} trials, so it is not universally "
        f"false as this project measured. Re-derive gate 5's rationale before "
        f"trusting either number."
    )


def test_a_zero_budget_refuses_rather_than_scaling_to_zero() -> None:
    """ "The book allocated this instrument no risk" is not "the allocation
    reduced the size by 100%".

    Both publish no size, so an outcome-blind consumer cannot tell a policy
    decision from a small number. A zero multiplier inside gate 5 would have
    produced the latter while reporting the former.
    """
    result = _translate(_live(), budget=0.0)

    assert as_str(result, key="outcome") == "refused_no_risk_budget"
    assert as_float(result, key="fraction_of_capital") == 0.0
    assert as_str(result, key="binding_constraint") == "none"


def test_a_missing_budget_publishes_the_kelly_size_and_names_the_gap() -> None:
    """§9.3's prose assumes a budget always exists; measured, a bare thesis has none.

    The design choice is to **still size** and to name the gap, rather than to
    raise: raising would make the integration look complete by making it
    impossible to call. The cost of that choice is that the output must never
    read as "checked and clear", which is what the binding constraint and the
    warning are for.
    """
    result = _translate(_live())

    # The missing budget is reported by the BOUND and the WARNING, never by the
    # binding constraint -- the binding must keep naming the cap that produced
    # the number, or a reader cannot tell whether a limit bound at all.
    assert as_float(result, key="permitted_risk_contribution") == 1.0
    assert as_float(result, key="fraction_of_capital") > 0.0
    assert as_str(result, key="binding_constraint") == "position_limit"
    assert any("did NOT run" in w for w in result.warnings)
    assert as_bool(result, key="scenario_sizing_permitted") is True


def test_the_binding_constraint_is_not_overwritten_by_a_missing_budget() -> None:
    """A missing budget is a fact about WHICH CHECKS RAN, not what bound the size.

    The first draft assigned ``binding = "missing_risk_budget"`` on the
    no-budget path, which **discarded** the clipping: every unbudgeted thesis
    rejected the position cap's provenance and reported "no budget" instead, so
    a reader could not tell whether a constraint had bound. The two facts are
    now separate fields, and this test asserts they do not collide.
    """
    clipped_no_budget = _translate(_live())
    clipped_with_budget = _translate(_live(), budget=0.12)

    assert (
        as_str(clipped_no_budget, key="binding_constraint")
        == as_str(clipped_with_budget, key="binding_constraint")
        == "position_limit"
    ), "the cap produced both numbers, so both must say so"
    # ...and the missing budget is still legible, through the other field.
    assert as_float(clipped_no_budget, key="permitted_risk_contribution") == 1.0
    assert as_float(clipped_with_budget, key="permitted_risk_contribution") != 1.0


def test_a_budget_tighter_than_the_position_cap_is_reported_as_tighter() -> None:
    """The announcement that must survive the decision not to apply it.

    The cap governs the *number* because it is the expressible constraint; the
    risk budget is the binding *policy*. Both facts are published, and neither
    is inferred from the other — a reader who saw only ``binding_constraint ==
    "position_limit"`` would conclude the budget was loose, which is the
    opposite of the truth here.
    """
    cap = get_settings().risk.max_position_fraction
    tighter = cap / 2.0
    result = _translate(_live(), budget=tighter)

    assert as_float(result, key="permitted_risk_contribution") == tighter
    assert as_str(result, key="binding_constraint") == "position_limit"
    assert any("TIGHTER than the position cap" in w for w in result.warnings)


def test_a_budget_looser_than_the_cap_is_not_reported_as_binding() -> None:
    """The mirror case, so the previous test's warning is known to discriminate.

    A warning that fires on both branches carries no information; asserting only
    the firing direction would leave that open.
    """
    cap = get_settings().risk.max_position_fraction
    looser = min(1.0, cap * 2.0)
    result = _translate(_live(), budget=looser)

    assert as_float(result, key="permitted_risk_contribution") == looser
    assert not any("TIGHTER than the position cap" in w for w in result.warnings)


def test_a_budget_naming_another_instrument_is_refused_at_construction() -> None:
    """A caller error, not a refusal — the two need different handling.

    Sizing one instrument against another's allocation publishes a proposal
    claiming a portfolio check it did not perform, and **no field on the output
    would show the mismatch**. Raising is right here because no output of this
    function would be correct; the ``refused_*`` outcomes are for inputs the
    function can answer honestly.
    """
    thesis = _live()
    with pytest.raises(ValidationError, match="TU futures"):
        ThesisPositionInputs(
            thesis=thesis,
            risk_budget_target=RiskBudgetTarget(
                instrument="TU futures", target_risk_contribution_pct=0.12
            ),
        )


def test_a_budget_for_a_no_trade_thesis_is_tolerated_not_raised() -> None:
    """A stale budget line must not destroy a batch of theses.

    The instrument check is skipped when the thesis is not a trade, so the
    function — which owns the refusal taxonomy — reports the refusal instead.
    Raising here would make one stale budget entry fail an entire run whose
    theses were all correctly standing down.
    """
    thesis = _thesis(instrument=NO_PRODUCTION_INSTRUMENT, status="empty_no_trade")
    result = translate_thesis_to_position(
        ThesisPositionInputs(
            thesis=thesis,
            risk_budget_target=RiskBudgetTarget(
                instrument="some other instrument", target_risk_contribution_pct=0.12
            ),
        )
    )
    assert as_str(result, key="outcome") == "refused_not_a_trade"


# ---------------------------------------------------------------------------
# The sign-off gate — Section 9.3's contract term
# ---------------------------------------------------------------------------


def _every_outcome() -> list[ModelResult]:
    """One input per reachable outcome, so no path is left unchecked.

    Every entry is asserted reachable by ``test_every_outcome_member_is_reachable``
    and ``test_every_binding_member_is_reachable``, so this list is the *proof*
    that the two ``Literal``s have no dead members. Two entries were wrong on the
    first draft and are worth recording, because both looked reasonable:

    * ``sized_by_kelly`` was claimed by a two-outcome fixture with positive edge
      at both branches. Probed: every such fixture pins Kelly's optimum at the
      **grid edge** (``f* = 0.5`` here, the maximum for a ``[0, 1]`` grid), so it
      always clips and never reaches this outcome. An *interior* optimum needs
      a bounded growth rate, which needs a longer payoff ratio against a wider
      loss — measured, ``p=0.45`` on ``+0.05 / -0.04`` gives ``f* = 0.125``.
    * ``refused_no_scenarios`` was claimed by two different inputs, both wrong.
      A no-trade thesis is refused by gate 1 before gate 3 is reached; an
      ``empty_no_trade`` thesis that *is* a trade is refused by gate 2 first.
      The member turned out to be **unreachable by construction** and was
      removed — see
      ``test_an_empty_distribution_is_unreachable_so_its_outcome_was_removed``.
      It is deliberately absent from this list: an entry here for it would be
      the fabrication this whole test exists to prevent.
    """
    negative_edge = [
        ScenarioOutcome(name="base", probability=0.5, payoff_estimate=-0.05),
        ScenarioOutcome(name="bull", probability=0.3, payoff_estimate=0.02),
        ScenarioOutcome(name="bear", probability=0.2, payoff_estimate=-0.15),
    ]
    # The only measured input that reaches `sized_by_kelly`: a full-Kelly optimum
    # strictly inside the search grid, hence below `cap * divisor = 0.30` and
    # hence not clipped. (An empty distribution would also keep the optimum
    # un-clipped, but it cannot reach this gate at all.)
    interior = [
        ScenarioOutcome(name="mild_up", probability=0.45, payoff_estimate=0.05),
        ScenarioOutcome(name="loss", probability=0.55, payoff_estimate=-0.04),
    ]
    return [
        # refused_not_a_trade, in all three of its reasons
        _translate(_thesis(instrument=NO_PRODUCTION_INSTRUMENT, status="empty_no_trade")),
        _translate(_thesis(instrument=ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT)),
        _translate(_thesis(instrument=_OUT_OF_UNIVERSE)),
        # refused_scenarios_uncalibrated -- both the non-empty distribution (the
        # live state) and the empty stand-down, which lands here rather than on
        # an emptiness gate because gate 2 fires first
        _translate(_thesis(status="SCENARIO_DISTRIBUTION_UNAVAILABLE")),
        _translate(_thesis(status="empty_no_trade")),
        # refused_no_edge
        _translate(_thesis(status="calibrated", scenarios=negative_edge)),
        # refused_no_risk_budget
        _translate(_live(), budget=0.0),
        # clipped_by_position_limit / binding="position_limit", with and without
        # a budget -- the pair that proves the binding is not overwritten
        _translate(_live()),
        _translate(_live(), budget=0.12),
        # sized_by_kelly / binding="kelly"
        _translate(_thesis(status="calibrated", scenarios=interior)),
    ]


def test_every_outcome_member_is_reachable() -> None:
    """A ``Literal`` member with no producer is the project's recurring defect.

    D-045/D-046/D-048 and **O-53** are all declared-but-unreachable branches.
    This test is the guard that a member added to the taxonomy is a path that
    actually runs — and, in the other direction, that removing a path removes
    its member rather than leaving it behind.
    """
    produced = {as_str(result, key="outcome") for result in _every_outcome()}
    declared = set(get_args(PositionTranslationOutcome))
    assert produced == declared, (
        f"declared but never produced: {sorted(declared - produced)}; "
        f"produced but not declared: {sorted(produced - declared)}"
    )


def test_every_binding_member_is_reachable() -> None:
    """The same guard on the binding ``Literal``."""
    produced = {as_str(result, key="binding_constraint") for result in _every_outcome()}
    declared = set(get_args(PositionBinding))
    assert produced == declared, (
        f"declared but never produced: {sorted(declared - produced)}; "
        f"produced but not declared: {sorted(produced - declared)}"
    )


def test_the_docstrings_agree_with_the_literal_they_describe() -> None:
    """A COUNTING claim in a docstring is a claim, and this is the receipt.

    **Found by the sweep, not by reading.** ``M10.2`` and ``M10.3`` both SURVIVED
    the first run: the two docstrings that state how many members and how many
    gates this module has could be changed to any number at all with every test
    still green, because ``get_args`` reads the *type* and a docstring is a
    string. D-072 had already paid for the first one — the type docstring shipped
    saying "nine members" for a ``Literal`` that had six, and had said nine since
    the draft, through a repair that *removed* three members. A reader who trusts
    the docstring and a reader who trusts the type were being told different
    things, and nothing in the suite could tell.

    Both claims are pinned to **word→number maps** rather than to whole
    sentences. A sentence-pinned substring (the first draft of this test) is a
    second thing to reflow on every edit, and a test that has to be edited
    whenever the prose around it moves gets edited *loosely*. The maps below
    survive reflow and still fail on the defect: change "six" to "nine" and the
    key goes missing.

    This is the same discipline as ``test_the_module_exports_what_it_declares``
    in ``tests/portfolio/test_risk_budget.py``: the numbers a maintainer reads
    before deciding what to change are pinned against the code that produced
    them.
    """
    words = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }

    outcome_count = len(get_args(PositionTranslationOutcome))
    binding_count = len(get_args(PositionBinding))

    type_doc = ProposedPosition.__doc__ or ""
    declared_outcomes = [words[w] for w in words if f"The {w} members" in type_doc]
    assert declared_outcomes == [outcome_count], (
        f"ProposedPosition's docstring claims "
        f"{declared_outcomes or ['no number']} members for a Literal that has "
        f"{outcome_count}. A type cannot check a sentence; this is the check."
    )

    binding_doc = PositionBinding.__doc__ or ""
    # **A `Literal` alias CANNOT carry a docstring** — `PositionBinding.__doc__`
    # is `None`, measured, and so is `PositionTranslationOutcome.__doc__`. The
    # prose documenting both lives in the *comments above them*, which Python
    # cannot reach at runtime. Asserting against `.__doc__` here would therefore
    # assert against the empty string and pass for the wrong reason — the same
    # class of defect as a test whose premise is a doc rather than a measurement.
    #
    # So the checkable claim is the one that IS reachable: the Pydantic model
    # that publishes the field carries the members' documentation, and
    # `ProposedPosition`'s docstring names them. This is the weaker of the two
    # available checks and it is stated as such rather than dressed up.
    assert binding_doc == "" or binding_doc is None, (
        "if a Literal alias ever gains a real docstring, this test's premise "
        "changes and the comment above is stale -- measure it again rather than "
        "assuming the limitation still holds"
    )
    guard_doc = ProposedPosition.__doc__ or ""
    assert "binding_constraint" in guard_doc, (
        "ProposedPosition's docstring must document the field that carries the "
        "binding Literal: the Literal itself cannot, so this is the only "
        "reachable place a reader learns what a member means"
    )
    assert binding_count == len(get_args(PositionBinding))

    function_doc = translate_thesis_to_position.__doc__ or ""
    # The function's gate list must state the SAME number the census below
    # measures. Both directions are checked because the sentence is phrased
    # "there are N, not M" and either half drifting is the defect.
    gate_claims = [words[w] for w in words if f"There are **{w}**, not" in function_doc]
    assert len(gate_claims) == 1, (
        f"the gate count must be stated exactly once and in words; found "
        f"{gate_claims or ['nothing']} in translate_thesis_to_position's docstring"
    )
    asserted_gates = gate_claims[0]
    assert asserted_gates == _count_gates_in_the_docstring(function_doc), (
        "the 'there are N, not M' sentence disagrees with the numbered gate list "
        "beneath it -- the number a maintainer reads before adding a gate is the "
        "number that licenses reinstating dead code"
    )
    assert asserted_gates == _GATE_OUTCOMES, (
        f"the docstring claims {asserted_gates} gates but this file's producer "
        f"census accounts for {_GATE_OUTCOMES}. Update BOTH, or the claim is "
        f"unverified -- which is the defect M10.3 exploited."
    )


#: The number of gates ``translate_thesis_to_position`` applies, as a fact this
#: module states ONCE and asserts in three places. It is a module constant rather
#: than a literal in the test because the reachability guard, the docstring check
#: and the outcome census must all agree, and three independent literals would be
#: three places to forget.
_GATE_OUTCOMES = 4


def _count_gates_in_the_docstring(function_doc: str) -> int:
    """Count the gates in the function's own gate list.

    Scoped **between the two headings** the docstring uses, not over the whole
    text: the function has three numbered lists (the gates, the specification's
    gaps, and the cost of each gap), and a naive count over the whole docstring
    returns 8 rather than 4. The first draft of this helper did exactly that and
    the assertion caught it — which is the point of counting rather than
    trusting, and also the reason the scope is named here rather than left to
    the next reader.
    """
    lines = function_doc.splitlines()
    start = None
    stop = len(lines)
    for i, line in enumerate(lines):
        if start is None and "The gates, in the order they are applied" in line:
            start = i
        elif start is not None and line.strip().startswith("What the specification"):
            stop = i
            break
    if start is None:  # pragma: no cover - the heading is part of the shipped text
        return 0
    return sum(
        1
        for line in lines[start:stop]
        if line.strip()[:2].rstrip(".").isdigit() and line.strip()[1:2] == "."
    )


def test_the_sign_off_gate_is_on_every_outcome() -> None:
    """§9.3's gate is a **contract term**, not a caveat on the happy path.

    Section 1.1's distinction between a reasoning layer and a signal generator
    rests on this sentence surviving every path. Asserting it on one path — the
    natural test — leaves the refusals uncovered, which are exactly the results
    a consumer is most likely to pass along unread.
    """
    for result in _every_outcome():
        outcome = as_str(result, key="outcome")
        assert SIGN_OFF_REQUIRED in result.warnings, f"{outcome} lost the sign-off gate"
        assert as_bool(result, key="requires_human_sign_off") is True, outcome


def test_the_sign_off_gate_says_the_value_is_not_an_order() -> None:
    """The gate must deny executability in words a caller cannot misread.

    A future edit that reworded it at one site would change what the output
    promises without changing any number in it, which is why the sentence is a
    module constant and this is asserted against the constant's own content.
    """
    assert "PROPOSAL ONLY" in SIGN_OFF_REQUIRED
    assert "not an order" in SIGN_OFF_REQUIRED
    assert "human" in SIGN_OFF_REQUIRED
    for result in _every_outcome():
        assert SIGN_OFF_REQUIRED in result.warnings


# ---------------------------------------------------------------------------
# The result contract
# ---------------------------------------------------------------------------


def test_the_published_value_is_the_proposal_serialised() -> None:
    """The value is the typed object, so a consumer never parses prose.

    ``value`` is a deliberately loose union (Section 22.9), so the contract that
    it holds *this* shape is a test rather than a type.
    """
    result = _translate(_live(), budget=0.12)

    assert result.model_name == "translate_thesis_to_position"
    assert result.country == "us"
    raw = result.value
    assert isinstance(raw, dict), f"value is {type(raw).__name__}, not a dict"
    proposal = ProposedPosition.model_validate(raw)
    assert proposal.outcome == "clipped_by_position_limit"
    assert proposal.instrument == _IN_UNIVERSE
    assert proposal.direction == "long"
    assert proposal.timeframe == "6-12 months"
    assert proposal.requires_human_sign_off is True


def test_a_refusal_carries_a_non_empty_reason() -> None:
    """A refusal without a reason is indistinguishable from a bug.

    Every refusal is built through one constructor for this property, so the
    test is a guard on that clause rather than on each site.
    """
    for result in _every_outcome():
        reason = as_str(result, key="reason")
        assert reason.strip(), as_str(result, key="outcome")
        assert len(reason) > 40, "a reason short enough to be a placeholder"


def test_every_sizing_logic_names_the_real_mechanism() -> None:
    """A translated proposal must not still say "human-determined".

    §16.2's Q11 sentence is ``"Phase 1: human-determined; Phase 4+: ..."``. On a
    path where this function *did* derive a number that label has outlived its
    truth, and copying it would make the output claim a human chose the size.
    """
    for result in _every_outcome():
        outcome = as_str(result, key="outcome")
        logic = as_str(result, key="sizing_logic")
        if outcome.startswith("refused_"):
            continue  # a refusal derived no size, so the thesis's label stands
        assert "human-determined" not in logic, (
            f"{outcome} published the Phase-1 label on a path where this function did the sizing"
        )
        assert "fractional_kelly" in logic, f"{outcome} does not name its mechanism"


def test_the_refusal_sizing_logic_does_not_claim_a_mechanism_ran() -> None:
    """The refusal's replacement label says *none*, which is true on every path.

    The alternative — echoing an empty string — would publish a refusal with no
    statement of what was not done. Note the function preserves a *non-empty*
    thesis sizing_logic (the Phase-1 sentence is genuinely the human's answer on
    a refusal), so the replacement is asserted on the empty case it exists for.
    """
    result = _translate(_thesis(status="SCENARIO_DISTRIBUTION_UNAVAILABLE", sizing_logic=""))
    logic = as_str(result, key="sizing_logic")
    assert logic.startswith("none")
    assert "see outcome" in logic


def test_a_refusal_preserves_a_non_empty_thesis_sizing_logic() -> None:
    """The refusals that are not the function's own must not erase the thesis's.

    On a Section 25 refusal the human path is exactly what remains, so the
    thesis's own sizing_logic is the honest label and replacing it would delete
    the only guidance the reader has.
    """
    result = _translate(_thesis(status="SCENARIO_DISTRIBUTION_UNAVAILABLE"))
    assert as_str(result, key="sizing_logic") == "Phase 1: human-determined"


def test_an_empty_sizing_logic_is_replaced_rather_than_copied() -> None:
    """``TradeIdea.sizing_logic`` defaults to ``""`` and can be constructed so.

    A standalone ``TradeIdea`` bypasses the builder, so the empty string is
    reachable and would publish a refusal saying nothing.
    """
    result = _translate(_thesis(status="SCENARIO_DISTRIBUTION_UNAVAILABLE", sizing_logic=""))
    assert as_str(result, key="sizing_logic").strip()


def test_the_confidence_is_computed_from_stated_facts() -> None:
    """Section 22.8: confidence is derived, never asserted.

    A refusal publishes the floor (it is the absence of a size, not a
    measurement of one); a sizing path with no risk budget is penalised by the
    data-quality flag because the covariance needed to verify the bound is
    absent. The two must not be equal, or the flag is inert.
    """
    refusal = _translate(_thesis(status="SCENARIO_DISTRIBUTION_UNAVAILABLE"))
    unchecked = _translate(_live())
    checked = _translate(_live(), budget=0.12)

    assert refusal.confidence < unchecked.confidence, (
        "a refusal must not carry the same confidence as a computation"
    )
    assert checked.confidence > unchecked.confidence, (
        "running the risk check must raise confidence over not running it"
    )


def test_the_result_flags_the_missing_budget_as_a_data_quality_gap() -> None:
    """The flag travels so a downstream collector does not have to re-derive it."""
    assert _translate(_live()).data_quality_flags_present is True
    assert _translate(_live(), budget=0.12).data_quality_flags_present is False


def test_the_context_states_the_proposal_never_places_an_order() -> None:
    """The context is what an OpenBB Workspace consumer renders beside the value."""
    result = _translate(_live(), budget=0.12)
    assert "PROPOSED" in result.context
    assert "NEVER places an order" in result.context


def test_inputs_used_names_both_supplied_inputs() -> None:
    result = _translate(_live(), budget=0.12)
    assert set(result.inputs_used) == {"thesis", "risk_budget_target"}


# ---------------------------------------------------------------------------
# The output type's own invariants
# ---------------------------------------------------------------------------


def test_a_refusal_cannot_carry_a_size() -> None:
    """The schema refuses it, so no construction site has to remember to.

    Without this, a future edit could publish a refusal with a plausible size on
    it and every consumer that branches on the number would treat it as a small
    position.

    **All three size fields are asserted, and the third one was found by the
    sweep.** ``M8.1`` relaxes the guard's ``or`` to an ``and``, and it SURVIVED
    the first run because the shipped guard never tested
    ``requested_fraction_of_capital`` at all — measured, a refusal carrying
    ``requested_fraction_of_capital=0.05`` and zeros elsewhere was ACCEPTED.
    The reason a single-field test would not have caught it is that the two
    fields the guard *did* check are written together on every path today, so
    no input distinguishes them. The third field is the one a reader is most
    likely to mistake for the proposal's real size (D-057's P5: the pre-clip
    request is what carries the conviction), which is exactly why it is the
    worst of the three to leave unguarded. Both directions are asserted here:
    each field alone must be refused.
    """
    base: dict[str, Any] = {
        "outcome": "refused_not_a_trade",
        "reason": "a reason long enough to satisfy the field's own constraint",
        "instrument": NO_PRODUCTION_INSTRUMENT,
        "direction": "n/a",
        "timeframe": "n/a",
        "fraction_of_capital": 0.0,
        "requested_fraction_of_capital": 0.0,
        "notional_fraction_after_constraints": 0.0,
        "binding_constraint": "none",
        "permitted_risk_contribution": 1.0,
        "scenario_sizing_permitted": False,
        "sizing_logic": "none",
    }
    # The premise: with all three at zero the object is legal, so what follows
    # is testing the guard and not the field bounds.
    assert ProposedPosition(**base).fraction_of_capital == 0.0

    for field in (
        "fraction_of_capital",
        "requested_fraction_of_capital",
        "notional_fraction_after_constraints",
    ):
        with pytest.raises(ValidationError, match="is a refusal but a non-zero size"):
            ProposedPosition(**{**base, field: 0.05})


def test_a_refusal_cannot_name_a_binding_constraint() -> None:
    """A constraint cannot have produced a size that was not produced."""
    with pytest.raises(ValidationError, match="is a refusal but binding_constraint"):
        ProposedPosition(
            outcome="refused_no_edge",
            reason="a reason long enough to satisfy the field's own constraint",
            instrument=_IN_UNIVERSE,
            direction="long",
            timeframe="6-12 months",
            fraction_of_capital=0.0,
            requested_fraction_of_capital=0.0,
            notional_fraction_after_constraints=0.0,
            binding_constraint="position_limit",
            permitted_risk_contribution=1.0,
            scenario_sizing_permitted=True,
            sizing_logic="none",
        )


def test_a_constraint_cannot_increase_the_notional() -> None:
    """Limits reduce exposure; this is what would catch a budget that levers up.

    The invariant is enforced by the output type rather than by a comment,
    because the failure would be a *larger* position reported as constrained —
    the direction that looks like success.
    """
    with pytest.raises(ValidationError, match="exceeds the unconstrained"):
        ProposedPosition(
            outcome="sized_by_kelly",
            reason="a reason long enough to satisfy the field's own constraint",
            instrument=_IN_UNIVERSE,
            direction="long",
            timeframe="6-12 months",
            fraction_of_capital=0.10,
            requested_fraction_of_capital=0.10,
            notional_fraction_after_constraints=0.20,
            binding_constraint="kelly",
            permitted_risk_contribution=1.0,
            scenario_sizing_permitted=True,
            sizing_logic="kelly",
        )


def test_the_input_model_refuses_unknown_fields() -> None:
    """``extra="forbid"`` on the inputs, per the project's config convention."""
    with pytest.raises(ValidationError):
        ThesisPositionInputs(thesis=_live(), unexpected=1)  # type: ignore[call-arg]


def test_the_proposal_refuses_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ProposedPosition(
            outcome="sized_by_kelly",
            reason="a reason long enough to satisfy the field's own constraint",
            instrument=_IN_UNIVERSE,
            direction="long",
            timeframe="6-12 months",
            fraction_of_capital=0.1,
            requested_fraction_of_capital=0.1,
            notional_fraction_after_constraints=0.1,
            binding_constraint="kelly",
            permitted_risk_contribution=1.0,
            scenario_sizing_permitted=True,
            sizing_logic="kelly",
            unexpected=1,  # type: ignore[call-arg]
        )


# ---------------------------------------------------------------------------
# Economics — the properties a reviewer would argue with
# ---------------------------------------------------------------------------


def test_the_size_never_exceeds_the_position_cap() -> None:
    """Section 17.3's hard constraint holds on every sizing path.

    Asserted over the config's own cap rather than a literal, so a policy change
    moves both the limit and the test together.
    """
    cap = get_settings().risk.max_position_fraction
    for budget in (None, 0.01, 0.05, 0.12, 0.5, 1.0):
        result = _translate(_live(), budget=budget)
        size = as_float(result, key="fraction_of_capital")
        assert size <= cap + 1e-12, f"budget={budget} published {size} above cap {cap}"


def test_a_larger_risk_allocation_never_shrinks_the_reported_bound() -> None:
    """The published bound is monotone in the allocation.

    Monotonicity is the weakest property a bound must have, and the one the
    original multiplicative bug violated in the opposite direction: a larger
    allocation produced a *smaller* published size.
    """
    sizes = []
    for budget in (0.02, 0.05, 0.12, 0.30):
        result = _translate(_live(), budget=budget)
        sizes.append(as_float(result, key="permitted_risk_contribution"))
    assert sizes == sorted(sizes)
    # And the notional is unchanged throughout, because it is not derived from
    # the allocation at all.
    notionals = {
        as_float(_translate(_live(), budget=b), key="fraction_of_capital")
        for b in (0.02, 0.05, 0.12, 0.30)
    }
    assert len(notionals) == 1


def test_the_thesis_is_not_mutated() -> None:
    """The function reads the thesis; it must not write to it.

    A mutation would be invisible here but would corrupt any caller that keeps
    the thesis for comparison, which is the normal use — build once, translate
    against several budget scenarios.
    """
    thesis = _live()
    before = thesis.model_dump()
    _translate(thesis, budget=0.12)
    assert thesis.model_dump() == before


def test_the_direction_is_passed_through_not_derived() -> None:
    """The thesis owns the direction; §9.3's function adds no sign logic.

    Deriving one here would let the sizing layer disagree with the reasoning
    layer about which way the trade points, and nothing downstream could detect
    the disagreement.
    """
    for direction in ("long", "short"):
        result = _translate(_thesis(status="calibrated", direction=direction))
        assert as_str(result, key="direction") == direction
