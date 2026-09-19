"""Module 14 — ``build_us_macro_thesis()``: the thesis builder (Section 7.2, 16.2).

This is **the seam function**. It appears on the Tier 4 checklist *and* on the
Phase 3 checklist, and that overlap is not bookkeeping — it is the point where
the models layer stops producing numbers and the thesis layer starts making
claims. Everything upstream is a measurement; everything here is a judgment
with an audit trail.

What it does
------------
It answers Section 16.2's fifteen questions **in order**, and returns a
``MacroThesis``. Three of those questions can end the sentence early by
returning a no-trade thesis (Section 16.3, D-068):

======  ==========================================================================
Q       stands down when
======  ==========================================================================
**Q6**  ``abs(gap.raw_gap) <= gap.dispersion`` — the gap is inside the policy
        rules' own disagreement
**Q7**  ``convergence == "CONFLICTED"`` — growth and inflation point opposite ways
**Q8**  ``invalidation.identified is False`` — no evidence-based falsifier exists
======  ==========================================================================

The three gates are checked **in that order**, and each one hands its own gate
object to ``no_trade_thesis`` as ``evidence`` and **states the trigger it
observed**. That is the closing condition of **O-70**, **O-79** and **O-85**.

What Section 16.2's sample gets wrong, and why
----------------------------------------------
The sample is a *sketch of the control flow*, not a running program. Measured
against the shipped contracts (``.probe/p_d069_1.py``), it diverges in **eight**
places — and the corrections are not stylistic:

**1. ``select_instrument`` takes two arguments, not two positional scalars.**
The sample calls ``select_instrument(gap, regime)``. The shipped signature is
``select_instrument(inputs: InstrumentSelectionInputs, universe:
InstrumentUniverse) -> ModelResult``. ``InstrumentSelectionInputs`` requires
``thesis_type`` and ``gap_direction``, and **neither is derivable from ``gap``**:
``thesis_type`` is an analytical choice among seven families, and a gap says
nothing about which one the thesis is. So this builder **takes the choice as a
parameter** rather than inventing one. A builder that guessed
``POLICY_PATH_GAP`` from ``unit == "%"`` would be manufacturing a claim.

**2. Three returns are objects, and the sample assigns each to a scalar field.**
Measured, one at a time:

- ``derive_invalidation_conditions`` returns an ``InvalidationAssessment``; the
  sample assigns it to ``stop_or_invalidation``, which is ``str``.
- ``build_confirmation_signals`` returns a ``ConfirmationSignalAssessment``
  (``signals`` **plus** the unreadable/neutral census, D-066); the sample
  assigns it to ``confirmation_signals``, which is ``list[ConfirmationSignal]``.
- ``collect_all_warnings`` returns a ``WarningSummary`` (§16.4's verbatim list
  **plus** attribution, D-067); the sample assigns it to ``warnings``, which is
  ``list[str]``. Measured refusal: ``sources``.

Each is unpacked at exactly one line here, with the rich object kept — the
assessment's census goes into the thesis's ``warnings``, and the summary's
attribution into the warning lines themselves.

**3. **Q8 is absent from the sample entirely.*** D-063 added the gate
(``invalidation.identified is False`` → no-trade) and the sample cannot host it:
it never binds the assessment to a name, so there is no variable for the check
to read. This builder binds it and checks it.

**4. ``catalysts=next_catalyst_calendar()`` has no branch for its failure.**
The function **raises** ``CatalystSourceError`` when no official source answers
(D-065) — deliberately, so an unreachable calendar cannot read as an empty one.
A builder that let that propagate would make every thesis fail on a network
blip; a builder that swallowed it would publish an empty calendar as a fact.
This one catches it, records the unreachability as a **warning on the thesis**,
and continues — because "we could not date the catalysts" is a disclosure, not
a reason to have no thesis.

**5. ``build_scenario_distribution`` returns ``[]`` for a verdict that cannot
carry a thesis.** Called after Q6 and Q7 that path is still reachable for
``NO_SIGNAL``. ``[]`` is schema-valid; this builder does not add a branch for
it, because §16.2's ordering already makes it correct — but it is stated here so
the next reader does not "fix" it into a raise.

**6. The sample's ``direction`` rule reads the gap and nothing else.**
``"long" if gap.raw_gap < 0 else "short"`` is right for a **rates** instrument
(a model rate below the market's is a view that rates fall, i.e. a receiver) and
false for every other family — a curve steepener, an FX carry, an equity
expression. So the direction is taken **from ``select_instrument``'s own
output**, and the sample's rule is only the fallback for the one family it was
written for. Measured: ``select_instrument`` already publishes
``GapDirection`` with the sign convention stated, so re-deriving it would be a
second, unstated definition of the same thing.

**7. ``MacroThesis`` requires eight fields and the sample passes all eight.**
*(Corrected from the carried-in note, which said six were missing. Measured:
**zero** are missing. The "six required fields" figure belongs to §16.4's
``no_trade_thesis`` sample, D-068's defect 1 — two different samples, one
misattribution.)* The sample's field set is complete; only its **values** are
divergent.

**8. The sample checks ``is_meaningful`` and then calls ``gap.raw_gap``.**
``is_meaningful = abs(gap.raw_gap) > ensemble["dispersion"]`` computes the test
from the ensemble dict, while the shipped ``canonical_policy_gap`` computes
``is_meaningful`` from the **median** of the three rules and the **max-min
spread**. Two definitions of the same predicate, and only one of them is the
canonical gap's own. This builder uses ``gap.is_meaningful`` — the field on the
object it is about to publish — so the verdict and the evidence cannot disagree.

What this function does NOT do
------------------------------
- **It does not trade.** No order, no position, no sizing arithmetic. Sizing
  ships as the Phase-1 prose §16.2 asks for.
- **It does not invent a ``ThesisType``.** The caller names it (correction 1).
- **It does not derive Q1's ``ModelResult``s.** See ``_run_economy_reads``.
- **It does not silently drop the rich objects** the three gates hold.
- **It does not catch anything but ``CatalystSourceError``.** A broad ``except``
  around the model chain would make a broken model look like a no-trade, which
  is the one failure this module must not produce (Section 16.3: no-trade is not
  a fallback for missing data).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from macro_engine.models.contracts import ModelResult, utc_now
from macro_engine.models.convergence import ConvergenceInputs, classify_convergence
from macro_engine.models.instrument_selection import (
    GapDirection,
    InstrumentSelectionInputs,
    ThesisType,
    select_instrument,
)
from macro_engine.models.policy_rules import (
    FirstDifferenceInputs,
    MarketPricingGap,
    PolicyRuleResult,
    TaylorRuleInputs,
    balanced_approach_rule,
    canonical_policy_gap,
    derive_market_implied_policy_path,
    first_difference_rule,
    policy_rule_ensemble,
    taylor_rule,
)
from macro_engine.thesis_layer.catalysts import CatalystSourceError, next_catalyst_calendar
from macro_engine.thesis_layer.invalidation import (
    InvalidationAssessment,
    derive_invalidation_conditions,
)
from macro_engine.thesis_layer.no_trade import (
    NO_TRADE_INSTRUMENT as NO_TRADE_INSTRUMENT_VALUE,
)
from macro_engine.thesis_layer.no_trade import (
    NoTradeDecision,
    no_trade_thesis,
    render_no_trade_thesis,
)
from macro_engine.thesis_layer.scenarios import build_scenario_distribution
from macro_engine.thesis_layer.schemas import (
    ConvergenceClassification,
    MacroThesis,
    ProductionUniverse,
    ThesisStatus,
    TradeIdea,
)
from macro_engine.thesis_layer.signals import (
    ConfirmationSignalAssessment,
    build_confirmation_signals,
)
from macro_engine.thesis_layer.warnings import (
    UnattributedWarning,
    WarningSummary,
    collect_all_warnings,
)

#: The value a stand-down reports as its instrument, **re-exported**: the
#: declaration lives in ``no_trade.py`` (``_build_no_trade_trade_idea``), which
#: owns the no-trade shape and whose sweep certifies the literal. This module
#: does not re-declare it — measured during D-069: a second ``= "NONE"`` here
#: would be a definition with **no production consumer** (the live path takes its
#: instrument from ``select_instrument``, and every stand-down goes through
#: ``render_no_trade_thesis``), so it could silently drift from the value the
#: thesis actually publishes. Aliased so a caller can compare against the
#: published shape without importing from a private helper.
NO_TRADE_INSTRUMENT = NO_TRADE_INSTRUMENT_VALUE

#: Section 16.2 Q11's Phase-1 sizing sentence, verbatim in intent. A module
#: constant because a test asserts the thesis carries it and a re-typed string
#: at a call site is the drift this project has measured repeatedly.
SIZING_LOGIC_PHASE_1 = (
    "Phase 1: human-determined; Phase 4+: fractional_kelly(scenarios, confidence)"
)

#: The thesis-id prefix, so an id is legible in a log without a lookup.
THESIS_ID_PREFIX = "us"


def new_thesis_id(*, as_of: datetime) -> str:
    """A fresh thesis id: ``us-YYYY-MM-DD-<8 hex>``.

    §16.2 writes ``thesis_id=generate_id()`` and §7.3's example shows
    ``"us-2026-03-a1"``. **No ``generate_id`` exists anywhere in the tree**
    (measured), so §16.2's sample is calling a function that was never defined —
    a ninth divergence, and one ``mypy`` cannot miss but a reader scanning the
    sample would.

    The format is date-first because the id is a **log key**: an operator
    paging through a day's theses needs them adjacent, and a UUID alone sorts
    arbitrarily. The random suffix is drawn from ``uuid4`` rather than a counter
    because a counter needs shared state, and this builder is documented as a
    pure function of its inputs with no database.

    ``as_of`` is the thesis's own stamp rather than wall-clock, so the id is
    reproducible from the same inputs — which is what makes a re-run
    comparable rather than merely different.
    """
    return f"{THESIS_ID_PREFIX}-{as_of:%Y-%m-%d}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# The one place this module refuses to guess
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EconomyReads:
    """Q1's three economy reads, as the builder's caller supplies them.

    Why this is a parameter and not computed here
    ---------------------------------------------
    Section 16.2's Q1 reads:

        growth = output_gap(...)                  # Module 7
        inflation = inflation_breadth_score(...)  # Module 5
        labor = labor_tightness_score(...)        # Module 6

    ``output_gap`` has a snapshot-fed helper (``output_gap_from_snapshot``,
    Module 7 Tier 1). The other two do **not**: ``inflation_breadth_score`` takes
    an ``InflationSubMeasures`` of three **month-over-month percent floats**
    (``cpi_headline_mom``, ``cpi_core_mom``, ``pce_core_mom``) and
    ``labor_tightness_score`` takes a ``LaborInputs`` of raw levels, and
    **neither has a ``snapshot``-named helper anywhere in the tree** (measured:
    the snapshot-fed helper census is ``[]`` for ``inflation_nowcast``,
    ``labor_synthesis``, ``regime`` and ``national_accounts`` alike).

    So "run every Phase-1 model against the snapshot" (§7.2 step 1) requires a
    **plumbing layer that does not exist yet** — one that turns
    ``MacroDataSnapshot`` fields into each model's input record, with unit
    conventions, yoy/mom transformation, and release-lag handling per series.
    That layer is Phase 3's own work item and is *not* a side effect of shipping
    the builder.

    The honest resolution is the one this project has used before (D-045's
    ``MANUAL`` route, D-036): **take what only the caller can supply as a
    parameter, and say so in the return.** A builder that reached into the
    snapshot and invented the transforms would produce a thesis whose numbers
    cannot be reproduced from a stated input, which is worse than a builder with
    a wider signature.

    A caller holding a snapshot and no plumbing layer still gets a fully-formed,
    fully-disclosed thesis; a caller holding a wired pipeline passes real reads.
    **Neither is silently preferred.**

    The three results are kept as ``ModelResult``s rather than floats because
    every downstream consumer — the regime classifier, the convergence
    classifier, the signal builder, the invalidation deriver, the warning
    collector — reads the result, not the number, and five fields
    (``model_name``, ``source_family``, ``warnings``, ``confidence``,
    ``as_of``) travel only on the object.
    """

    growth: ModelResult
    inflation: ModelResult
    labor: ModelResult

    def as_sequence(self) -> tuple[ModelResult, ModelResult, ModelResult]:
        """The three reads in §16.2's documented order, for the warning collector."""
        return (self.growth, self.inflation, self.labor)


