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

from macro_engine.config import get_settings
from macro_engine.data_layer.fed_funds_futures_client import FedFundsFuturesCurve
from macro_engine.models.contracts import ModelResult, utc_now
from macro_engine.models.convergence import ConvergenceInputs, classify_convergence
from macro_engine.models.instrument_selection import (
    GapDirection,
    InstrumentSelectionInputs,
    ThesisType,
    select_instrument,
)
from macro_engine.models.policy_rules import (
    BoeContemporaneousInputs,
    BoeFirstDifferenceInputs,
    BoeForwardLookingInputs,
    FirstDifferenceInputs,
    MarketPricingGap,
    PolicyRuleResult,
    TaylorRuleInputs,
    balanced_approach_rule,
    boe_contemporaneous_taylor_rule,
    boe_first_difference_rule,
    boe_forward_looking_taylor_rule,
    canonical_policy_gap,
    derive_market_implied_policy_path,
    first_difference_rule,
    policy_rule_ensemble,
    taylor_rule,
)
from macro_engine.models.probability import scenario_distribution_status
from macro_engine.portfolio.risk_budget import (
    ProposedPosition,
    RiskBudgetTarget,
    ThesisPositionInputs,
    translate_thesis_to_position,
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
from macro_engine.thesis_layer.scenarios import (
    build_scenario_distribution,
    scenario_probabilities_are_calibrated,
)
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

#: The Phase-1 thesis horizon sentence. A module constant for the SAME reason
#: its neighbour above is one (audit finding B-1, 2026-09-29): it was a bare
#: ``"6-12 months"`` literal at the ``TradeIdea`` call site, which is exactly the
#: re-typed-string drift the ``SIZING_LOGIC_PHASE_1`` comment warns about — and
#: the two sit two lines apart in the same call, so the standard was applied to
#: one field and missed on its neighbour. Named here so a guard test can assert
#: the call site binds the NAME (``test_the_horizon_is_used_not_re_typed``).
#:
#: ⚠️ **This is a disclosure-bearing STRING, not a structured horizon, and that
#: is a known open gap — not something this constant fixes.** O-75 records that
#: "a stated thesis-timeframe convention … does not exist yet", and §16.4's spec
#: writes a free-text ``timeframe``. Measured: ``TradeIdea.timeframe`` is a bare
#: ``str`` defaulting to ``"n/a"``, and the only consumers
#: (``portfolio/risk_budget.py:2932/2938``) INTERPOLATE it into prose and copy it
#: onto ``PositionSize.timeframe`` — nothing parses it into a numeric holding
#: period. So a backtest or a sizing model that wants a horizon in days has no
#: machine-readable value to read; it must be given a real field (and a
#: convention) first. Promoting the literal to a constant removes the *drift*
#: defect and makes the gap single-sourced; it does NOT invent the convention.
THESIS_TIMEFRAME_PHASE_1 = "6-12 months"

#: The default thesis-id prefix, so an id is legible in a log without a lookup.
#: **Superseded as the actual prefix** by the ``country`` argument to
#: :func:`new_thesis_id` (§22.3): a UK thesis must not carry a ``us-`` prefix or
#: the one field an operator greps by would mislabel every non-US thesis. Kept
#: as the documented DEFAULT for the ``country="us"`` case, not as the prefix
#: itself, so there is one source for the "us" spelling rather than two.
THESIS_ID_PREFIX = "us"


def new_thesis_id(*, as_of: datetime, country: str = THESIS_ID_PREFIX) -> str:
    """A fresh thesis id: ``<country>-YYYY-MM-DD-<8 hex>``.

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

    ``country`` (§22.3) is the id's first segment. It is a **country code**, not
    the literal ``"us"``: a gb thesis whose id began ``us-`` would be the single
    most misleading field on the record, because the id is what an operator
    pages by. The caller passes the same ``country`` the thesis itself carries,
    so the two cannot drift.
    """
    return f"{country}-{as_of:%Y-%m-%d}-{uuid.uuid4().hex[:8]}"


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

    The transforms live in the caller, not here
    -------------------------------------------
    ``api_layer/orchestration.py`` is the plumbing layer for this signature. It
    turns ``MacroDataSnapshot`` fields into each model's input record, including
    the unit conventions, the yoy/mom transforms and the per-series release-lag
    handling (``_yoy_percent``, ``_mom_percent``, ``_trailing_percentile``,
    ``_claims_4wk_change``, ``_inflation_leg``, ``_labor_leg``,
    ``_output_gap_change``). An earlier version of this docstring said that layer
    *"does not exist yet"*; it exists, and leaving that sentence in place made the
    remaining wiring gap read as a known-and-accepted limitation rather than as
    outstanding work (DEF-006).

    What the builder keeps out of scope — and why it still matters
    -------------------------------------------------------------
    This function takes its inputs as parameters rather than reaching into the
    snapshot for three reasons that remain correct:

    1. **Reproducibility.** A builder that invented its own transforms would
       produce a thesis whose numbers cannot be reproduced from a stated input.
    2. **The ``NOT_COMPUTED`` pattern.** A caller that cannot supply a record
       still gets a fully-formed, fully-disclosed thesis; the disclosure names
       what was not computed instead of guessing (D-043/D-045).
    3. **Signature stability.** Adding a third rule record to the signature is a
       visible, reviewable change; silently deriving one would not be.

    The open item is therefore **not** this signature. It is that
    ``orchestration.py`` feeds the **policy axis**, the regime read, Module
    7.1's national-accounts divergence **and** Module 8's curve reads (slope and
    breakevens) — and not yet an FCI or a risk input. Measured by
    ``tools/reachability_audit.py``: 59 of the 77 model functions in
    ``models/`` have no pipeline caller, of which 34 are live-checked in
    ``scripts/`` and 25 have no caller of any kind.

    **That 59 is not 59 Phase 0-3 obligations, and the distinction matters.**
    ``AGENTS.md`` line 1787's Module-to-Phase-to-Endpoint table assigns the
    Risk/Portfolio modules (``historical_var``, ``expected_shortfall``,
    ``parametric_var``, ``realized_vol_simple``, ``portfolio_volatility_*``,
    ``marginal_risk_contributions``) the endpoint **"(Phase 4+)"**, and §9.2/§9.3
    defer ``compute_risk_parity_weights`` and ``translate_thesis_to_position``
    to Phase 4. §16.2's own algorithm marks Q11 *"Phase 1: human-determined;
    Phase 4+: fractional_kelly"* and Q12 *"Phase 4+ hook"*. So wiring the risk
    axis now would not close a Phase 0-3 gap — it would build a Phase 4 layer
    early, which is a different decision from this one.

    Extending the orchestrator to the curve axis is **done**; the FCI and risk
    axes are the remaining candidates, and the risk half is Phase 4 by the
    spec's own endpoint assignment. See ``docs/DEFECTS_2026-09-19.md``.

    **Neither** a snapshot-only caller **nor** a fully-wired one is silently
    preferred.

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


@dataclass(frozen=True)
class BoeRuleInputs:
    """The three Bank of England rule-input records, as one bundle (Section 22.3).

    Why a bundle rather than three loose fields on ``ThesisInputs``
    --------------------------------------------------------------
    The US path carries ``taylor_inputs`` and ``first_difference_inputs`` — TWO
    records, because the Fed's *balanced-approach* rule reuses the contemporaneous
    Taylor record. The BoE's three published rules (Annex 1, Nov 2025 MPR) each
    take a DISTINCT record: the contemporaneous Taylor-type rule reads energy and
    non-energy CPI **deviations**; the forward-looking Taylor-type rule reads a
    five-quarter-ahead inflation LEVEL and output gap; the first-difference rule
    reads a three-quarter-ahead inflation level and a GDP **growth rate**. There
    is no way to express that as two records without one standing in for two
    different regressor sets — the inert/wrong-input shape the two Fed records
    exist to avoid.

    The bundle lives HERE rather than in ``api_layer`` because the builder is the
    consumer and the dependency runs ``api_layer -> thesis_layer``, so a bundle
    declared a layer up could not be imported by its own consumer.
    """

    contemporaneous: BoeContemporaneousInputs
    forward_looking: BoeForwardLookingInputs
    first_difference: BoeFirstDifferenceInputs


#: The three policy rules, in §7.3's order. Named so the two functions that
#: unpack the tuple cannot disagree about the order.
RuleTrio = tuple[PolicyRuleResult, PolicyRuleResult, PolicyRuleResult]


def build_policy_gap(
    taylor_inputs: TaylorRuleInputs | None,
    first_difference_inputs: FirstDifferenceInputs | None,
    *,
    short_yield: float,
    short_tenor_term_premium: float | None,
    futures_curve: FedFundsFuturesCurve | None = None,
    country: str = "us",
    boe_inputs: BoeRuleInputs | None = None,
) -> tuple[MarketPricingGap, RuleTrio, ModelResult, ModelResult]:
    """Q3-Q5: the three rules, their dispersion, and the canonical gap.

    Returns ``(gap, rules, ensemble, market_path)`` — **four** values, not the
    three an earlier version of this line listed. ``market_path`` is the
    ``derive_market_implied_policy_path`` result, and it is returned rather than
    discarded because it carries the Section 22.5 term-premium contamination
    warnings that reach the thesis through ``collect_all_warnings``.

    The rules are returned alongside the ensemble because
    ``MacroThesis.policy_view`` is §7.3's documented dict of
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

    ``futures_curve`` is the Section 22.5 replacement path, threaded through from
    the caller. ``None`` (the default) keeps the Phase 1-4 term-premium proxy, so
    every existing call is unaffected (the extension is additive). When a curve
    **is** supplied, ``derive_market_implied_policy_path`` prefers it and
    publishes the market's own near futures-implied rate instead of the proxy —
    and the returned ``market_path`` is then the futures result, so the
    contamination warnings are the futures function's, not the proxy's.
    """
    # -- Q3-Q5's three rules, DISPATCHED BY COUNTRY (Section 22.3). The Fed's
    #    trio and the BoE's trio are different functions reading different input
    #    records; a country's thesis must run its OWN central bank's rules or the
    #    gap is meaningless. The dispatch is explicit (not a try/except or a
    #    getattr) so a country with no rule set is a loud refusal, and so a new
    #    country cannot silently fall through to the Fed's rules.
    if country == "gb":
        if boe_inputs is None:
            raise TypeError(
                "build_policy_gap(country='gb') requires boe_inputs; the Bank of "
                "England's three published rules take three distinct input "
                "records and none of them can be derived from the Fed's. A gb "
                "thesis with no BoE inputs has no policy leg (Section 22.3)."
            )
        if taylor_inputs is not None or first_difference_inputs is not None:
            raise TypeError(
                "build_policy_gap(country='gb') was given the Fed's rule inputs "
                "as well as the BoE's. A thesis carries ONE country's records "
                "(Section 22.3); passing both would let the wrong central bank's "
                "rules run silently."
            )
        taylor = boe_contemporaneous_taylor_rule(boe_inputs.contemporaneous)
        balanced = boe_forward_looking_taylor_rule(boe_inputs.forward_looking)
        first_diff = boe_first_difference_rule(boe_inputs.first_difference)
    elif country == "us":
        if taylor_inputs is None or first_difference_inputs is None:
            raise TypeError(
                "build_policy_gap(country='us') requires taylor_inputs and "
                "first_difference_inputs; the Fed's rules cannot be derived from "
                "the BoE's records (Section 22.3)."
            )
        if boe_inputs is not None:
            raise TypeError(
                "build_policy_gap(country='us') was given boe_inputs; a thesis "
                "carries ONE country's records (Section 22.3)."
            )
        taylor = taylor_rule(taylor_inputs)
        balanced = balanced_approach_rule(taylor_inputs)
        first_diff = first_difference_rule(first_difference_inputs)
    else:
        raise ValueError(
            f"build_policy_gap has no rule set for country {country!r}; "
            f"implemented: ['gb', 'us'] (Section 22.3). A country without its own "
            f"central-bank rules must not borrow another's."
        )

    ensemble = policy_rule_ensemble(taylor, balanced, first_diff)
    market_path = derive_market_implied_policy_path(
        short_yield=short_yield,
        short_tenor_term_premium=short_tenor_term_premium,
        futures_curve=futures_curve,
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


def _gap_direction_sentence(raw_gap: float) -> str:
    """The gap's sign, in words, for the §3 `direction` field.

    A named function rather than an inline conditional for the same reason
    `_as_signal` is one: the sign convention here is load-bearing and easy to
    invert. A **positive** ``raw_gap`` means the model-implied path is above the
    market-implied path — policy is more restrictive than priced — which is the
    opposite of the naive reading of "the gap is positive, so policy is loose".

    Note the field's own semantics (Section 3): `direction` describes what the
    value MEANS, not the sign of the number. For a gap these coincide, but the
    sentence is what a reader consumes, so it is written explicitly rather than
    left to be re-derived.

    The exact-zero case is separated because "flat" is a third state, not a
    rounding of either direction. The comparison is on ``!= 0`` rather than on
    ``> 0`` / ``< 0`` with a fallthrough, so a zero cannot be mislabelled by
    whichever branch's `else` caught it (the D-040 class of defect).
    """
    if raw_gap == 0:
        return "flat: model-implied and market-implied paths coincide"
    if raw_gap > 0:
        return "policy is more restrictive than priced (model path above market path)"
    return "policy is less restrictive than priced (model path below market path)"


def _as_signal(gap: MarketPricingGap, *, as_of: datetime, confidence: float) -> ModelResult:
    """The gap, as the ``ModelResult`` that ``classify_convergence`` can read.

    A named function rather than an inline construction because three things
    about it are load-bearing and each one is a defect if forgotten:

    * ``value=gap.raw_gap`` — the **signed** gap, not ``abs`` and not
      ``is_meaningful``. ``_direction`` reads the sign, so passing the magnitude
      would make every gap point the same way and the classifier would see the
      thesis confirm itself unconditionally.
    * ``model_name="market_pricing_gap"`` — the label a reader sees in the
      per-signal direction table. A bare default would put the class name there.
    * ``confidence`` is **passed in**, never invented here. It is the confidence
      of the ``policy_rule_ensemble`` result that produced this gap — the
      evidence actually behind the number — so the adapter re-shapes a result
      without claiming a confidence of its own. Two earlier forms were both
      wrong: copying ``gap.is_meaningful`` (a *significance verdict*, not a
      measurement confidence — the D-046 "scored by its own subject matter"
      failure) and writing the literal ``1.0`` (Section 22.8's forbidden
      self-asserted confidence, and a flat contradiction of this docstring,
      which already said the confidence was ``compute_confidence``'s to
      produce). The value now originates from ``compute_confidence`` inside
      ``policy_rule_ensemble`` and is threaded through unchanged.

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
        confidence=confidence,
        interpretation=gap.interpretation,
        context=(
            f"Adapted from MarketPricingGap for convergence classification: the "
            f"signed raw_gap ({gap.raw_gap:+.4f}pp) is the direction, against a "
            f"rule dispersion of {gap.dispersion:.4f}pp."
        ),
        inputs_used=["model_implied_value", "market_implied_value", "dispersion"],
        warnings=[],
        # --- Section 3/4: the reasoning object, populated -------------------
        unit="percentage points",
        direction=_gap_direction_sentence(gap.raw_gap),
        assumptions=[
            "The model-implied policy path (the median of the three rules, "
            "Section 22.4) is the correct benchmark for 'what policy SHOULD be'. A "
            "reader who rejects the rules' structural assumptions rejects the "
            "sign of this gap with them.",
            "The market-implied path, term-premium-adjusted, represents what is "
            "PRICED. If the adjustment is wrong the gap measures the adjustment "
            "error rather than a policy surprise.",
            "Dispersion across the three rules is treated as the noise floor for "
            "significance (Section 16.2 Q6). Three rules over one target is a "
            "narrow disagreement set, so the floor is likely understated.",
        ],
        data_provenance=[
            "model_implied_value — median of the three policy rules, computed "
            "upstream by build_policy_gap",
            "market_implied_value — derive_market_implied_policy_path, "
            "term-premium-adjusted, from the nominal curve in the snapshot",
            "dispersion — cross-rule disagreement, from the same three rule results",
        ],
        limitations=[
            "THIS IS A SIGNIFICANCE VERDICT CARRIER, NOT A MEASUREMENT. The "
            "`confidence` on this result is a carrier value for "
            "`count_independent_families` and is NOT a measurement confidence: a "
            "gap carries a significance verdict (is_meaningful), not a "
            "measurement error, and converting one into the other would be the "
            "D-046 'scored by its own subject matter' failure.",
            "The gap is EX-POST in the sense that both sides are read from the "
            "same curve at the same instant. It is not a forecast; it is a "
            "difference of two opinions about the same future path.",
            "The dispersion floor is computed from three rules that share a "
            "target and a functional form. Genuine model uncertainty — the "
            "possibility that the correct reaction function is not in the family "
            "at all — is NOT in the dispersion and therefore NOT in the floor.",
        ],
        decision_relevance=(
            "Section 16.2's Q6 (the significance test that stands a thesis down) "
            "and Q7's convergence input. The SIGN drives `_direction`, so this "
            "result decides which way the thesis would trade if it traded; the "
            "magnitude versus dispersion decides whether it trades at all."
        ),
        decision_prohibition=[
            "MUST NOT be read as a measured disagreement with an error band. A "
            "gap of +0.26pp against a 0.86pp dispersion is NOT 'policy is 26bp "
            "too tight' — it is 'the rules and the market differ by an amount "
            "smaller than the rules differ from each other' (Section 16.2 Q6).",
            "MUST NOT be consumed without `dispersion`. A bare raw_gap has no "
            "scale: the same +0.26pp is decisive under a 0.05pp dispersion and "
            "meaningless under a 0.86pp one.",
            "MUST NOT be used to select an instrument or size a position on its "
            "own: the Q6 verdict is a precondition, and when it is not "
            "meaningful the pipeline stands down rather than sizing "
            "(Section 16.3).",
        ],
    )


# ---------------------------------------------------------------------------
# Q7 — convergence, and the verdict that ends the sentence
# ---------------------------------------------------------------------------


def classify_thesis_convergence(
    reads: EconomyReads,
    gap: MarketPricingGap,
    *,
    ensemble: ModelResult,
    as_of: datetime,
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
    signals: list[ModelResult] = [
        *reads.as_sequence(),
        _as_signal(gap, as_of=as_of, confidence=ensemble.confidence),
    ]
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
    taylor_inputs: TaylorRuleInputs | None,
    first_difference_inputs: FirstDifferenceInputs | None,
    *,
    thesis_type: ThesisType,
    universe: ProductionUniverse,
    country: str = "us",
    boe_inputs: BoeRuleInputs | None = None,
    curve_short_tenor: str | None = None,
    curve_long_tenor: str | None = None,
    short_yield: float,
    short_tenor_term_premium: float | None = None,
    futures_curve: FedFundsFuturesCurve | None = None,
    as_of: datetime | None = None,
    unattributed: Sequence[UnattributedWarning] = (),
    catalyst_calendar: Sequence[str] | None = None,
    regime: ModelResult | None = None,
    risk_budget_target: RiskBudgetTarget | None = None,
) -> MacroThesis:
    """Section 7.2 / 16.2: build the US macro thesis, or stand down.

    Parameters
    ----------
    reads:
        Q1's three economy reads. See ``EconomyReads`` for why this is a
        parameter rather than something this function computes from a snapshot.
    taylor_inputs / first_difference_inputs:
        Q5's rule inputs for a **US** thesis. Two records rather than one because
        ``first_difference_rule`` reads a **change** and ``TaylorRuleInputs``
        reads **levels**; a single record would have to carry both and let each
        rule ignore half of it (D-037's inert-input class).
    country:
        The country whose central-bank rules this thesis runs (Section 22.3).
        ``"us"`` (default) runs the Fed's trio from ``taylor_inputs`` /
        ``first_difference_inputs``; ``"gb"`` runs the Bank of England's three
        published rules from ``boe_inputs``. The two sets are mutually exclusive
        — passing the other country's records is refused rather than ignored.
    boe_inputs:
        The Bank of England's three rule-input records, required when
        ``country="gb"`` and refused otherwise. See :class:`BoeRuleInputs`.
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
    futures_curve:
        Section 22.5's replacement input, forwarded to ``build_policy_gap`` and
        on to ``derive_market_implied_policy_path``. ``None`` (the default) is
        the honest input for a caller that has not fetched a curve, and the
        Phase 1-4 term-premium **proxy** is then what runs — which is the
        shipped behaviour, so every existing caller is unaffected. When a curve
        is supplied the market leg becomes the market's own near futures-implied
        rate, and the proxy's contamination warnings do not apply.
        The default is ``None`` rather than a fetch so that the **decision to
        use the futures source is explicit at the call site**, not an implicit
        network read inside a builder (D-137's declaration-by-design; §21.0
        rule 3 forbids inventing the curve here).
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
    regime:
        Q1's **fourth** read: ``classify_regime_rule_based``'s result, computed
        by the orchestration layer (``_regime_leg``) because it needs
        ``RegimeInputs`` — output gap, inflation level, inflation momentum and
        unemployment gap — which only a snapshot holder can derive. ``None``
        (the default) is the honest input for a caller that has no regime
        record, and ``_regime_view`` then publishes its ``NOT_COMPUTED`` shape
        (D-043/D-045) rather than a guessed state. The default pipeline supplies
        it; before this parameter existed, ``regime.state`` was ``None`` on
        every thesis ever produced (``docs/DEFECTS_2026-09-19.md``, DEF-003).
    risk_budget_target:
        Section 17.4's **risk axis** — this instrument's budgeted share of total
        portfolio risk, if the caller has a book to allocate against. ``None``
        (the default) means **no book was supplied**, and it is the default for
        a measured reason rather than for convenience: ``AGENTS.md`` §21.1
        defines five source types for every input, and a **portfolio holding is
        none of them** — there is no series, no derivation, no config leaf and
        no manual path for "what the book currently holds". A builder that
        invented a book would violate §21.0 rule 3, so the absence is a
        supported input with a *disclosed* meaning rather than a guessed one.

        When it **is** supplied, Section 17.4's feedback rule runs: the thesis
        is translated into a proposed size via
        ``portfolio/risk_budget.py``'s ``translate_thesis_to_position`` (D-072)
        and, if the proposal clips to near-zero against ``RiskLimits``, the
        thesis is **demoted** — a position that cannot be sized meaningfully is
        not actionable regardless of conviction (the LTCM lesson, encoded).

        The demotion is **not** a refusal and **not** a silent edit: the status
        moves and the reason is published as a warning, because a status field
        that changed without a stated cause is the failure direction O-86 names.

        It is also **not reached** on the shipped pipeline. Measured on today's
        data: all seven ``ThesisType`` members stand down at Q6/Q7/Q8, so no
        thesis reaches the sizing path at all — this parameter is inert until a
        thesis survives every gate. That is a fact about the world, printed by
        ``scripts/live_risk_axis_check.py`` rather than assumed here.

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
        futures_curve=futures_curve,
        country=country,
        boe_inputs=boe_inputs,
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
            country=country,
            ensemble=ensemble,
            market_path=market_path,
            as_of=stamp,
            unattributed=unattributed,
            stamp=stamp,
            regime=regime,
        )

    # -- Q7.
    convergence_result, convergence = classify_thesis_convergence(
        reads, gap, ensemble=ensemble, as_of=stamp
    )
    signals = build_confirmation_signals(reads.growth, reads.inflation, reads.labor, gap)
    if convergence is ConvergenceClassification.CONFLICTED:
        decision = _q7_decision(signals)
        return _render(
            decision,
            reads=reads,
            gap=gap,
            rules=rules,
            country=country,
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
            country=country,
            ensemble=ensemble,
            market_path=market_path,
            as_of=stamp,
            unattributed=unattributed,
            stamp=stamp,
            convergence=convergence,
            convergence_result=convergence_result,
            signals=signals,
            invalidation=invalidation,
            regime=regime,
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
        country=country,
    )
    instrument = _instrument_from(selection)

    # -- Q10. Scenarios. Safe to call here: Q6 has already refused a
    #    sub-noise-floor gap, so the function's raise path is unreachable and
    #    only the `[]` path (a verdict that cannot carry a thesis) remains.
    scenarios = build_scenario_distribution(gap, convergence)
    # Section 25: stamp whether the distribution may drive sizing. Read from the
    # config's own calibration_status leaves rather than asserted here, so
    # promoting the probabilities to a calibrated status lifts the prohibition
    # with no edit to this file.
    scenario_status = scenario_distribution_status(
        scenarios, probabilities_are_calibrated=scenario_probabilities_are_calibrated()
    )

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

    # -- Q12 (the risk half). Section 17.4's feedback rule. ---------------
    #
    # WHAT THIS BLOCK IS FOR, AND WHAT IT DELIBERATELY DOES NOT DO
    # -----------------------------------------------------------
    # Section 17.4 is the only rule in the specification that carries a
    # *risk-layer* finding back into the thesis LIFECYCLE:
    #
    #   "A thesis whose sizing_logic output (once Phase 4+ auto-sizing exists)
    #    clips to near-zero against RiskLimits ... should have its status
    #    automatically demoted ... a thesis that can't be sized meaningfully
    #    isn't actionable, regardless of conviction."
    #
    # Three things about that sentence drive the code below:
    #
    # 1. **The sizing is not computed here.** ``translate_thesis_to_position``
    #    (D-072) owns it, and ``_risk_axis`` **calls** it rather than
    #    re-deriving anything. Re-implementing the Kelly/limit arithmetic in the
    #    builder would create a second definition of the size, and the two would
    #    drift.
    #
    # 2. **The thesis must exist BEFORE it can be sized**, so the object is
    #    constructed first and the risk axis is applied to it. An earlier draft
    #    of this hook tried to size from the builder's local variables before
    #    construction and had to declare four parameters it could not consume —
    #    which is the declared-unconsumed shape this project keeps finding
    #    (D-045/D-046/D-048, O-53). Constructing first removes the temptation
    #    and lets the axis read the **published** object rather than a
    #    reconstruction of it.
    #
    # 3. **``None`` is the shipped state, and it is disclosed, not silent.**
    #    ``risk_budget_target`` is ``None`` unless the caller supplies a book.
    #    In that case the risk axis DID NOT RUN, and the thesis says so — a
    #    reader must be able to tell "we sized it and it is fine" from "we did
    #    not size it", which is the distinction ``translate_thesis_to_position``
    #    itself makes for a missing budget.
    #
    # The demotion target is ``WATCH``, and Section 17.4's own wording says
    # ``CANDIDATE`` -> ``WATCH``. Measured: **nothing in the shipped system
    # produces ``CANDIDATE``** — the builder emits ``DRAFT`` and every
    # stand-down emits ``WATCH``. So the rule as literally written describes a
    # transition this system cannot be in. The choice made here is to demote
    # **to ``WATCH``** (the status that means "not actionable", which is the
    # property Section 17.4 protects) rather than to invent a ``CANDIDATE``
    # producer for it to be demoted *from* — that would be manufacturing a
    # lifecycle stage to satisfy a sentence. Recorded as **O-96**.
    thesis = MacroThesis(
        thesis_id=new_thesis_id(as_of=stamp, country=country),
        country=country,
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
            timeframe=THESIS_TIMEFRAME_PHASE_1,
            sizing_logic=SIZING_LOGIC_PHASE_1,
            stop_or_invalidation=invalidation.text,
            catalysts=list(catalysts),
        ),
        scenario_distribution=scenarios,
        scenario_distribution_status=scenario_status,
        status=ThesisStatus.DRAFT,
        warnings=warnings,
        independent_source_families=_family_count(reads),
    )
    return _apply_risk_axis(thesis, risk_budget_target)


# ---------------------------------------------------------------------------
# Rendering a stand-down — the one place the trigger reaches the thesis
# ---------------------------------------------------------------------------


def _render(
    decision: NoTradeDecision,
    *,
    reads: EconomyReads,
    gap: MarketPricingGap,
    rules: RuleTrio,
    country: str,
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
    regime: ModelResult | None = None,
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

    ``country`` (§22.3) is threaded rather than defaulted so a stand-down carries
    the same country code its live counterpart does — the id prefix and the
    ``country`` field are both built from it, so a UK stand-down cannot be
    labelled ``us`` by a forgotten argument.
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
        thesis_id=new_thesis_id(as_of=stamp, country=country),
        country=country,
        created_at=stamp,
        as_of=stamp,
        regime=_regime_view(reads.growth, reads.inflation, regime),
        growth_view={"output_gap": _scalar(reads.growth)},
        inflation_view={"breadth_score": _scalar(reads.inflation)},
        policy_view=policy_view_dict(rules, ensemble),
        market_pricing_gap=gap,
        confirmation_signals=signal_list,
        convergence_classification=convergence or ConvergenceClassification.NO_SIGNAL,
        scenario_distribution=[],
        scenario_distribution_status="empty_no_trade",
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


def _regime_view(
    growth: ModelResult,
    inflation: ModelResult,
    regime: ModelResult | None = None,
) -> dict[str, object]:
    """§7.3's ``regime`` field: the state and its confidence.

    Section 16.2's Q1 calls ``classify_regime_rule_based`` as the **fourth**
    read. That function needs ``RegimeInputs`` — output gap, inflation level,
    inflation momentum, unemployment gap — a fourth plumbing requirement of the
    same kind ``EconomyReads`` documents, and this builder does not invent it.

    **Two paths, and the caller chooses.** When ``regime`` is supplied (the
    orchestrator now supplies it — ``_regime_leg``), its state, confidence and
    interpretation are published along with the two bucketed axes and the
    corroboration verdict, so a reader can see *which* axis chose the label and
    whether the two slack measures agreed. When ``regime`` is ``None``, the
    view falls back to the ``NOT_COMPUTED`` shape (D-043/D-045): the two axes
    the classifier would have read, and an explicit statement that no verdict
    was formed.

    The fallback is retained deliberately rather than deleted once the
    orchestrator was wired. A caller holding a snapshot and no regime inputs
    still gets a fully-formed, fully-disclosed thesis, and the note says which
    case applied instead of the builder guessing a state. What changed is that
    the *default* pipeline no longer takes the fallback path — before
    ``_regime_leg`` existed, ``state: None`` was on every thesis ever produced
    (``docs/DEFECTS_2026-09-19.md``, DEF-003).
    """
    if regime is not None:
        value = regime.value
        if isinstance(value, dict):
            state = value.get("state")
            return {
                "state": state,
                "confidence": regime.confidence,
                "note": regime.interpretation,
                "growth_axis": value.get("growth_axis"),
                "inflation_axis": value.get("inflation_axis"),
                "slack_corroborated": value.get("slack_corroborated"),
                "output_gap": _scalar(growth),
                "inflation_breadth": _scalar(inflation),
            }
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


# ---------------------------------------------------------------------------
# Section 17.4 — the risk axis, and the one place a risk finding moves a status
# ---------------------------------------------------------------------------


def _apply_risk_axis(thesis: MacroThesis, target: RiskBudgetTarget | None) -> MacroThesis:
    """Section 17.4: does this thesis survive being sized? Returns the thesis.

    Runs **after** the thesis is constructed, which is what makes it honest: the
    rule turns on the *proposed size*, and a size can only be proposed for an
    object that exists. An earlier draft evaluated the rule from the builder's
    local variables, before construction, and had to accept four parameters it
    could not consume — the declared-unconsumed shape this project has found
    eight times (D-045/D-046/D-048, O-53). Constructing first removes it.

    The sizing itself is ``translate_thesis_to_position``'s (D-072) and is
    **called**, never re-derived. That function has four gates of its own, and a
    builder that reproduced any of them would be a second definition of the same
    predicate — precisely the defect §16.2's own sample commits, where
    ``is_meaningful`` is computed twice from different inputs.

    What it does with the result
    ----------------------------
    * **``refused_*``** — the translation declined to size. The thesis keeps
      ``DRAFT`` and the refusal is published. A refusal is **not** a demotion:
      Section 17.4 demotes a thesis whose size is *too small*, and a translation
      that declined for a different stated reason has said something else. The
      two must not collapse into one status or the reason stops travelling.
    * **Sized, above the bound** — ``DRAFT``, with the proposal's own reason
      attached so the size is legible next to the thesis that produced it.
    * **Sized, at or below ``risk.thesis_demotion_fraction``** — **demoted to
      ``WATCH``**, because Section 17.4's LTCM lesson is that a correct idea you
      cannot survive-size is not yet a trade.

    ``target is None`` short-circuits to a **disclosed absence** rather than a
    silent pass. ``AGENTS.md`` §21.1 defines five source types for every input
    and a portfolio holding is **none of them** — no series, no derivation, no
    config leaf, no manual path. So the builder cannot obtain a book, and
    inventing one would violate §21.0 rule 3. The warning says the check did not
    run, because "unchecked" and "checked and clear" must not read alike.
    """
    if target is None:
        return thesis.model_copy(
            update={
                "warnings": [
                    *thesis.warnings,
                    "[Q12 risk] No portfolio-level risk budget was supplied, so "
                    "Section 17.4's sizing feedback DID NOT RUN. A DRAFT here "
                    "means 'not yet sized against a book', NOT 'sized and "
                    "verified' — §21.1 defines no source for portfolio holdings, "
                    "so a caller holding a book must pass `risk_budget_target`.",
                ]
            }
        )

    translation = translate_thesis_to_position(
        ThesisPositionInputs(thesis=thesis, risk_budget_target=target)
    )
    value = translation.value
    # A TYPED raise rather than a bare `assert`, for the reason every other
    # narrowing in this module is one: an assert is stripped under `-O`, so the
    # guard would vanish and `ProposedPosition.model_validate` would report the
    # wrong thing — a schema complaint about a non-dict, instead of
    # "translate_thesis_to_position changed shape". MEASURED 2026-10-06: this was
    # the module's ONLY bare assert, against six typed raises elsewhere.
    if not isinstance(value, dict):
        raise TypeError(
            f"translate_thesis_to_position returned a {type(value).__name__} for "
            f"value; ProposedPosition is built from the documented dict, so a "
            f"non-dict means the function changed shape and this call site was "
            f"not updated."
        )
    proposal = ProposedPosition.model_validate(value)

    demotion = get_settings().risk.thesis_demotion_fraction
    if proposal.outcome.startswith("refused_"):
        return thesis.model_copy(
            update={
                "warnings": [
                    *thesis.warnings,
                    f"[Q12 risk] The risk budget was supplied but the position "
                    f"could not be sized: {proposal.outcome} — {proposal.reason} "
                    f"This is a REFUSAL, not a demotion: Section 17.4 demotes a "
                    f"thesis whose size is too small, and this is a different "
                    f"finding.",
                ]
            }
        )

    if proposal.fraction_of_capital <= demotion:
        return thesis.model_copy(
            update={
                "status": ThesisStatus.WATCH,
                "warnings": [
                    *thesis.warnings,
                    f"[Q12 risk] DEMOTED to WATCH by Section 17.4: the proposed "
                    f"notional is {proposal.fraction_of_capital:.4f} of capital, "
                    f"at or below the {demotion:.4f} near-zero bound (binding "
                    f"constraint: {proposal.binding_constraint!r}). A thesis "
                    f"that cannot be sized meaningfully is not actionable "
                    f"regardless of conviction — the LTCM lesson, encoded. The "
                    f"view may be right; it is not yet a trade.",
                ],
            }
        )

    return thesis.model_copy(
        update={
            "warnings": [
                *thesis.warnings,
                f"[Q12 risk] Sized by Section 17.4: proposed "
                f"{proposal.fraction_of_capital:.4f} of capital in "
                f"{proposal.instrument} (binding constraint: "
                f"{proposal.binding_constraint!r}, permitted risk contribution: "
                f"{proposal.permitted_risk_contribution:.4f}). {proposal.reason}",
            ]
        }
    )