# ---------------------------------------------------------------------------
# Q3-Q5 — the policy chain
# ---------------------------------------------------------------------------


#: The three policy rules, in §7.3's order. Named so the two functions that
#: unpack the tuple cannot disagree about the order.
RuleTrio = tuple[PolicyRuleResult, PolicyRuleResult, PolicyRuleResult]


def build_policy_gap(
    taylor_inputs: TaylorRuleInputs,
    first_difference_inputs: FirstDifferenceInputs,
    *,
    short_yield: float,
    short_tenor_term_premium: float | None,
) -> tuple[MarketPricingGap, RuleTrio, ModelResult, ModelResult]:
    """Q3-Q5: the three rules, their dispersion, and the canonical gap.

    Returns ``(gap, rules, ensemble)``. The rules are returned alongside the
    ensemble because ``MacroThesis.policy_view`` is §7.3's documented dict of
    **all three** rule values plus dispersion **plus** the interpretation, and a
    caller that only kept the ensemble would have to re-run the rules to fill it.

    The gap is built by ``canonical_policy_gap`` — the ONE valid definition
    (Section 22.4). Section 16.2's sample builds its own ``MarketPricingGap``
    from ``ensemble["rules"]["taylor"]`` and a hand-written
    ``is_meaningful = abs(raw_gap) > ensemble["dispersion"]``, which is a
    **second definition of the same predicate**: ``canonical_policy_gap`` sets
    ``is_meaningful`` from the **median** of the three rules, not from Taylor,
    and from the max-min spread, not from the ensemble dict's field. Where two
    definitions of one predicate exist, the object that publishes the verdict
    must be the one that computes it — otherwise ``gap.is_meaningful`` and the
    number next to it can disagree, which is the ``is_meaningful`` version of
    D-067's attribution defect.

    ``market_implied`` is derived from the curve, not passed as a rate:
    ``derive_market_implied_policy_path`` returns the **expectations component**
    and attaches its own warnings when no term premium is available. Those
    warnings are **not** dropped — they are returned on the ensemble's sibling
    result and reach the thesis through ``collect_all_warnings``.
    """
    taylor = taylor_rule(taylor_inputs)
    balanced = balanced_approach_rule(taylor_inputs)
    first_diff = first_difference_rule(first_difference_inputs)

    ensemble = policy_rule_ensemble(taylor, balanced, first_diff)

    market_path = derive_market_implied_policy_path(
        short_yield=short_yield,
        short_tenor_term_premium=short_tenor_term_premium,
    )
    market_implied = market_path.value
    if not isinstance(market_implied, int | float):
        raise TypeError(
            f"derive_market_implied_policy_path returned a "
            f"{type(market_implied).__name__} for value; the canonical gap needs a "
            f"rate. The market-implied path is a PROXY whose value is documented as "
            f"a float, so a non-numeric value here means the function changed shape "
            f"and this call site was not updated — not that the market has no "
            f"implied path."
        )

    gap = canonical_policy_gap(taylor, balanced, first_diff, float(market_implied))
    return gap, (taylor, balanced, first_diff), ensemble, market_path


# ---------------------------------------------------------------------------
# The policy_view dict (Section 7.3's documented shape)
# ---------------------------------------------------------------------------


def policy_view_dict(
    rules: RuleTrio,
    ensemble: ModelResult,
) -> dict[str, object]:
    """§7.3's ``policy_view``: all three rules, the dispersion, the interpretation.

    The sample's own ``MacroThesis(... policy_view=ensemble ...)`` passes the
    **whole ``ModelResult``**, which is acceptable to the ``dict[str, object]``
    annotation by accident (pydantic would reject a ``BaseModel`` where a
    ``dict`` is declared — so the sample would fail here too, a fourth
    divergence from the shipped schema).

    The shape below is §7.3's, taken literally::

        {"taylor": 3.2, "balanced": 2.6, "first_difference": 3.0,
         "dispersion": 0.6, "interpretation": "Low dispersion — rules agree"}

    ``dispersion`` is read from the **ensemble** rather than recomputed, so the
    published number and the classifier's own cannot drift.
    """
    taylor, balanced, first_diff = rules
    value = ensemble.value
    if not isinstance(value, dict):
        raise TypeError(
            f"policy_rule_ensemble returned a {type(value).__name__} for value; "
            f"§7.3's policy_view needs the documented dict with 'rules', "
            f"'dispersion_pp' and 'interpretation'."
        )
    return {
        "taylor": float(_rule_number(taylor)),
        "balanced": float(_rule_number(balanced)),
        "first_difference": float(_rule_number(first_diff)),
        "dispersion": value.get("dispersion_pp"),
        "agreement": value.get("agreement"),
        "interpretation": ensemble.interpretation,
    }


def _rule_number(result: PolicyRuleResult) -> float:
    """Narrow a rule's ``value`` to a float, refusing anything else.

    ``PolicyRuleResult.value`` is typed ``object`` on the base, so this is where
    the numeric contract is enforced once rather than at three unpack sites.
    """
    if isinstance(result.value, bool) or not isinstance(result.value, int | float):
        raise TypeError(
            f"{result.model_name} returned a {type(result.value).__name__} for "
            f"value; a policy rule must produce a rate in percent."
        )
    return float(result.value)


# ---------------------------------------------------------------------------
# The gap as a convergence signal
# ---------------------------------------------------------------------------


def _as_signal(gap: MarketPricingGap, *, as_of: datetime) -> ModelResult:
    """The gap, as the ``ModelResult`` that ``classify_convergence`` can read.

    A named function rather than an inline construction because three things
    about it are load-bearing and each one is a defect if forgotten:

    * ``value=gap.raw_gap`` — the **signed** gap, not ``abs`` and not
      ``is_meaningful``. ``_direction`` reads the sign, so passing the magnitude
      would make every gap point the same way and the classifier would see the
      thesis confirm itself unconditionally.
    * ``model_name="market_pricing_gap"`` — the label a reader sees in the
      per-signal direction table. A bare default would put the class name there.
    * ``confidence=gap.is_meaningful`` is **not** copied: a gap carries a
      significance verdict, not a measurement confidence, and inventing one
      would be the D-046 "scored by its own subject matter" failure. The
      confidence is ``compute_confidence``'s to produce, so the adapter reports
      what it knows and no more.

    ``warnings`` is empty deliberately: the gap's own caveats live in its
    ``interpretation`` and in the ensemble's warnings, and duplicating them here
    would make the same fact appear twice in the thesis's warning list with two
    different attributions (D-067's de-duplication collision).
    """
    return ModelResult(
        model_name="market_pricing_gap",
        country="us",
        as_of=as_of,
        value=gap.raw_gap,
        confidence=1.0,
        interpretation=gap.interpretation,
        context=(
            f"Adapted from MarketPricingGap for convergence classification: the "
            f"signed raw_gap ({gap.raw_gap:+.4f}pp) is the direction, against a "
            f"rule dispersion of {gap.dispersion:.4f}pp."
        ),
        inputs_used=["model_implied_value", "market_implied_value", "dispersion"],
        warnings=[],
    )


# ---------------------------------------------------------------------------
# Q7 — convergence, and the verdict that ends the sentence
# ---------------------------------------------------------------------------


def classify_thesis_convergence(
    reads: EconomyReads, gap: MarketPricingGap, *, as_of: datetime
) -> tuple[ModelResult, ConvergenceClassification]:
    """Q7: classify agreement across ``[growth, inflation, labor, gap]``.

    Section 16.2 passes **four** signals — the three reads *and the gap itself*.
    ``classify_convergence`` takes them as ``ConvergenceInputs(signals=[...])``.

    The gap participates because it is the claim under test: three models can
    agree with each other while disagreeing with the thesis, and a convergence
    verdict that ignored the gap would call that agreement.

    **The gap has to be adapted, and the adaptation is not optional.**
    ``ConvergenceInputs.signals`` is typed ``list[ModelResult]`` and
    ``classify_convergence`` reads ``.value`` off each element. Measured:
    ``MarketPricingGap`` is a plain ``BaseModel`` whose ``value`` is the
    ``raw_gap`` float — **it is not a ``ModelResult``**. So §16.2's sample, which
    passes the gap directly, would fail pydantic validation at this line — a
    **tenth** divergence between the sample and the shipped contracts, and one
    with real content: the gap's direction is ``raw_gap``'s sign, which is
    exactly what ``_direction`` computes from a numeric ``value``, so adapting
    it is not a workaround. It is how the gap's sign enters a classifier that
    reads values.

    The adapter is built **here**, locally, rather than by making
    ``MarketPricingGap`` a ``ModelResult`` (which would give a
    ``canonical_policy_gap`` result a ``confidence``, an ``interpretation`` and
    a ``warnings`` list it has no basis for) or by widening
    ``ConvergenceInputs`` (which would push the narrowing to every other caller).

    Returns the ``ModelResult`` (for the warning collector and the thesis's
    ``warnings``) **and** the parsed ``ConvergenceClassification``. The verdict
    is parsed here rather than trusted as a string because
    ``ConvergenceClassification`` inherits from ``str``: a bare ``"HIGH"`` has
    the same hash as the member, passes a membership test, and then dies on
    ``.value`` somewhere else. Parsing at the boundary turns a typo into a raise
    at the point that produced it.
    """
    signals: list[ModelResult] = [*reads.as_sequence(), _as_signal(gap, as_of=as_of)]
    result = classify_convergence(ConvergenceInputs(signals=signals))
    value = result.value
    if not isinstance(value, dict):
        raise TypeError(
            f"classify_convergence returned a {type(value).__name__} for value; "
            f"the documented shape is a dict carrying 'classification'."
        )
    verdict_raw = value.get("classification")
    if verdict_raw is None:
        raise KeyError(
            "classify_convergence's value dict has no 'classification' key. This "
            "module reads the verdict by that name; if the key was renamed the "
            "caller must be updated with it, not defaulted past."
        )
    return result, ConvergenceClassification(verdict_raw)


# ---------------------------------------------------------------------------
# The three gates
# ---------------------------------------------------------------------------


def _q6_decision(gap: MarketPricingGap) -> NoTradeDecision:
    """Q6: the gap is inside the policy rules' own disagreement.

    ``trigger`` and ``evidence`` are both derived from the object being read —
    ``gap`` is passed through as ``evidence``, so nothing is flattened and the
    magnitudes that say *how close* the call was travel with the decision
    (D-068 defect 3).
    """
    return no_trade_thesis(
        reason=(
            f"Gap does not exceed policy-rule dispersion — insufficient "
            f"signal-to-noise ({gap.interpretation})"
        ),
        trigger="gap_below_dispersion",
        gap=gap,
    )


def _q7_decision(assessment: object) -> NoTradeDecision:
    """Q7: growth and inflation point opposite ways (Module 12 dual mandate).

    The reason carries the **census** rather than just the verdict, because
    "CONFLICTED" alone does not say how many models were read — and an
    opposition between two readable signals is a different fact from an
    opposition involving one nobody could read (D-066's whole point).
    """
    if not isinstance(assessment, ConfirmationSignalAssessment):
        raise TypeError(
            f"_q7_decision needs the ConfirmationSignalAssessment that "
            f"build_confirmation_signals returns, got "
            f"{type(assessment).__name__}. Passing anything else would make the "
            f"census unavailable and the reason a bare verdict."
        )
    return no_trade_thesis(
        reason=(
            f"Growth/inflation/policy signals directly contradict — Module 12 "
            f"dual-mandate-tension pattern ({assessment.disagreeing} contradicting, "
            f"{assessment.agreeing} confirming, {assessment.neutral} neutral)"
        ),
        trigger="conflicted_signals",
        evidence=assessment,
    )


def _q8_decision(assessment: InvalidationAssessment) -> NoTradeDecision:
    """Q8: no evidence-based falsifier could be derived (D-063 / O-68).

    The gate exists because Section 15's LTCM lesson makes an unstated falsifier
    a disqualifying condition, and ``InvalidationAssessment.text`` is
    **deliberately empty** when ``identified`` is False — so a caller that
    ignored this gate would hand ``TradeIdea`` an empty string and be refused by
    the very validator that exists for it. This branch turns that refusal into a
    no-trade, which is what Section 16.3 says it should be.

    ``assessment.reason`` (rather than ``.text``, which is empty by
    construction) is what reaches ``reason``; the whole assessment reaches
    ``evidence`` because ``unreadable`` and ``neutral`` are the only record of
    *why* nothing was identified.
    """
    return no_trade_thesis(
        reason=(f"No evidence-based invalidation condition could be derived — {assessment.reason}"),
        trigger="no_falsifier",
        evidence=assessment,
    )


# ---------------------------------------------------------------------------
# The builder
# ---------------------------------------------------------------------------


def build_us_macro_thesis(
    reads: EconomyReads,
    taylor_inputs: TaylorRuleInputs,
    first_difference_inputs: FirstDifferenceInputs,
    *,
    thesis_type: ThesisType,
    universe: ProductionUniverse,
    curve_short_tenor: str | None = None,
    curve_long_tenor: str | None = None,
    short_yield: float,
    short_tenor_term_premium: float | None = None,
    as_of: datetime | None = None,
    unattributed: Sequence[UnattributedWarning] = (),
    catalyst_calendar: Sequence[str] | None = None,
) -> MacroThesis:
    """Section 7.2 / 16.2: build the US macro thesis, or stand down.

    Parameters
    ----------
    reads:
        Q1's three economy reads. See ``EconomyReads`` for why this is a
        parameter rather than something this function computes from a snapshot.
    taylor_inputs / first_difference_inputs:
        Q5's rule inputs. Two records rather than one because
        ``first_difference_rule`` reads a **change** and ``TaylorRuleInputs``
        reads **levels**; a single record would have to carry both and let each
        rule ignore half of it (D-037's inert-input class).
    thesis_type:
        Which analytical family the thesis expresses (Section 22.3.1's seven).
        **Required, and not derived.** A gap does not name a thesis type: the
        same policy-path gap can be expressed as an outright, a curve trade or
        an FX carry, and choosing is part of the analysis.
    universe:
        The production execution universe (Section 22.12). Passed to
        ``select_instrument`` so a view whose cleanest expression is outside it
        returns ``ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT`` rather than a
        substitute instrument.
    short_yield / short_tenor_term_premium:
        Q3/Q4's market read. ``None`` for the premium is the honest input when
        no term-premium model is wired, and ``derive_market_implied_policy_path``
        discloses the contamination on its own result (Section 22.5).
    unattributed:
        Section 21.4's blocked inputs and Section 5.4's flags, forwarded to
        ``collect_all_warnings``. Forwarded because a blocked input is the
        **absence** of data — no enumeration of results can reveal it — so a
        builder that did not forward the caller's list would make the Section
        21.4 obligation *look* discharged while nothing was passed (**O-81** /
        **O-82**).
    catalyst_calendar:
        Override for the forward calendar. ``None`` (the default) **fetches**.
        An explicit ``[]`` means "the caller has a calendar and it is empty",
        which is a different claim from "nothing was fetched" — and the two must
        not be the same input (D-066's defect 4 in the parameter position).

    Returns
    -------
    MacroThesis
        A live thesis (``status=DRAFT``), or a no-trade thesis
        (``status=WATCH``) if Q6, Q7 or Q8 stood the sentence down.

    Notes
    -----
    ``status`` is ``DRAFT`` on a live thesis and ``WATCH`` on a no-trade, and
    neither is promotable here: Section 7.2 step 10 requires a human to promote,
    and no auto-promotion exists before the Phase 5+ risk gate (**O-86** records
    that ``WATCH`` alone cannot distinguish "no edge" from "waiting" — the
    ``trigger`` field and the labelled warning are what make it legible).
    """
    stamp = as_of or utc_now()

    # -- Q1..Q5, in a straight line. Nothing below can be reordered without
    #    breaking the gate ordering, which is why there are no early returns
    #    before the gates.
    gap, rules, ensemble, market_path = build_policy_gap(
        taylor_inputs,
        first_difference_inputs,
        short_yield=short_yield,
        short_tenor_term_premium=short_tenor_term_premium,
    )

    # -- Q6. THE SIGNIFICANCE TEST reads the published gap's own verdict, not a
    #    recomputation of the same predicate.
    if not gap.is_meaningful:
        decision = _q6_decision(gap)
        return _render(
            decision,
            reads=reads,
            gap=gap,
            rules=rules,
            ensemble=ensemble,
            market_path=market_path,
            as_of=stamp,
            unattributed=unattributed,
            stamp=stamp,
        )

    # -- Q7.
    convergence_result, convergence = classify_thesis_convergence(reads, gap, as_of=stamp)
    signals = build_confirmation_signals(reads.growth, reads.inflation, reads.labor, gap)
    if convergence is ConvergenceClassification.CONFLICTED:
        decision = _q7_decision(signals)
        return _render(
            decision,
            reads=reads,
            gap=gap,
            rules=rules,
            ensemble=ensemble,
            market_path=market_path,
            as_of=stamp,
            unattributed=unattributed,
            stamp=stamp,
            convergence=convergence,
            convergence_result=convergence_result,
            signals=signals,
        )

    # -- Q8.
    invalidation = derive_invalidation_conditions(reads.growth, reads.inflation, reads.labor)
    if not invalidation.identified:
        decision = _q8_decision(invalidation)
        return _render(
            decision,
            reads=reads,
            gap=gap,
            rules=rules,
            ensemble=ensemble,
            market_path=market_path,
            as_of=stamp,
            unattributed=unattributed,
            stamp=stamp,
            convergence=convergence,
            convergence_result=convergence_result,
            signals=signals,
            invalidation=invalidation,
        )

    # -- Q9. The instrument. `gap_direction` comes from the gap's own sign and
    #    `thesis_type` from the caller; neither is guessed.
    selection = select_instrument(
        InstrumentSelectionInputs(
            thesis_type=thesis_type,
            gap_direction=_gap_direction(gap),
            curve_short_tenor=curve_short_tenor,
            curve_long_tenor=curve_long_tenor,
        ),
        universe,
    )
    instrument = _instrument_from(selection)

    # -- Q10. Scenarios. Safe to call here: Q6 has already refused a
    #    sub-noise-floor gap, so the function's raise path is unreachable and
    #    only the `[]` path (a verdict that cannot carry a thesis) remains.
    scenarios = build_scenario_distribution(gap, convergence)

    # -- Q11..Q14. Sizing is Phase-1 prose; the falsifier is the assessment's
    #    own `text`, which is non-empty precisely because Q8 passed.
    catalysts, calendar_warnings = _resolve_catalysts(catalyst_calendar, stamp)

    warning_summary: WarningSummary = collect_all_warnings(
        *reads.as_sequence(),
        convergence_result,
        ensemble,
        market_path,
        selection,
        unattributed=unattributed,
    )
    warnings = _thesis_warnings(
        warning_summary,
        reads=reads,
        signals=signals,
        invalidation=invalidation,
        calendar_warnings=calendar_warnings,
        convergence=convergence,
    )

    return MacroThesis(
        thesis_id=new_thesis_id(as_of=stamp),
        country="us",
        created_at=stamp,
        as_of=stamp,
        regime=_regime_view(reads.growth, reads.inflation),
        growth_view={"output_gap": _scalar(reads.growth)},
        inflation_view={"breadth_score": _scalar(reads.inflation)},
        policy_view=policy_view_dict(rules, ensemble),
        market_pricing_gap=gap,
        confirmation_signals=list(signals.signals),
        convergence_classification=convergence,
        trade_idea=TradeIdea(
            instrument=instrument,
            direction=_direction_for(selection, gap),
            timeframe="6-12 months",
            sizing_logic=SIZING_LOGIC_PHASE_1,
            stop_or_invalidation=invalidation.text,
            catalysts=list(catalysts),
        ),
        scenario_distribution=scenarios,
        status=ThesisStatus.DRAFT,
        warnings=warnings,
        independent_source_families=_family_count(reads),
    )


# ---------------------------------------------------------------------------
# Rendering a stand-down — the one place the trigger reaches the thesis
# ---------------------------------------------------------------------------


def _render(
    decision: NoTradeDecision,
    *,
    reads: EconomyReads,
    gap: MarketPricingGap,
    rules: RuleTrio,
    ensemble: ModelResult,
    market_path: ModelResult,
    as_of: datetime,
    unattributed: Sequence[UnattributedWarning],
    stamp: datetime,
    convergence: ConvergenceClassification | None = None,
    signals: ConfirmationSignalAssessment | None = None,
    invalidation: InvalidationAssessment | None = None,
    selection: ModelResult | None = None,
    convergence_result: ModelResult | None = None,
) -> MacroThesis:
    """Render a stand-down into a ``MacroThesis`` with whatever partial view exists.

    Section 16.4's comment — *"other fields populated with whatever partial view
    was formed, so a human can still see WHY the system concluded no-trade"* —
    is the requirement, and it is the reason ``render_no_trade_thesis`` takes
    ``**thesis_fields``. This function supplies them.

    **A stand-down carries every warning a live thesis would.** Measured while
    testing this module: an earlier version of this function published only the
    trigger line, which dropped the model warnings *and* Section 22.5's
    market-path contamination disclosure from every stand-down — so a reader
    asking "why no trade?" lost the very disclosures that make the inputs
    interpretable, and the live check measured ``contaminated=0`` on a run where
    the contaminated branch was definitely taken. Section 7.2 step 9's "never
    drop them" is not conditioned on the thesis being live, and a stand-down is
    exactly when a reader most needs to see how weak the inputs were. The
    collector therefore runs on **both** paths, over whatever results exist.

    The three fields that were **not** formed are supplied as their *emptiest
    truthful* values rather than as invented content:

    - ``scenario_distribution=[]`` — a distribution over a trade that must not
      exist is the false confidence Module 12.2 exists to prevent, and
      ``build_scenario_distribution`` refuses such a gap anyway;
    - ``confirmation_signals=[]`` — omitted rather than faked, because a signal
      list built for a thesis nobody is making would read as corroboration. On
      the Q7 path the signals **were** built, so they are carried;
    - ``convergence_classification=NO_SIGNAL`` when Q6 fired before Q7 ran, so
      the field records *"never classified"* rather than a verdict that was not
      reached.

    ``warnings`` is **not** passed to ``render_no_trade_thesis`` — that function
    owns the field and refuses it, correctly, because it must write the trigger
    line *first* so a reader meets the stand-down before the caveats it is made
    of. D-068's contract is respected rather than worked around: the thesis is
    rendered first, and the collected warnings are then **appended behind** the
    trigger line. Measured: passing ``warnings=`` raises, so the fix is an
    append, not an argument.
    """
    collected: list[ModelResult] = [*reads.as_sequence(), ensemble, market_path]
    if convergence_result is not None:
        collected.append(convergence_result)
    if selection is not None:
        collected.append(selection)
    summary = collect_all_warnings(*collected, unattributed=unattributed)
    warnings = _thesis_warnings(
        summary,
        reads=reads,
        signals=signals,
        invalidation=invalidation,
        calendar_warnings=(),
        convergence=convergence,
    )

    signal_list = list(signals.signals) if signals is not None else []
    thesis = render_no_trade_thesis(
        decision,
        thesis_id=new_thesis_id(as_of=stamp),
        country="us",
        created_at=stamp,
        as_of=stamp,
        regime=_regime_view(reads.growth, reads.inflation),
        growth_view={"output_gap": _scalar(reads.growth)},
        inflation_view={"breadth_score": _scalar(reads.inflation)},
        policy_view=policy_view_dict(rules, ensemble),
        market_pricing_gap=gap,
        confirmation_signals=signal_list,
        convergence_classification=convergence or ConvergenceClassification.NO_SIGNAL,
        scenario_distribution=[],
        independent_source_families=_family_count(reads),
    )

    # The trigger line is first (D-068 owns it); the model warnings and the
    # census disclosures follow it. Never a substitution — an append — so the
    # stand-down remains legible as a stand-down.
    if warnings:
        thesis.warnings = [*thesis.warnings, *warnings]
    return thesis


# ---------------------------------------------------------------------------
# Small readers — each one a named refusal rather than a bare cast
# ---------------------------------------------------------------------------


def _scalar(result: ModelResult) -> object:
    """A model's value, abbreviated for a thesis view field.

    A ``dict[str, object]`` field takes anything, so this deliberately does
    **not** narrow to a float: ``inflation_breadth_score`` publishes a dict and
    a reader of §7.3's example would not expect it. What it does do is keep the
    value rather than stringify it, so a consumer can compute on it.
    """
    return result.value


def _gap_direction(gap: MarketPricingGap) -> GapDirection:
    """The gap's sign as ``GapDirection``.

    ``raw_gap = model_implied - market_implied``. Positive means the model's
    prescribed rate is **above** the market's, i.e. the thesis expects the
    traded variable to move **up** relative to what is priced — which is
    ``GapDirection.POSITIVE``'s documented meaning.

    ``raw_gap == 0.0`` is refused rather than defaulted. Q6 has already
    established ``abs(raw_gap) > dispersion``, and dispersion is non-negative,
    so a zero gap cannot reach this line — which means reaching it is a
    contradiction between the gate and the object, and the honest response to a
    contradiction is a raise, not a coin-flip default.
    """
    if gap.raw_gap > 0:
        return GapDirection.POSITIVE
    if gap.raw_gap < 0:
        return GapDirection.NEGATIVE
    raise ValueError(
        f"gap.raw_gap is exactly 0.0 while gap.is_meaningful is "
        f"{gap.is_meaningful!r} (dispersion={gap.dispersion!r}). Q6 lets a gap "
        f"through only when abs(raw_gap) > dispersion, so an exactly-zero gap "
        f"means the published verdict and the published magnitude disagree. "
        f"There is no direction to express and defaulting to one would invent a "
        f"sign."
    )


def _instrument_from(selection: ModelResult) -> str:
    """The instrument string ``select_instrument`` chose, on either output shape.

    **This function has to handle two shapes, and that is a measured property of
    ``select_instrument``, not a defensive habit.** The module's own
    ``_selection_value`` declares *"select_instrument always returns a dict
    value"* and raises otherwise — but measured, that is true only of the
    **executable** routes. The sentinel routes build their result through
    ``_sentinel_result``, which sets ``value`` to the **bare string**
    (``ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT`` or
    ``BLOCKED_MULTI_COUNTRY_NOT_BUILT``). So ``select_instrument`` publishes two
    value shapes, and the sibling helper's own claim is wrong about one of them.

    Two shapes is not a defect to be papered over here — a sentinel is not a
    selection, and giving it a dict with an empty ``instrument`` key would make
    "no production instrument exists" indistinguishable from "an instrument whose
    name is blank". But the consequence is real: **every consumer of
    ``select_instrument`` must branch on the shape**, and a consumer that assumes
    the dict (as ``_selection_value`` does) raises on the one answer the
    analytical boundary exists to produce. Recorded as **O-87**.

    Both sentinels are passed through **unchanged** — that is Section 22.12's
    boundary rule. A builder that "helpfully" substituted a production
    instrument would violate it in the one place it matters most.
    """
    value = selection.value
    if isinstance(value, str):
        if not value:
            raise ValueError(
                "select_instrument returned an EMPTY string for value. The two "
                "sentinels are both non-empty by definition, so an empty string is "
                "not a sentinel — it is a missing instrument, which must not be "
                "published as a TradeIdea.instrument."
            )
        return value

    if not isinstance(value, dict):
        raise TypeError(
            f"select_instrument returned a {type(value).__name__} for value; the "
            f"documented shapes are a dict (an executable route) or a non-empty "
            f"sentinel string (a refused route)."
        )
    instrument = value.get("instrument")
    if not isinstance(instrument, str) or not instrument:
        raise KeyError(
            f"select_instrument's value dict has no non-empty 'instrument' string "
            f"(got {instrument!r}). Every executable route publishes one, and the "
            f"refused routes publish a bare string rather than a dict; a dict "
            f"without a name means the output shape changed."
        )
    return instrument


def _direction_for(selection: ModelResult, gap: MarketPricingGap) -> str:
    """The trade direction, from the selector's own output where it publishes one.

    Section 16.2's rule (``"long" if gap.raw_gap < 0 else "short"``) is written
    for a **rates** instrument and is only correct there: a model rate below the
    market's implies the rate falls, and a faller is a receiver — long. For a
    curve trade, an FX carry or an equity expression the gap's sign does not
    name the direction of the instrument.

    Measured: ``select_instrument``'s **executable** routes publish ``direction``
    inside their value dict, already resolved against ``GapDirection``. The
    **sentinel** routes publish a bare string instead (see ``_instrument_from``),
    so there is no direction to read and the fallback applies — which is correct:
    a thesis with no production instrument has no direction either, and the
    schema's ``"n/a"`` default is not applied here because the two stand-down
    *reasons* (no instrument vs no direction) are different (D-066's shape).

    So the selector's value is used when it is one of the schema's two live
    directions, and the sample's rule is the fallback otherwise. The fallback is
    kept rather than removed because it is the *documented* behaviour for the
    rates family it was written for, and dropping it would change the output on
    the one path the sample got right.
    """
    value = selection.value
    published = value.get("direction") if isinstance(value, dict) else None
    if published in ("long", "short"):
        return str(published)
    return "long" if gap.raw_gap < 0 else "short"


def _regime_view(growth: ModelResult, inflation: ModelResult) -> dict[str, object]:
    """§7.3's ``regime`` field: the state and its confidence.

    Section 16.2's Q1 calls ``classify_regime_rule_based`` as the **fourth**
    read. That function needs ``RegimeInputs`` — output gap, inflation level,
    inflation momentum, unemployment gap — a fourth plumbing requirement of the
    same kind ``EconomyReads`` documents, and inventing it here would be the
    same defect one field over.

    So the regime view is assembled from the reads **the caller supplied**, and
    it is deliberately *thin*: ``state`` is absent, because a state is what a
    classifier produces and there is no classifier in this call. What it
    carries is the two axes the classifier would read, so a consumer sees the
    inputs and knows the verdict was not computed rather than reading a
    fabricated one.

    This is the ``NOT_COMPUTED`` disclosure pattern (D-043/D-045): the honest
    answer to "what is the regime" when no classifier ran is **the inputs, and
    the statement that no verdict was formed**.
    """
    return {
        "state": None,
        "confidence": 0.0,
        "note": (
            "Not classified: classify_regime_rule_based needs RegimeInputs "
            "(output gap, inflation level, inflation momentum, unemployment gap) "
            "and this builder was not given that record. The two axes below are "
            "the reads it would have used."
        ),
        "output_gap": _scalar(growth),
        "inflation_breadth": _scalar(inflation),
    }


def _family_count(reads: EconomyReads) -> int:
    """Section 6.6b's independent-source-family count over the three reads.

    ``None`` is **not** a family, and neither is a repeated one: a count that
    treated "unknown" as a value would report two families for two unlabelled
    models, which is exactly the D-046 over-count. Measured live:
    ``output_gap``'s ``source_family`` is ``None``, so the honest count on a
    default snapshot is ``0`` — and ``0`` is the disclosure that the
    independence question cannot be answered yet, where ``3`` would be a claim.
    """
    families = {
        family for result in reads.as_sequence() if (family := result.source_family) is not None
    }
    return len(families)


# ---------------------------------------------------------------------------
# Catalysts — the one failure this builder catches
# ---------------------------------------------------------------------------


def _resolve_catalysts(
    override: Sequence[str] | None, stamp: datetime
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Q14's forward calendar, and the warnings its retrieval produced.

    Returns ``(catalysts, warnings)``.

    ``CatalystSourceError`` is caught **here and only here**. It is the one
    documented failure that means *"the thesis is fine, the calendar is not
    reachable"*, and D-065 raises it precisely so an unreachable calendar cannot
    read as an empty one. Swallowing it silently would restore that defect;
    letting it propagate would make a network blip destroy the thesis. So it is
    caught, the unreachability is **published as a warning**, and the thesis
    continues with an empty calendar that is *labelled*.

    An explicit ``override`` — including ``[]`` — skips the fetch entirely, so a
    caller with its own calendar never triggers a network call, and an empty
    list is honoured as the caller's own statement rather than overwritten by a
    fetch.
    """
    if override is not None:
        return tuple(override), ()

    try:
        return tuple(next_catalyst_calendar(as_of=stamp.date())), ()
    except CatalystSourceError as exc:
        return (), (
            "CATALYST CALENDAR UNREACHABLE: no official source answered "
            f"({exc}). The thesis is otherwise complete; the forward calendar is "
            "EMPTY because nothing could be fetched, NOT because no catalyst is "
            "scheduled.",
        )


# ---------------------------------------------------------------------------
# Warnings — §7.2 step 9's union, plus the convergence-specific caveats
# ---------------------------------------------------------------------------


def _thesis_warnings(
    summary: WarningSummary,
    *,
    reads: EconomyReads,
    signals: object,
    invalidation: InvalidationAssessment | None,
    calendar_warnings: tuple[str, ...],
    convergence: ConvergenceClassification | None,
) -> list[str]:
    """§7.2 step 9: every model's warnings, plus the convergence caveats.

    The union is ``summary.warnings`` — Section 16.4's de-duplicated list,
    **verbatim** (D-067 preserved it for exactly this reason). To it this
    function appends the three disclosures a flat model-warning list cannot
    carry, each **prefix-labelled** so a reader can tell a model's own warning
    from a thesis-level addition without parsing prose:

    1. the **unreadable/neutral census** from Q7 — D-066's second half, which
       the published ``list[ConfirmationSignal]`` has no slot for;
    2. the **invalidation census** from Q8 — how many falsifiers vs how many
       inputs could not be read;
    3. the **catalyst unreachability**, when it happened.

    The census lines are added **only when the census is non-empty**. A line
    reading "0 unreadable, 3 neutral" on a clean run is noise, and noise in a
    warnings list is how a real warning gets skimmed past (D-054's silence
    lesson, inverted).
    """
    warnings = list(summary.warnings)

    if isinstance(signals, ConfirmationSignalAssessment) and signals.unreadable:
        names = ", ".join(entry.source_model for entry in signals.unreadable)
        warnings.append(
            f"[confirmation signals] {len(signals.unreadable)} of "
            f"{len(signals.signals)} inputs could not be read as a direction "
            f"({names}); a neutral entry is an ABSENT reading, not agreement"
        )

    if invalidation is not None and invalidation.unreadable:
        names = ", ".join(entry.model_name for entry in invalidation.unreadable)
        warnings.append(
            f"[invalidation] {len(invalidation.unreadable)} of 3 inputs could not "
            f"be read ({names}), so the stated falsifiers are drawn from a partial "
            f"set — an unreadable input is not a satisfied condition"
        )

    if invalidation is not None and invalidation.neutral:
        warnings.append(
            f"[invalidation] {len(invalidation.neutral)} input(s) carry no "
            f"direction: {'; '.join(invalidation.neutral)}"
        )

    warnings.extend(calendar_warnings)

    if convergence is ConvergenceClassification.NO_SIGNAL:
        warnings.append(
            "[convergence] NO_SIGNAL: no input carried a direction, so agreement "
            "was never established. A thesis resting on an unclassified "
            "convergence has no corroboration to cite."
        )

    _ = reads  # the reads reach `warnings` through `summary`, not directly
    return warnings
