"""Module 17 — position sizing under hard risk constraints (Tier 3).

Four functions, four questions, all of the form *"should the book be this
big?"* and none of them placing an order:

* ``evaluate_drawdown_rules`` (17.3, Section 6.6c) — the pre-committed
  de-risking ladder. Silent until a drawdown trips it.
* ``check_rebalancing_drift`` (17.3, Section 15.18) — has the book drifted off
  its *risk* budget?
* ``volatility_target_scaling`` (17.2, Section 20.13) — scale exposure so the
  book's expected vol equals a target, then clip against hard limits.
* ``apply_fractional_kelly`` (17.3, Sections 20.14/22.6) — size a position from
  the **full scenario distribution** by expected-log-growth growth-optimal
  Kelly, divided by the mandatory fractional divisor, then clipped.

**Three failure directions, all of them fail-safe-looking.** 17.3's ladder fails
toward *silence*: a 100x unit error made it unable to fire at all, so a
de-risking rule reported "no rule triggered" at a 90% drawdown (D-054). 17.2's
scaler fails toward *false confidence*: its only enforced limit is an upper
bound that cannot bind when vol rises, so it reports ``clipped=False`` while
cutting a book by 75% (D-056). 17.3's Kelly sizer fails toward *prudence*: a
100x unit error in its payoff input produces a **smaller** number that slips
under the cap unnoticed, and a binding cap collapses every confident view to one
published size (D-057). None is visible in the arithmetic. All three are visible
in the **direction the mechanism fails**.

Module 17.3 — pre-committed mechanical de-risking (Tier 3).

Section 6.6c defines this function and Section 17.3 restates the rationale.
The economic content is deliberately thin, and that is the point: it is a
**pre-commitment device**, not a judgement. A trader mid-drawdown who believes
their thesis is still correct is exactly the person Module 17.3 says cannot be
trusted to size down, so the rule is written in advance and applied
mechanically.

Four specification defects, one live config defect
--------------------------------------------------
The function is eleven lines of arithmetic. It shipped with **four specification
defects plus one defect in the config it was supposed to read**, and the config
defect had made the function **unable to fire at all**:

1. **Unit mismatch between the spec and its own config — a 100x error.** Section
   6.6c writes ``DrawdownRule(threshold_pct=0.10)``, a **fraction**. The shipped
   ``config/settings.yaml`` writes ``{drawdown_pct: 10.0}``, a **percent**. A
   function reading one and comparing against the other is off by 100x. The
   direction of the error matters enormously and was **not** what was assumed:
   the predicted failure was "every tier fires, always 100%", and the actual
   failure is the opposite — **no tier can ever fire**, so the de-risking rule
   is permanently silent and reports "no risk-reduction rule triggered" at a
   90% drawdown. A safety mechanism that fails toward inaction is the worst
   available failure mode. Resolved by normalising to a **fraction** at the
   boundary (see ``_tiers``) and bounding it, because a fraction's bounds make
   the error detectable and a percent's do not.
2. **``risk_reduction_pct`` had no bounds.** ``float`` with no validator, so a
   caller-supplied rule could return ``5.0`` ("reduce risk by 500%") or
   ``-1.0`` ("increase risk"), and the function would publish it as a
   de-risking instruction. Now bounded to ``(0, 1]`` as a fraction.
3. **"Rules are evaluated in order; the MOST SEVERE triggered rule wins" is
   self-contradictory prose.** The two clauses cannot both be true, and the
   second governs: the result is **invariant under permutation** of the rule
   list (verified across all 6 permutations of the default set). A reader who
   believed order mattered would write ``sorted(rules)`` or break out of the
   loop early, and both would change the answer. The implementation therefore
   **does not iterate in order** and says so.
4. **``max(triggered, key=risk_reduction_pct)`` is not the same as
   ``max(triggered, key=threshold_pct)`` once rules are caller-supplied.** For
   the default set they agree on every triggered subset, which is exactly why
   nobody would notice — but they diverge on a legal non-monotone rule set
   (verified: ``[(0.10, 0.90), (0.15, 0.20), (0.20, 0.50)]`` at a 17%
   drawdown returns 90% by severity and 20% by threshold). Severity is the
   spec's stated rule, so severity is what is implemented, but the divergence
   is now disclosed because the two are indistinguishable on the default set.
5. **``0.0`` is an ambiguous output.** The "no rule fired" path returns
   ``value=0.0``, and a rule with ``risk_reduction_pct=0.0`` would return the
   same number — so a consumer reading ``value`` alone cannot distinguish
   "nothing triggered" from "a rule fired and prescribed inaction". A
   ``RuleOutcome`` ``Literal`` is published alongside so the two are
   distinguishable **without parsing prose**.

What is deliberately NOT a defect
---------------------------------
**This function is not a classifier, so the base-state rule does not apply.**
D-047 and D-053 both found specifications whose own thresholds made the
uninformative label the modal output. Here the modal output is
``no_action`` — and that is **correct and informative**: the rule exists to be
silent until it is not, and a de-risking rule that fired most of the time would
be a strategy, not a rule. Recording the *non*-application matters, because the
converse habit — applying lesson 5g mechanically — would have produced a
"fix" for a property that is the whole design.
"""

from __future__ import annotations

import math
from typing import Literal, cast, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

from macro_engine.config import get_settings
from macro_engine.models.contracts import (
    ConfidenceInputs,
    ModelResult,
    compute_confidence,
    utc_now,
)
from macro_engine.models.instrument_selection import (
    ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT,
)
from macro_engine.models.probability import ScenarioOutcome
from macro_engine.models.risk import _quadratic_form
from macro_engine.thesis_layer.schemas import (
    NO_PRODUCTION_INSTRUMENT,
    MacroThesis,
    ProductionUniverse,
)

__all__ = [
    "DEFAULT_RISK_PARITY_TOLERANCE",
    "SIGN_OFF_REQUIRED",
    "DrawdownRule",
    "DrawdownState",
    "KellyInputs",
    "KellyPayoffUnit",
    "PositionBinding",
    "PositionTranslationOutcome",
    "ProposedPosition",
    "RebalancingOutcome",
    "RiskBudgetInputs",
    "RiskBudgetTarget",
    "RiskLimits",
    "RuleOutcome",
    "SizingOutcome",
    "ThesisPositionInputs",
    "VolTargetInputs",
    "apply_fractional_kelly",
    "check_rebalancing_drift",
    "compute_risk_parity_weights",
    "evaluate_drawdown_rules",
    "generalized_kelly_fraction",
    "resolve_drawdown_rule",
    "risk_contributions",
    "sample_covariance",
    "stress_correlations",
    "translate_thesis_to_position",
    "volatility_target_scaling",
]


class DrawdownState(BaseModel):
    """A portfolio's position relative to its high-water mark.

    ``drawdown_pct`` is a **fraction**, not a percent: ``0.15`` means a 15%
    drawdown. That follows Section 6.6c and it is the opposite of the suffix's
    usual meaning, which is the unit trap this module exists to close. The
    property is named to match the specification; the *convention* is stated
    here, on the input, where a caller must see it.
    """

    model_config = ConfigDict(extra="forbid")

    high_water_mark: float = Field(
        gt=0.0,
        description=(
            "Peak portfolio value. MUST be > 0. A zero HWM is a division by zero "
            "and a negative one makes the drawdown meaningless, so the bound is "
            "on the input rather than on the derived drawdown."
        ),
    )
    current_value: float = Field(
        description=(
            "Current value. May be NEGATIVE (a wiped-out portfolio carrying "
            "negative equity), which is why the derived drawdown is allowed "
            "above 1.0 while this input is not bounded below."
        ),
    )

    @property
    def drawdown_pct(self) -> float:
        """Fractional drawdown from the high-water mark: ``(hwm - cur) / hwm``.

        Positive means a loss. **Negative is reachable and meaningful** — when
        ``current_value > high_water_mark`` the portfolio is at a new high, and
        the function reports no rule rather than clamping the value to zero.
        Above ``1.0`` means more than 100% has been lost (negative equity).
        """
        return (self.high_water_mark - self.current_value) / self.high_water_mark


class DrawdownRule(BaseModel):
    """One pre-committed de-risking step.

    Both fields are **fractions in ``(0, 1]``**, matching Section 6.6c. The
    upper bounds are load-bearing: without them a rule could prescribe a
    reduction of 500% or a negative reduction (an increase), and the function
    would publish either as a mechanical de-risking instruction.
    """

    model_config = ConfigDict(extra="forbid")

    threshold_pct: float = Field(
        gt=0.0,
        le=1.0,
        description="Drawdown at or above which the rule triggers, as a fraction in (0, 1].",
    )
    risk_reduction_pct: float = Field(
        gt=0.0,
        le=1.0,
        description=(
            "Fraction of risk to remove once triggered, in (0, 1]. "
            "1.0 means stop trading entirely. Bounded because an unbounded "
            "float admits 'reduce risk by 500%' and negative reductions."
        ),
    )


RuleOutcome = Literal["no_action", "reduce_risk", "stop_trading"]


def _tiers() -> list[DrawdownRule]:
    """The configured tiers, converted from the config's percent to fractions.

    **The conversion lives here and nowhere else.** ``config/settings.yaml``
    stores the tiers in percent (``drawdown_pct: 10.0``) because a human
    editing a pre-commitment should read "10%", and every other threshold in
    that file uses the same convention. Section 6.6c's arithmetic uses
    fractions. One boundary, one conversion, one place to test.
    """
    settings = get_settings()
    return [
        DrawdownRule(
            threshold_pct=float(tier.drawdown_pct) / 100.0,
            risk_reduction_pct=float(tier.risk_reduction_pct) / 100.0,
        )
        for tier in settings.risk.drawdown_tiers
    ]


def resolve_drawdown_rule(
    drawdown_pct: float,
    rules: list[DrawdownRule] | None = None,
) -> DrawdownRule | None:
    """The most severe triggered rule, or ``None`` if nothing triggered.

    **No iteration order.** Section 6.6c says rules are "evaluated in order" and
    that "the most severe triggered rule wins", and only the second is true: the
    result is invariant under permutation of the rule list, because the maximum
    over a set does not depend on how the set was traversed. A reader who
    believed the first clause would sort the list first, or break out early,
    and both change the answer on a non-monotone rule set.

    **Severity, not threshold.** The two keys agree on every triggered subset of
    the default tiers, so a test over the defaults cannot tell them apart. They
    diverge as soon as a caller supplies a rule whose reduction is not monotone
    in its threshold — which ``DrawdownRule`` permits. Severity is the stated
    rule and is what is implemented.
    """
    if rules is None:
        rules = _tiers()
    triggered = [rule for rule in rules if drawdown_pct >= rule.threshold_pct]
    if not triggered:
        return None
    return max(triggered, key=lambda rule: rule.risk_reduction_pct)


def evaluate_drawdown_rules(
    state: DrawdownState,
    rules: list[DrawdownRule] | None = None,
) -> ModelResult:
    """Apply the pre-committed de-risking ladder to a drawdown (Module 17.3).

    Section 6.6c's rationale is behavioural rather than quantitative: a trader
    mid-drawdown who is convinced their thesis is still correct is prone to
    doubling down, so the de-risking decision is written down in advance and
    removed from the moment. The function therefore reports an instruction and
    **never applies it** — it is a stateless rule lookup, not a state
    transition, and calling it twice on the same state returns the same answer.

    ``value`` is the **fraction of risk to remove**, in ``[0, 1]``, or ``0.0``
    when nothing triggers. Because ``0.0`` is ambiguous — it is both "nothing
    triggered" and "a rule prescribed no reduction" — the ``outcome`` key
    distinguishes them without parsing prose.

    Confidence is computed from stated facts (Section 22.8), never asserted.
    Measured, against the lattice the stated facts can reach: with the heuristic
    marker set and no independent corroboration it is ``base 0.7 -
    heuristic_penalty 0.2 = 0.5`` — the **midpoint** of the admissible range.
    (A first draft of the accompanying test asserted it was "high relative to
    the project's other models". It is not, and it should not be: the tiers are
    a stated convention rather than a fitted estimate, so the heuristic penalty
    applies and the honest reading is the midpoint, not a claim of accuracy.)
    The remaining uncertainty is real — a stale high-water mark makes the
    drawdown wrong and the function cannot detect it — so a warning names it.
    """
    resolved = rules if rules is not None else _tiers()
    drawdown = state.drawdown_pct

    trigger = resolve_drawdown_rule(drawdown, resolved)

    warnings: list[str] = [
        "This overrides thesis conviction — a thesis believed correct does NOT "
        "exempt a position from this rule. That is the Module 17.3 LTCM lesson "
        "and the reason the rule is mechanical rather than discretionary.",
    ]

    if trigger is None:
        outcome: RuleOutcome = "no_action"
        reduction = 0.0
        # An EMPTY ladder is a legal configuration meaning "never de-risk"
        # (test_an_empty_tier_list_configures_a_silent_ladder), so the
        # no-threshold case must be distinguished from "below the least severe
        # threshold". Reporting the latter for the former would name a threshold
        # that does not exist — and the previous form did precisely that, using
        # ``min(..., default=float("nan"))`` so the message read "the least
        # severe configured threshold is nan%" (D-078).
        least_severe = min((r.threshold_pct for r in resolved), default=None)
        interpretation = f"Drawdown {drawdown:.2%} — no risk-reduction rule triggered. " + (
            f"The least severe configured threshold is {least_severe:.2%}."
            if least_severe is not None
            else "NO TIERS ARE CONFIGURED, so the ladder is empty and this "
            "rule can never fire. That is a deliberate 'never de-risk' "
            "setting only if intended; check risk.drawdown_thresholds."
        )
    else:
        reduction = trigger.risk_reduction_pct
        # `stop_trading` is `risk_reduction_pct == 1.0`: remove all risk. It is
        # distinguished from a merely large reduction because a consumer must
        # not have to compare floats to learn that trading has stopped.
        outcome = "stop_trading" if reduction >= 1.0 else "reduce_risk"
        interpretation = (
            f"Drawdown {drawdown:.2%} exceeds the {trigger.threshold_pct:.2%} "
            f"threshold — reduce risk by {reduction:.1%}"
        )

    if drawdown > 1.0:
        warnings.append(
            f"Drawdown is {drawdown:.1%}, i.e. more than the entire high-water "
            f"mark has been lost — current value is negative. The rule set "
            f"cannot express anything beyond 'stop trading', so this reads like "
            f"any other full stop-out."
        )
    if drawdown < 0.0:
        warnings.append(
            f"Drawdown is {drawdown:.2%} — the portfolio is ABOVE its high-water "
            f"mark, so no rule fires. If the high-water mark is stale rather than "
            f"the portfolio having genuinely peaked, this reading is wrong."
        )
    if rules is not None:
        warnings.append(
            "Caller-supplied rules override the configured ladder. The "
            "pre-commitment argument only holds if these were fixed in advance."
        )

    confidence = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=False,
            # The tiers are a stated convention, not a calibrated estimate, so
            # the heuristic marker is set. This is the honest reading: nothing
            # in this function was fitted to data.
            is_heuristic_not_calibrated=True,
            depends_on_unobservable=False,
        )
    )

    return ModelResult(
        model_name="drawdown_rule_check",
        country="us",
        as_of=utc_now(),
        value={
            "risk_reduction_fraction": round(reduction, 6),
            "outcome": outcome,
            "drawdown_fraction": round(drawdown, 6),
            "triggered_threshold_fraction": (
                round(trigger.threshold_pct, 6) if trigger is not None else None
            ),
            "tiers_evaluated": len(resolved),
            "tiers_triggered": sum(1 for rule in resolved if drawdown >= rule.threshold_pct),
        },
        confidence=confidence,
        interpretation=interpretation,
        context=(
            f"HWM={state.high_water_mark}, current={state.current_value}. "
            f"Pre-committed mechanical rule, NOT a discretionary judgment call — "
            f"apply regardless of thesis conviction."
        ),
        inputs_used=["high_water_mark", "current_value"],
        warnings=warnings,
        data_quality_flags_present=False,
    )


# ---------------------------------------------------------------------------
# Module 17.3 (continued) — risk-budget drift (Section 15.18)
# ---------------------------------------------------------------------------


class RiskBudgetTarget(BaseModel):
    """One instrument's intended share of **portfolio risk** (not of notional).

    The distinction is the entire economic content of Module 17.1 and it is
    invisible in the arithmetic: a 35% *dollar* position in a 5%-vol instrument
    and a 35% dollar position in an 18%-vol instrument are the same number and
    very different risk. The field is therefore named for what it measures and
    the docstring states the basis, because two bare floats cannot reveal a
    notional-vs-risk mismatch.
    """

    model_config = ConfigDict(extra="forbid")

    instrument: str = Field(min_length=1, description="Instrument identifier.")
    target_risk_contribution_pct: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Intended share of TOTAL portfolio risk, as a **fraction** in [0, 1]. "
            "Not a percent and not a notional weight — see the class docstring."
        ),
    )


DriftDirection = Literal["over", "under"]
RebalancingOutcome = Literal["balanced", "rebalance"]


def check_rebalancing_drift(
    current_contributions: dict[str, float],
    targets: list[RiskBudgetTarget],
    drift_threshold_pct: float | None = None,
) -> ModelResult:
    """Detect risk-budget drift — portfolio maintenance, NOT thesis validation.

    Section 15.18's stated purpose is **structural separation**. Module 17.3
    names the failure mode it exists to prevent: conflating *"my portfolio
    drifted from its risk budget"* with *"my thesis is wrong"*. Those are
    different facts with different remedies — the first is fixed by rebalancing,
    the second by exiting — and a book that treats the first as the second
    de-risks on noise, while a book that treats the second as the first holds a
    broken thesis because the position happens to still be on budget. The
    function therefore reports drift and says nothing about validity.

    Every quantity is a **fraction of total portfolio risk**, not a percent and
    not a notional weight.

    Four defects in the specification's version
    -------------------------------------------
    1. **A missing instrument silently becomes a zero contribution.**
       ``current_contributions.get(t.instrument, 0.0)`` makes "not held" and
       "held, contributing no risk" the same input. They are different facts:
       the first is a data gap and the second is a market-neutral position. At a
       20% target the two coincide by accident (both read as 20pp of drift), but
       at a 0% target a **missing** entry reads as perfectly balanced while an
       entry genuinely at zero reads the same — so the function cannot report
       that it never saw an instrument it was told to budget.
    2. **An instrument outside the budget is invisible.** The spec iterates
       ``targets``, so a position carrying risk with no budget line is never
       examined. That is the more dangerous direction: unbudgeted risk is
       exactly what a drift check is for.
    3. **The threshold's unit was unstated.** ``drift_threshold_pct = 0.10`` is
       only sensible as a **fraction** (10%); read as a percent it is a 0.1%
       tolerance, which trips on every real book. This project has three unit
       suffixes in play and ``*_pct`` is the ambiguous one, so the convention is
       stated on the parameter, bounded, and taken from config rather than a
       literal default.
    4. **``>`` makes the threshold non-binding at the boundary.** A drift of
       exactly ``threshold`` does not flag. The specification's arrow points one
       way and the choice is disclosed rather than left to a reader to infer
       from a comparison operator.

    **The base-state rule does not apply** (lesson 5g). Probed over 20 000
    plausible weight wobbles on a real 4-instrument covariance, the check trips
    **10.8%** of the time — so ``balanced`` is modal, as it should be for a
    maintenance check, and the distribution is non-degenerate in both
    directions. Recording the non-application matters because a mechanical
    application of the rule would "fix" a healthy partition.
    """
    settings = get_settings()
    threshold = (
        settings.risk.rebalancing_drift_threshold
        if drift_threshold_pct is None
        else float(drift_threshold_pct)
    )
    if not 0.0 < threshold <= 1.0:
        raise ValueError(
            f"drift_threshold_pct must be a fraction in (0, 1], got {threshold}. "
            f"A value above 1.0 is a percent written into a fraction field."
        )

    drifted: list[dict[str, float | str]] = []
    drifted_instruments: list[str] = []
    seen: set[str] = set()

    for target in targets:
        seen.add(target.instrument)
        actual = current_contributions.get(target.instrument, 0.0)
        signed = actual - target.target_risk_contribution_pct
        if abs(signed) > threshold:
            direction: DriftDirection = "over" if signed > 0 else "under"
            drifted.append(
                {
                    "instrument": target.instrument,
                    "target_risk_contribution": round(target.target_risk_contribution_pct, 6),
                    "actual_risk_contribution": round(actual, 6),
                    "signed_drift": round(signed, 6),
                    "abs_drift": round(abs(signed), 6),
                    "direction": direction,
                }
            )
            drifted_instruments.append(target.instrument)

    # Defect 2: anything contributing risk with no budget line. Reported
    # separately because it is a different repair — the budget is incomplete,
    # not the position out of line.
    unbudgeted = sorted(set(current_contributions) - seen)

    warnings: list[str] = [
        "This is PORTFOLIO risk-budget maintenance, NOT a thesis-validity check. "
        "Rebalancing a drifted position does NOT mean its thesis is wrong, and a "
        "strong thesis does NOT exempt it from rebalancing (Module 17.3).",
    ]
    if unbudgeted:
        warnings.append(
            f"{len(unbudgeted)} instrument(s) contribute risk with NO budget line: "
            f"{unbudgeted}. Unbudgeted risk is not drift — it is a missing budget, "
            f"and it is invisible to a targets-first scan, which is why it is "
            f"reported separately."
        )

    missing = [t.instrument for t in targets if t.instrument not in current_contributions]
    if missing:
        warnings.append(
            f"{len(missing)} budgeted instrument(s) have no current contribution "
            f"and were read as 0.0: {missing}. 'Not held' and 'held at zero risk' "
            f"are indistinguishable on this input — supply an explicit 0.0 to say "
            f"the latter."
        )

    total_actual = sum(current_contributions.values())
    # The tolerance is a config leaf (`risk.rebalancing_contribution_sum_tolerance`)
    # and not the bare `0.01` it shipped as. It is the SAME class of number as
    # `risk.rebalancing_drift` six lines up: a judgement about how far off a
    # *stated* invariant an input may be before it is worth warning about, and
    # therefore a policy number Section 21 keeps out of the function body. A
    # literal here is also invisible to the sweep — `mutation_rebalancing.py`'s
    # M9.3 deletes the whole branch (`if False:`), so a mutant that MOVES the
    # bound survives every test (the D-031 shape: a value read from config and a
    # retyped literal are indistinguishable without a mover).
    sum_tolerance = settings.risk.rebalancing_contribution_sum_tolerance
    if current_contributions and abs(total_actual - 1.0) > sum_tolerance:
        warnings.append(
            f"Current contributions sum to {total_actual:.4f}, not 1.0 (within "
            f"{sum_tolerance}). Risk contributions are SHARES of total portfolio "
            f"risk, so a set that does not sum to 1 is either partial or not shares "
            f"at all (dollar amounts, say) — and against fractional targets every "
            f"dollar figure 'drifts'."
        )

    outcome: RebalancingOutcome = "rebalance" if drifted else "balanced"
    if drifted:
        worst = max(drifted, key=lambda d: float(d["abs_drift"]))
        interpretation = (
            f"{len(drifted)} of {len(targets)} instrument(s) drifted beyond "
            f"{threshold:.1%} of total risk budget; worst is "
            f"{worst['instrument']} at {float(worst['abs_drift']):.1%} "
            f"({worst['direction']})"
        )
    else:
        interpretation = (
            f"No instrument drifted beyond {threshold:.1%} of the risk budget "
            f"across {len(targets)} budgeted instrument(s)"
        )

    confidence = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=bool(missing),
            # The threshold is a stated convention, not a fitted estimate.
            is_heuristic_not_calibrated=True,
            depends_on_unobservable=False,
        )
    )

    return ModelResult(
        model_name="rebalancing_drift_check",
        country="us",
        as_of=utc_now(),
        value={
            "outcome": outcome,
            "drifted": drifted,
            "drifted_instruments": drifted_instruments,
            "unbudgeted_instruments": unbudgeted,
            "missing_instruments": missing,
            "instruments_evaluated": len(targets),
            "instruments_drifted": len(drifted),
            "drift_threshold_fraction": round(threshold, 6),
            "total_current_contribution": round(total_actual, 6),
        },
        confidence=confidence,
        interpretation=interpretation,
        context=(
            "PORTFOLIO risk-budget maintenance. Section 15.18 names the failure "
            "this separation prevents: conflating 'my portfolio drifted' with "
            "'my thesis is wrong'."
        ),
        inputs_used=["current_contributions", "targets"],
        warnings=warnings,
        data_quality_flags_present=bool(missing),
    )


# ---------------------------------------------------------------------------
# Module 17.2 — volatility targeting (Section 20.13)
# ---------------------------------------------------------------------------


class RiskLimits(BaseModel):
    """The hard constraints a sizing model may never override (Section 17.3).

    Section 17.3 declares **five** fields; four ship here. The fifth,
    ``max_drawdown_trigger_pct = 0.10``, is **removed** — see the note below.

    Every field is a **fraction or a multiple**, and the units are stated on the
    field because the specification's own naming does not carry them: three
    fields end in ``_pct`` and hold **fractions** (``0.15`` = 15%). That is the
    same suffix ambiguity that made D-054's ladder permanently silent and left
    D-055's threshold unstated, so the convention is stated here and enforced at
    load time in ``config.py``'s ``_reject_percent_in_fraction_field``.

    Only ``max_leverage`` is consumed by Module 17.2, and that is a real
    limitation rather than a design: a vol target scales *exposure*, and none of
    the other limits is expressible as a function of exposure alone. They are
    declared so the policy object is complete and a future consumer does not
    have to invent a default, and ``volatility_target_scaling`` **reports which
    ones it did not read** rather than implying it enforced them.
    """

    model_config = ConfigDict(extra="forbid")

    max_position_pct_of_portfolio: float = Field(
        gt=0.0,
        le=1.0,
        description=(
            "Largest single position as a FRACTION of the portfolio "
            "(0.15 = 15%). Not consumed by volatility_target_scaling."
        ),
    )
    max_factor_exposure_pct: float = Field(
        gt=0.0,
        le=1.0,
        description=(
            "Largest exposure to any single PCA factor, as a FRACTION "
            "(0.30 = 30%). Not consumed by volatility_target_scaling."
        ),
    )
    max_leverage: float = Field(
        ge=1.0,
        description=(
            "Gross exposure ceiling as a MULTIPLE of capital (3.0 = 3x). The "
            "one limit Module 17.2 enforces."
        ),
    )
    min_liquidity_days_to_unwind: int = Field(
        ge=0,
        description=(
            "Never size beyond what can be unwound in N days. Not consumed by "
            "volatility_target_scaling; it constrains the instrument, not the "
            "book's exposure."
        ),
    )

    @classmethod
    def from_settings(cls) -> RiskLimits:
        """Build from ``config/settings.yaml`` — **the only legitimate source**.

        Section 17.3 writes these as literals in a class body. Section 21
        prohibits literals in models, so the defaults live in the config and
        this constructor is how a caller gets them without inventing numbers.
        """
        risk = get_settings().risk
        return cls(
            max_position_pct_of_portfolio=risk.max_position_fraction,
            max_factor_exposure_pct=risk.max_factor_exposure_fraction,
            max_leverage=risk.max_leverage_multiple,
            min_liquidity_days_to_unwind=risk.min_liquidity_days,
        )

    @property
    def unread_by_vol_targeting(self) -> list[str]:
        """Limits Module 17.2 declares but cannot enforce, named explicitly.

        Section 20.13's body reads ``max_leverage`` and nothing else, while
        Section 17.3's prose says sizing must respect "max position, max factor
        exposure, max drawdown, liquidity, or tail-risk limits". Four of those
        are not reachable from a function whose only inputs are two
        volatilities and an exposure. Publishing them is the difference between
        *"not enforced here"* and *"enforced"*.
        """
        return [
            "max_position_pct_of_portfolio",
            "max_factor_exposure_pct",
            "min_liquidity_days_to_unwind",
        ]

    @property
    def unread_by_position_sizing(self) -> list[str]:
        """Limits Module 17.3's Kelly sizer **does** enforce.

        The mirror of ``unread_by_vol_targeting`` and deliberately **not** a
        filter of it: the two functions enforce **different** limits, so
        reusing one list for both would name the wrong set in one direction.
        Concretely, ``max_position_pct_of_portfolio`` is the **only** limit the
        Kelly sizer reads and the vol scaler does not — so a naive reuse of
        17.2's list would report the one limit 17.3 *does* enforce as
        unenforced, which is exactly the confusion this property exists to
        prevent.

        Position sizing sees **one position**, so the three limits that
        constrain the *book* (factor exposure, leverage) or the *instrument*
        (liquidity) are unreachable from it regardless of how the size is
        derived.
        """
        return [
            "max_factor_exposure_pct",
            "max_leverage",
            "min_liquidity_days_to_unwind",
        ]


class VolTargetInputs(BaseModel):
    """Inputs to Module 17.2's vol-target scaling.

    ``current_portfolio_vol`` and ``target_vol_annualized`` are **annualized
    fractions** (``0.10`` = 10%) on the same basis — the function is a ratio of
    the two, so a shared basis is the whole requirement and a 100x error in one
    but not the other is the only way to make it wrong.

    ``current_gross_exposure`` is the book's **gross exposure as a multiple of
    capital** (``1.0`` = fully invested, ``2.0`` = 2x levered). Scaling it by
    the vol ratio gives the **target multiple**, which is what the leverage
    ceiling binds against. The reading matters and Section 20.13 does not state
    it: under a notional reading, ``gross * scale`` is a dollar amount and
    comparing it to ``max_leverage`` would be comparing a notional to a ratio.
    """

    model_config = ConfigDict(extra="forbid")

    target_vol_annualized: float = Field(
        gt=0.0,
        description=(
            "The vol the book is being managed to, annualized and as a "
            "fraction. MUST be > 0: a zero or negative target is not a target."
        ),
    )
    current_portfolio_vol: float = Field(
        gt=0.0,
        description=(
            "Realised (or estimated) current portfolio vol, annualized and as a "
            "fraction. MUST be > 0 — it is the denominator."
        ),
    )
    current_gross_exposure: float = Field(
        gt=0.0,
        description=(
            "Gross exposure as a MULTIPLE of capital (1.0 = fully invested). "
            "MUST be > 0. Scaling it by the vol ratio yields the target "
            "multiple that the leverage ceiling binds against."
        ),
    )
    limits: RiskLimits


def volatility_target_scaling(inputs: VolTargetInputs) -> ModelResult:
    """Scale exposure toward a vol target, then clip against hard limits.

    Module 17.2 / Section 20.13. The arithmetic is one division: the book is
    scaled by ``target_vol / current_vol`` so that its *expected* vol becomes
    the target. Everything that matters is in the two things the specification
    leaves implicit, both of which are defects rather than omissions.

    **The clip is one-sided, and the specification calls it a constraint.**
    ``final = min(scaled, max_leverage)`` can only ever *reduce* exposure. On
    the de-risking side — the side where a vol target matters — it is inert:
    at a 40% vol spike against a 10% target the scale is 0.25, which is below
    any leverage ceiling, so ``clipped is False`` while the book is being cut
    by 75%. The published ``clipped_by_limits`` therefore means "the ceiling
    bound", not "a limit engaged", and a consumer reading it as the latter
    concludes that no constraint binds in exactly the regime the function
    exists to handle. Both facts are reported separately here.

    **Both breach and cut are attributed.** A book already above its leverage
    ceiling (``gross > max_leverage``) is cut by this function, correctly, but
    the cause is a pre-existing breach rather than a vol signal. Section 20.13
    reports it as an ordinary vol-target adjustment and warns about nothing.

    **The reflexivity warning is Section 20.13's stated economic content** —
    that simultaneous de-risking across funds amplifies the vol spike — and it
    is keyed on the configured scale threshold rather than a literal.

    Confidence is computed from stated facts (Section 22.8). The vol inputs are
    estimates and the threshold is a convention, so the heuristic marker is set
    and the honest reading is the project's midpoint.
    """
    raw_scale = inputs.target_vol_annualized / inputs.current_portfolio_vol
    scaled_exposure = inputs.current_gross_exposure * raw_scale
    ceiling = inputs.limits.max_leverage
    final_exposure = min(scaled_exposure, ceiling)

    clipped = final_exposure < scaled_exposure
    # A book already above the ceiling is a PRE-EXISTING breach: the cut is
    # correct but its cause is not the vol signal, and conflating the two makes
    # the function look like it detected something it did not.
    pre_existing_breach = inputs.current_gross_exposure > ceiling

    settings = get_settings()
    reflexivity_threshold = settings.risk.reflexivity_scale_threshold

    warnings: list[str] = []
    if raw_scale < reflexivity_threshold:
        warnings.append(
            f"Vol-target scale is {raw_scale:.2f}x, below the {reflexivity_threshold:.2f}x "
            f"reflexivity threshold — de-risking into a vol spike is "
            f"industry-reflexive: if many funds run similar rules they sell "
            f"simultaneously and amplify the move they are reacting to "
            f"(Module 17.2)."
        )
    if pre_existing_breach:
        warnings.append(
            f"Gross exposure {inputs.current_gross_exposure:.2f}x was ALREADY above "
            f"the {ceiling:.2f}x ceiling before scaling. The cut below is a "
            f"leverage-breach correction, not a vol-target adjustment — do not "
            f"read it as a signal that vol rose."
        )
    if clipped and not pre_existing_breach:
        warnings.append(
            f"The vol target alone would size the book at "
            f"{scaled_exposure:.2f}x, above the {ceiling:.2f}x ceiling. The hard "
            f"constraint overrides the vol target (Module 17.2's explicit rule)."
        )

    confidence = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=False,
            # The vol estimate is data-dependent but this function's own
            # arithmetic is a stated convention, and the target is a policy
            # number rather than a fitted one.
            is_heuristic_not_calibrated=True,
            depends_on_unobservable=False,
        )
    )

    direction = "de-risk" if raw_scale < 1.0 else "lever up" if raw_scale > 1.0 else "hold"
    interpretation = (
        f"Vol-target scale {raw_scale:.2f}x ({direction}) -> gross exposure {final_exposure:.2f}x"
    )
    if clipped:
        interpretation += f" (CLIPPED at the {ceiling:.2f}x leverage ceiling)"

    return ModelResult(
        model_name="volatility_target_scaling",
        country="us",
        as_of=utc_now(),
        value={
            # Both inputs are bounded `> 0`, so the scale is strictly positive
            # and the direction test below never sees a zero.
            "raw_scale": round(raw_scale, 6),
            "requested_exposure": round(scaled_exposure, 6),
            "final_exposure": round(final_exposure, 6),
            "clipped_by_leverage_ceiling": clipped,
            "pre_existing_leverage_breach": pre_existing_breach,
            # How far the book moved, independent of whether a ceiling bound.
            # Without this a 94% de-risking reports only `clipped=False`.
            "de_risking_fraction": round(max(0.0, 1.0 - raw_scale), 6),
            "direction": direction,
            "leverage_ceiling": round(ceiling, 6),
            "limits_declared_but_not_enforced": inputs.limits.unread_by_vol_targeting,
        },
        confidence=confidence,
        interpretation=interpretation,
        context=(
            "Hard constraints always win over vol-target scaling (Module 17.2). "
            "Only the leverage ceiling is expressible in terms of exposure; the "
            "other declared limits are reported as unenforced rather than "
            "implied. This function NEVER places an order — it reports a size."
        ),
        inputs_used=[
            "target_vol_annualized",
            "current_portfolio_vol",
            "current_gross_exposure",
        ],
        warnings=warnings,
        data_quality_flags_present=False,
    )


# ---------------------------------------------------------------------------
# Module 17.3 — fractional Kelly sizing (Sections 20.14 / 22.6)
# ---------------------------------------------------------------------------

#: Section 22.6 specifies the argmax grid resolution as a literal ``n_grid =
#: 1000``. That literal is **not** accurate enough for this project's published
#: precision, and the shortfall was measured rather than reasoned about: on a
#: binary bet whose closed form is exactly ``0.200000``, a 1000-point grid
#: returns ``0.200200`` — a ``2e-4`` error, **400x** the 6 dp this module
#: rounds to, so the published digits were decided by the search rather than by
#: the mathematics. The resolution therefore lives in ``settings.yaml``
#: (``kelly.grid_points``) and is read via ``KellySettings.search_points``.


#: The units Kelly will **accept**, declared against the producer's vocabulary.
#:
#: Until D-064 this was ``Literal["fraction_of_capital"]`` written out here, while
#: ``models/probability.py`` declared ``PayoffUnit = Literal["bp_pnl_proxy",
#: "fraction_of_capital"]``. The two agreed by inspection only — and, worse, the
#: ``KellyInputs.payoff_unit`` field carried that literal as a **default**.
#: ``KellyInputs(scenarios=distribution, limits=limits)`` — with the producer's
#: ``bp_pnl_proxy`` distribution and **no unit argument at all** — validated, took
#: ``"fraction_of_capital"``, and returned a plausible, smaller,
#: more prudent-looking Kelly fraction computed from basis points. That is D-057's
#: failure **toward silence** reached through the very field D-057 added to stop it,
#: and it is why the defect survived D-057: a test that *supplies* the bp argument
#: passes, and nothing could catch an argument **never supplied**.
#:
#: **Why this is written out rather than computed.** The obvious fix is
#: ``Literal[*get_args(PayoffUnit)]``, and it was tried first: it is correct at
#: runtime — ``get_args`` returns a tuple and the unpacking produces the identical
#: ``Literal`` — but ``mypy --strict`` refuses it with *"Invalid type alias:
#: expression is not a valid type"*, because a type alias must be expressible
#: **statically** and mypy does not evaluate ``get_args`` at type-check time. A
#: computed alias therefore buys nothing: it would not be checked at either call
#: site, which is the only thing an alias is for here.
#:
#: The derivation is enforced instead by
#: ``test_the_consumer_vocabulary_is_derived_from_the_producers``, which asserts
#: ``set(get_args(KellyPayoffUnit)) == set(get_args(PayoffUnit))``. That is a
#: **test rather than a type**, which is weaker in one respect and stronger in
#: another: it fails loudly the day the producer's vocabulary moves, which is
#: exactly the drift the retyped literal could not see.
#:
#: The two members are the producer's whole vocabulary, not the one usable unit.
#: That is deliberate: the field must be able to **name** a unit it then refuses,
#: so the refusal is a decision a reader can find (``M4.4`` in the kelly sweep)
#: rather than a member silently absent from a type (D-057's own lesson, one
#: layer up).
KellyPayoffUnit = Literal["bp_pnl_proxy", "fraction_of_capital"]

#: The **one** unit the Kelly arithmetic can use. Named once, so the validator
#: that refuses the others and the tests that pin the refusal read the same
#: literal rather than two occurrences of ``"fraction_of_capital"`` that can drift.
#:
#: **Annotated, and the annotation is load-bearing.** Without it ``mypy --strict``
#: infers ``str`` and every call site that passes this constant to
#: ``KellyInputs(payoff_unit=...)`` — a ``Literal`` field — is a type error. That
#: is not a nuisance: it is the type system correctly observing that a bare
#: ``str`` module constant could be rebound to anything, which is exactly the
#: drift the "named once" rationale above depends on not happening. Annotating
#: it as the ``Literal`` member makes the constant's *type* the same guarantee
#: its *single definition* is meant to provide.
_KELLY_UNIT: KellyPayoffUnit = "fraction_of_capital"


class KellyInputs(BaseModel):
    """Inputs to Module 17.3's fractional-Kelly sizing.

    ``scenarios`` carries the **full discrete distribution**, not a summary —
    that is the whole point of Section 22.6 (Finding #6): a two-outcome
    approximation cannot represent a three-branch thesis, and a mean/variance
    pair cannot represent a ruinous tail at all.

    **Payoffs must be FRACTIONS OF CAPITAL, not basis points.** Section 22.6
    states this ("payoff_estimate / capital_base — the caller must supply
    payoffs already normalized to a fraction, not a raw dollar/bp figure") and
    it is the single most dangerous requirement in this function, because
    nothing enforces it: the arithmetic is total over any float, so a scenario
    set in basis points returns a plausible, smaller, *more prudent-looking*
    number. Probed, the same set reads ``f* = 1.0000`` as fractions and
    ``f* = 0.1995`` as basis points, and the second slips under the position
    cap that catches the first (D-057's P4).

    Because that cannot be validated from the values alone, ``payoff_unit`` is a
    **required, enumerated declaration**: the caller must state the unit, and
    only ``"fraction_of_capital"`` is accepted. A ``"bp"`` declaration raises
    rather than being silently converted, because a unit the function cannot
    verify is a unit it must not guess.

    This is deliberately stricter than Section 17.3's signature, which takes a
    bare scenario list with no unit at all.
    """

    model_config = ConfigDict(extra="forbid")

    scenarios: list[ScenarioOutcome] = Field(
        min_length=1,
        description=(
            "The full discrete outcome distribution. Probabilities must sum to "
            "1.0 within the configured tolerance (checked by expected_value's "
            "rule, reused rather than restated)."
        ),
    )
    payoff_unit: KellyPayoffUnit = Field(
        description=(
            "The unit of every scenario's ``payoff_estimate``. **Required, and "
            "with no default** — see ``KellyPayoffUnit``. Only "
            "'fraction_of_capital' is accepted: the Kelly arithmetic is a "
            "growth rate over capital, so a bp or dollar payoff is a 100x-class "
            "error (or worse) that no downstream check can detect."
        ),
    )
    limits: RiskLimits

    @model_validator(mode="after")
    def _reject_units_the_arithmetic_cannot_use(self) -> KellyInputs:
        """Refuse a declared unit, then refuse values that cannot be that unit.

        **Two halves, and D-064 is why the first one exists as code.** Until
        D-064 the *type* did the refusing: ``Literal["fraction_of_capital"]``
        admitted one member, so pydantic rejected ``"bp_pnl_proxy"`` before this
        validator ran. That looked like validation and was not — the same
        one-member literal made the field **optional**, so a caller who supplied
        no argument at all was silently given ``"fraction_of_capital"`` for a
        ``bp_pnl_proxy`` distribution. The type was doing two jobs (admitting and
        defaulting) and the second one hid a 100x-class error.

        The two jobs are now separated and each is explicit: the field is
        **required** (no default can be wrong on a caller's behalf), the type
        **names the producer's whole vocabulary** so nothing can be silently
        missing from it, and *this* is where the one unit the arithmetic can
        actually use is enforced — by a named rule a reader can find and a test
        can pin. A member that exists in the type and is refused here is a
        **decision**; a member absent from the type is **nothing**.

        The second half is the value check. The unit declaration is the primary
        guard, but a declaration is a promise and promises get copied: a payoff
        beyond a total loss (``< -1``) cannot be a fraction of capital, and a
        payoff large enough to be a bp figure (``> 1``) is 100x more likely to be
        one than to be a 110% gain. The bound is deliberately **loose and
        one-sided at the top** — a genuine 150% payoff is legal in this system's
        units and must not be refused — so the check catches the unmistakable
        case and the declaration carries the rest.

        A **total loss is legal** (``-1.0``) and is exactly the ruin branch §22.6
        cares about, so the lower bound is strict: ``< -1.0`` is impossible,
        ``== -1.0`` is the tail.
        """
        if self.payoff_unit != _KELLY_UNIT:
            raise ValueError(
                f"payoff_unit is {self.payoff_unit!r}, but the Kelly arithmetic "
                f"is a growth rate over capital and can only use "
                f"{_KELLY_UNIT!r}. A bp or dollar payoff returns a plausible, "
                f"smaller, more prudent-looking fraction that slips under the "
                f"position cap -- the failure is toward SILENCE, which is why "
                f"this is refused here rather than converted. Convert the "
                f"payoffs (dividing a bp figure by 10000 against a known capital "
                f"base) at the point where the capital base is known, and pass "
                f"the result with the unit declared."
            )
        for scenario in self.scenarios:
            if scenario.payoff_estimate < -1.0:
                raise ValueError(
                    f"Scenario {scenario.name!r} has payoff_estimate "
                    f"{scenario.payoff_estimate!r}, beyond a total loss. A payoff "
                    f"cannot be less than -1.0 when it is a fraction of capital, "
                    f"so this value is either a bp/dollar figure or a data error."
                )
        return self


class SizingOutcome(BaseModel):
    """Why the published size is the number it is — as data, not prose.

    Three states exist and they mean different things to a consumer, which is
    why this is a ``Literal`` and not a caveat on the interpretation string:

    * ``"sized_by_kelly"`` — the fractional-Kelly size survived every hard
      limit and is the published number.
    * ``"clipped_by_position_limit"`` — Kelly asked for more than
      ``max_position_pct_of_portfolio``; the cap governs and the **Kelly content
      is discarded** from the published size. The pre-clip request is published
      beside it so conviction is not silently flattened.
    * ``"no_edge"`` — the growth-optimal fraction is zero or negative, so the
      correct size is **nothing at all**. A zero here is a *decision*, not a
      missing value, and a consumer that reads ``value == 0.0`` as "no opinion"
      has misread it.
    """

    model_config = ConfigDict(extra="forbid")

    outcome: Literal["sized_by_kelly", "clipped_by_position_limit", "no_edge"] = Field(
        description="Which branch determined the published size."
    )


def _expected_log_growth(scenarios: list[ScenarioOutcome], fraction: float) -> float:
    """``SUM_i p_i * log(1 + f * r_i)`` — the growth rate Kelly maximises.

    Returns ``-inf`` when any branch is **ruined** at this ``f`` (``1 + f*r <=
    0``), which is the mathematically right answer and the reason Kelly cannot
    be replaced by an EV maximisation: expected wealth is maximised by betting
    everything on the best branch, while expected *growth* is destroyed by
    ruin, because the log of zero is negative infinity and no later gain
    recovers it. Section 22.6 states the same thing in the comment on this
    exact guard ("ruin at this f for this scenario — Kelly forbids this").
    """
    total = 0.0
    for scenario in scenarios:
        term = 1.0 + fraction * scenario.payoff_estimate
        if term <= 0.0:
            return float("-inf")
        total += scenario.probability * math.log(term)
    return total


def generalized_kelly_fraction(scenarios: list[ScenarioOutcome]) -> ModelResult:
    """The full (undivided) growth-optimal fraction — Section 22.6, the REAL Kelly.

    ``f* = argmax_f  SUM_i [ p_i * log(1 + f * r_i) ]`` over ``f in [0, 1]``.

    **This function is the only thing in the system allowed to call itself
    Kelly.** Section 22.6 (Finding #6) declares the prior ``raw_kelly = ev/100``
    a placeholder "incorrectly labeled Kelly" and replaces it entirely; Section
    22.13 makes deleting it mandatory rather than optional, so the placeholder
    is **not** implemented here at all, in any form, not even behind a flag. The
    two differ by far more than a scale factor — probed on one three-branch set
    the placeholder returns ``0.000162`` where the real function returns
    ``0.5000``, a factor of **3 077x**, and the placeholder is *linear in EV*
    where Kelly is a ratio of odds with a domain that ends at ruin.

    **The output is FULL Kelly and is unsafe to use directly.** It is the number
    that maximises long-run growth *if the probabilities are exact*, and they
    are not — which is why ``kelly_fraction_multiplier`` (``1/k``, k >= 2) is
    mandatory and why this function's warning says so. ``apply_fractional_kelly``
    is the function a caller should use; this one exists so the division has a
    producer and so the raw optimum is auditable.

    Confidence is not calibrated here: the result is an exact optimisation of
    *stated* probabilities, so its precision is a property of the arithmetic and
    not of the world. ``apply_fractional_kelly`` inherits the honest reading.
    """
    settings = get_settings()
    tolerance = settings.probability.probability_sum_tolerance

    if not scenarios:
        raise ValueError(
            "A Kelly fraction needs a distribution to maximise over. An empty "
            "scenario set has no growth rate at any f, so there is no optimum "
            "— as opposed to an optimum of zero, which is what an empty grid "
            "search would otherwise report."
        )

    total_probability = sum(scenario.probability for scenario in scenarios)
    if abs(total_probability - 1.0) > tolerance:
        raise ValueError(
            f"Scenario probabilities sum to {total_probability!r}, which is more "
            f"than {tolerance} from 1.0. Kelly maximises over an EXHAUSTIVE "
            f"distribution: missing mass means the growth rate is computed over "
            f"a set of branches that does not account for every outcome, and the "
            f"optimum is then too large (a forgotten loss branch) or too small "
            f"(a forgotten gain branch) with nothing to signal which."
        )

    best_fraction = 0.0
    best_growth = float("-inf")
    grid_points = settings.kelly.search_points
    for index in range(grid_points):
        fraction = index / (grid_points - 1)
        growth = _expected_log_growth(scenarios, fraction)
        if growth > best_growth:
            best_fraction, best_growth = fraction, growth

    # The grid's lower edge is f=0, where growth is exactly 0 by construction
    # (every log(1) is 0). So a best_growth that is still -inf means EVERY
    # point was ruined and only the initialised 0.0 survived -- distinct from a
    # genuine no-edge optimum, and worth saying so rather than publishing 0.0.
    if best_growth == float("-inf"):
        raise ValueError(
            "Every candidate fraction ruins at least one scenario, including "
            "f = 0. That is impossible for a well-formed set — at f = 0 every "
            "term is exactly 1 and the growth rate is 0 — so the distribution "
            "is malformed rather than the optimum being zero."
        )

    # f* == 1.0 is the grid's UPPER EDGE, not an interior optimum: the search
    # cannot see past it. Reporting it as "bet everything" would be a lie in the
    # precise direction that matters, so it is disclosed (D-057's P2).
    at_search_edge = best_fraction >= 1.0

    settings_kelly = settings.kelly
    warnings: list[str] = [
        f"This is FULL Kelly ({best_fraction:.4f}). It MUST be divided by "
        f"kelly.{'fractional_divisor'} (k >= "
        f"{float(settings_kelly.min_fractional_divisor.value):.0f}) before use — "
        f"Module 12.4 / Section 22.6's mandatory fractional-Kelly rule applies to "
        f"this exact output.",
    ]
    if at_search_edge:
        warnings.append(
            "The optimum is at the SEARCH BOUNDARY (f = 1.0), so the true "
            "growth-optimal fraction is at least 1.0 and may be larger. The "
            "grid cannot see past its own domain. Read this as '>= 1', never as "
            "'bet everything' — and note that any hard limit will bind here, so "
            "the published size is the limit rather than the Kelly output."
        )
    if best_fraction == 0.0:
        warnings.append(
            "The growth-optimal fraction is ZERO: no positive size has a "
            "positive expected log growth. This is a decision to take no "
            "position, not a missing value."
        )

    confidence = compute_confidence(
        ConfidenceInputs(
            # The scenario probabilities are caller-supplied judgements with no
            # calibration behind them, so the input to this optimisation is a
            # belief rather than a measurement. The ARITHMETIC is exact; the
            # distribution is not, and only the latter determines how much the
            # answer is worth.
            is_heuristic_not_calibrated=True,
            depends_on_unobservable=False,
        )
    )

    return ModelResult(
        model_name="generalized_kelly_fraction",
        country="us",
        as_of=utc_now(),
        value={
            "full_kelly_fraction": round(best_fraction, 6),
            "expected_log_growth": round(best_growth, 8),
            # Published so a consumer can see WHY the optimum is where it is,
            # and so a zero-growth answer is distinguishable from a ruined one.
            "growth_at_zero": 0.0,
            "at_search_edge": at_search_edge,
            "grid_points": grid_points,
        },
        confidence=confidence,
        interpretation=(
            f"Full Kelly fraction {best_fraction:.4f}"
            + (" (at the search boundary — a lower bound)" if at_search_edge else "")
        ),
        context=(
            "Grid-search-maximised expected log growth over the FULL scenario "
            "distribution — not a two-outcome approximation, and not the EV/100 "
            "placeholder Section 22.6 replaced. The closed form does not exist "
            "for more than two outcomes, so a search is standard practice rather "
            "than an approximation introduced here."
        ),
        inputs_used=["scenarios"],
        warnings=warnings,
        data_quality_flags_present=False,
    )


def apply_fractional_kelly(inputs: KellyInputs) -> ModelResult:
    """Size a position by fractional Kelly, then clip against the hard limits.

    Module 17.3 / Sections 20.14 and 22.6. **This is the corrected function;
    Section 17.3's ``raw_kelly = ev / 100`` body is not implemented anywhere**
    (Section 22.13 makes its deletion mandatory rather than optional).

    Three things the specification leaves implicit, all of which are defects
    rather than omissions:

    **The divisor is mandatory and comes from config.** Section 17.3's
    signature defaults ``kelly_fraction: float = 0.5``, a literal in a model
    body, which Section 21 prohibits. The value is
    ``1 / kelly.fractional_divisor`` (``k = 2`` -> the ``0.5`` the spec means),
    it is read from the config, and the config already refuses a divisor below
    its floor at load time — so "full Kelly by accident" is a startup error
    rather than a silently aggressive size.

    **A binding cap destroys the Kelly information, so the pre-clip request is
    published beside the clipped size.** Probed, five scenario sets spanning a
    confident 4:1 view through a marginal 1:2 view produce **two** distinct
    published values, because four of them exceed the cap and collapse onto it
    (D-057's P5). The published ``requested_fraction_of_capital`` is what Kelly
    actually said; ``fraction_of_capital`` is what the limits permit; and
    publishing both is the difference between "the cap bound" and "Kelly
    produced this number".

    **``no_edge`` and ``sized_by_kelly`` at zero are different claims.** A
    growth-optimal fraction of zero means *take no position* — a decision — and
    is not the same as a missing value or a limit binding. The outcome
    ``Literal`` carries that distinction so a consumer never has to parse prose.

    **What this function does NOT enforce.** Only ``max_position_pct_of_portfolio``
    is expressible as a constraint on a single position's size. The factor
    exposure, leverage and liquidity limits are not — they constrain the *book*
    or the *instrument*, and a function that sees one position cannot evaluate
    them. They are named in ``limits_declared_but_not_enforced`` rather than
    implied, the same disclosure ``volatility_target_scaling`` publishes
    (D-056's D1/O-48) — and the **set differs** from that function's, because
    the two enforce different limits. The position cap is enforced *here* and
    not there, so reusing 17.2's list would name the wrong set.

    Confidence is computed from stated facts (Section 22.8). The scenario
    probabilities are uncalibrated judgements while the optimisation over them
    is exact, so the heuristic marker is set and the honest reading is the
    project's midpoint — the same reading the project's ``expected_value``
    takes on the same input.
    """
    settings = get_settings()

    # 1. The full, undivided Kelly optimum -- Section 22.6's real function.
    full_kelly = generalized_kelly_fraction(inputs.scenarios)
    full_kelly_value = full_kelly.value
    assert isinstance(full_kelly_value, dict)
    full_fraction = float(full_kelly_value["full_kelly_fraction"])
    at_search_edge = bool(full_kelly_value["at_search_edge"])

    # 2. The mandatory fractional division. Both factors come from config:
    #    the multiplier is 1/divisor and the divisor has a load-time floor.
    multiplier = settings.kelly.kelly_fraction_multiplier
    divisor = settings.kelly.divisor
    requested = full_fraction * multiplier

    # 3. Hard limits always win (Module 17.2's explicit rule, restated here).
    cap = inputs.limits.max_position_pct_of_portfolio
    final_fraction = min(requested, cap)
    clipped = final_fraction < requested

    if full_fraction == 0.0:
        outcome: SizingOutcome = SizingOutcome(outcome="no_edge")
    elif clipped:
        outcome = SizingOutcome(outcome="clipped_by_position_limit")
    else:
        outcome = SizingOutcome(outcome="sized_by_kelly")

    #: The limits a one-position sizer cannot evaluate. Named, not implied --
    #: a caller that reads RiskLimits and assumes this function enforced all of
    #: them is making the same mistake D-056's D1 caught. NOTE the deliberately
    #: different set from `unread_by_vol_targeting`: the two sizing functions
    #: enforce DIFFERENT limits, and `max_position_pct_of_portfolio` is enforced
    #: HERE and not there.
    unenforced = inputs.limits.unread_by_position_sizing

    warnings: list[str] = [
        "Kelly sizing assumes the scenario probabilities are correct, and they "
        "are caller-supplied judgements. The fractional divisor is the "
        "admission that they are not — a size derived at full Kelly is a "
        "bet that the distribution is exact.",
    ]
    if outcome.outcome == "no_edge":
        warnings.append(
            "The growth-optimal fraction is ZERO, so the correct size is NO "
            "POSITION. This is a decision, not a missing value: no positive "
            "size has positive expected log growth for this distribution. A "
            "positive expected VALUE is not sufficient — LTCM's positions were "
            "positive-EV."
        )
    if clipped:
        warnings.append(
            f"Kelly requested {requested:.4f} of capital (full Kelly "
            f"{full_fraction:.4f} / divisor {divisor:.1f}) and the position cap "
            f"is {cap:.4f}, so the cap governs. The published size is the LIMIT, "
            f"not the Kelly output — the conviction that produced "
            f"{requested:.4f} is not represented in the number and is published "
            f"separately."
        )
    if at_search_edge:
        warnings.append(
            "The full-Kelly optimum is at the search boundary (f = 1.0), so it "
            "is a LOWER bound on the true optimum rather than an interior "
            "solution. The request below is therefore also a lower bound — and "
            "because EVERY distribution with an all-positive edge pins at this "
            "same boundary, the request is then 1/divisor for all of them, so it "
            "does NOT distinguish them (D-057's P5b). "
            "expected_log_growth_at_request is what still does."
        )
    if unenforced:
        warnings.append(
            f"Only max_position_pct_of_portfolio is enforced here. The "
            f"following declared limits are NOT evaluated by a single-position "
            f"sizer and are reported as unenforced: {', '.join(unenforced)}."
        )

    confidence = compute_confidence(
        ConfidenceInputs(
            is_heuristic_not_calibrated=True,
            depends_on_unobservable=False,
        )
    )

    if outcome.outcome == "no_edge":
        interpretation = (
            "No position: the growth-optimal fraction is zero, so Kelly sizes "
            "this at 0.0000 of capital (not a limit — no edge)."
        )
    elif clipped:
        interpretation = (
            f"Size {final_fraction:.4f} of capital (clipped at the "
            f"{cap:.4f} position cap; Kelly requested {requested:.4f} from full "
            f"Kelly {full_fraction:.4f} / divisor {divisor:.1f})."
        )
    else:
        interpretation = (
            f"Size {final_fraction:.4f} of capital (full Kelly "
            f"{full_fraction:.4f} / divisor {divisor:.1f}, no limit bound)."
        )

    return ModelResult(
        model_name="apply_fractional_kelly",
        country="us",
        as_of=utc_now(),
        value={
            "fraction_of_capital": round(final_fraction, 6),
            # The pre-clip request, so a binding cap does not silently flatten
            # conviction into one shared number (D-057's P5).
            "requested_fraction_of_capital": round(requested, 6),
            "full_kelly_fraction": round(full_fraction, 6),
            "fractional_divisor": round(divisor, 6),
            "position_cap": round(cap, 6),
            "clipped_by_position_limit": clipped,
            "outcome": outcome.outcome,
            # The growth rate the published size is expected to compound at.
            # AT the request, not at the clipped size: the cap is a constraint
            # on the book, not on the distribution, so re-evaluating growth at
            # a size Kelly did not choose would answer a different question.
            "expected_log_growth_at_request": round(
                _expected_log_growth(inputs.scenarios, requested), 8
            ),
            "limits_declared_but_not_enforced": unenforced,
        },
        confidence=confidence,
        interpretation=interpretation,
        context=(
            "Fractional Kelly over the FULL scenario distribution (Section 22.6), "
            "clipped against the position cap — hard constraints always win over "
            "Kelly-derived size (Module 17.3). This function reports a size and "
            "NEVER places an order."
        ),
        inputs_used=["scenarios", "payoff_unit"],
        warnings=warnings,
        data_quality_flags_present=False,
    )


# ---------------------------------------------------------------------------
# Module 17.1 — risk-budgeted weight construction (Section 9.2, Phase 4)
# ---------------------------------------------------------------------------


class RiskBudgetInputs(BaseModel):
    """Section 9.2's inputs: a return matrix and a target risk budget.

    ``instrument_returns`` is a mapping of **instrument -> list of period
    returns in DECIMAL form** (``0.01`` = +1%), oldest first, all the same
    length. Section 9.2 writes it as a ``pd.DataFrame`` with columns as
    instruments and the index as dates; a mapping of equal-length lists is the
    same object without the pandas dependency in the model layer, and it makes
    the **length equality** a checkable contract rather than an assumption
    (pandas silently aligns and NaN-pads a ragged frame, which would turn a
    mis-joined series into a plausible covariance).

    ``target_risk_contribution`` is Section 9.2's ``dict[str, float]``:
    instrument -> intended share of **total portfolio risk**, as a fraction.
    It must name exactly the instruments in ``instrument_returns`` — a budget
    for an instrument with no returns, or returns with no budget line, is a
    mismatch whose repair differs in each direction, so both are refused by
    name rather than silently intersected.

    **The two are different objects and the docstring states it because no
    arithmetic reveals it.** ``instrument_returns`` is a *measurement*;
    ``target_risk_contribution`` is an *intention*. A caller who passes dollar
    weights where risk shares are wanted gets a number that looks fine and
    sizes the book wrongly — Module 17.1's whole content.
    """

    model_config = ConfigDict(extra="forbid")

    instrument_returns: dict[str, list[float]] = Field(
        min_length=1,
        description=(
            "instrument -> period returns as DECIMALS, oldest first. Every "
            "instrument must carry the same number of observations; they are "
            "treated as a single aligned panel."
        ),
    )
    target_risk_contribution: dict[str, float] = Field(
        min_length=1,
        description=(
            "instrument -> intended share of TOTAL portfolio risk, as a "
            "FRACTION. Must name exactly the instruments in "
            "instrument_returns, and is not a notional weight."
        ),
    )

    @model_validator(mode="after")
    def _panel_must_be_rectangular_and_budgeted(self) -> RiskBudgetInputs:
        """Refuse a ragged panel, a non-positive share, and a name mismatch.

        Three checks, each because the failure it prevents is silent:

        * **Ragged panel.** A covariance needs every instrument observed over
          the same window. Unequal lengths mean the panel is not aligned, and
          any pairwise computation over it (zero-padded, truncated, or
          index-zipped) produces a covariance of a book that never existed.
        * **Name mismatch, both directions.** A budget line with no returns is
          uninvestable; returns with no budget line are risk nobody budgeted.
          Intersecting silently would answer a question the caller did not ask
          (M-5's exact defect, one layer up).
        * **Non-positive share.** A zero share asks for a zero-weight position,
          which the solver cannot represent without degenerating; a negative
          share is not a budget. Both are refused here rather than producing a
          negative weight that would then be published as a sizing.
        """
        lengths = {name: len(values) for name, values in self.instrument_returns.items()}
        distinct_lengths = set(lengths.values())
        if len(distinct_lengths) > 1:
            detail = ", ".join(f"{name}={n}" for name, n in sorted(lengths.items()))
            raise ValueError(
                f"instrument_returns is not a rectangular panel: {detail}. A "
                f"covariance is estimated over one aligned window, so every "
                f"instrument must carry the same number of observations. Padding "
                f"or truncating would compute the covariance of a book that "
                f"never existed."
            )
        if min(distinct_lengths) < 2:
            raise ValueError(
                f"instrument_returns carries {min(distinct_lengths)} observation(s); at "
                f"least 2 are needed for a covariance to be defined."
            )

        budgeted = set(self.target_risk_contribution)
        measured = set(self.instrument_returns)
        unbudgeted = sorted(measured - budgeted)
        unmeasured = sorted(budgeted - measured)
        if unbudgeted or unmeasured:
            raise ValueError(
                f"target_risk_contribution and instrument_returns name different "
                f"instruments. Returns with no budget line: {unbudgeted or 'none'}. "
                f"Budget lines with no returns: {unmeasured or 'none'}. These are "
                f"different repairs — an unbudgeted book needs a budget, an "
                f"unmeasured line needs data — so they are refused rather than "
                f"silently intersected."
            )

        for name, share in self.target_risk_contribution.items():
            if not 0.0 < share <= 1.0:
                raise ValueError(
                    f"target_risk_contribution[{name!r}]={share} is outside (0, 1]. "
                    f"A risk budget is a FRACTION of total risk; a zero share "
                    f"cannot be represented by a positive weight, and a negative "
                    f"share is not a budget. Drop the instrument instead."
                )
        total = sum(self.target_risk_contribution.values())
        if abs(total - 1.0) > _RISK_BUDGET_SUM_TOLERANCE:
            raise ValueError(
                f"target_risk_contribution sums to {total!r}, not 1.0 (tolerance "
                f"{_RISK_BUDGET_SUM_TOLERANCE}). A risk budget is an allocation of "
                f"a WHOLE: shares that do not sum to 1 leave risk unallocated, and "
                f"the solver would then be asked to hit targets no weight vector "
                f"can satisfy."
            )
        return self

    @property
    def instruments(self) -> list[str]:
        """Instrument names in a **deterministic** order.

        Sorted, not insertion-ordered, because the returned weights are a
        vector and a caller reading ``weights[2]`` needs the index-to-name
        mapping to be reproducible across processes. Insertion order in a
        ``dict`` is a language guarantee, but it is a guarantee about *this*
        object, not about the order a caller compares two results in.
        """
        return sorted(self.instrument_returns)


#: Tolerance on the risk-budget shares summing to 1.0. A budget is a partition
#: of total risk, so this is an exactness check rather than a fit; the tolerance
#: exists only for float summation, not to admit an approximate budget.
_RISK_BUDGET_SUM_TOLERANCE = 1e-9

#: A named mirror of the shipped ``risk.risk_parity_tolerance`` value (``1e-10``),
#: kept as the human-readable reference for that leaf (`settings.yaml:1519`).
#: It is NOT the signature default any more: ``compute_risk_parity_weights`` takes
#: ``tolerance=None`` and resolves it to the config leaf, so the leaf is live and
#: a caller-supplied value is the only override. Kept (rather than deleted) because
#: other modules and tests import it by name; if the leaf is ever re-tuned, this
#: constant and the YAML must move together.
DEFAULT_RISK_PARITY_TOLERANCE = 1e-10


def sample_covariance(
    panel: dict[str, list[float]],
    *,
    annualization_periods: int,
    ddof: int = 1,
) -> tuple[list[str], list[list[float]]]:
    """Sample covariance of a rectangular return panel, annualised.

    Returns ``(instruments, covariance)`` with ``instruments`` sorted so the
    matrix's row/column order is reproducible and stated rather than implied by
    dict order.

    **Why this is written out rather than delegated to pandas.** The project's
    ``models/risk.py`` computed ``w' Sigma w`` explicitly for the same reason
    (a BLAS build must not change the last digit of a risk budget), and a
    covariance that differs across environments is not auditable. It also makes
    the estimator's choices visible: ``ddof``, the annualisation, and the
    two-pass mean/centred-sum formulation are all in the body.

    **``ddof = 1``** is the unbiased estimator, matching
    ``realized_vol_simple`` in ``models/risk.py`` — the two must agree on the
    diagonal or a book's risk budget and its vol target would be computed from
    two different volatilities for the same instrument. That agreement is
    asserted by ``test_the_diagonal_matches_realized_vol_simple``.

    The estimator is the plain sample covariance and **not** a shrinkage or
    factor estimator. That is a real limitation at large N — the sample
    covariance has ``N(N+1)/2`` parameters and its estimation error grows
    quadratically while the data does not — and it is disclosed on the result
    rather than silently swapped for a better estimator this module has not
    calibrated.
    """
    instruments = sorted(panel)
    n_assets = len(instruments)
    observations = len(panel[instruments[0]])

    means = [sum(panel[name]) / observations for name in instruments]

    covariance: list[list[float]] = [[0.0] * n_assets for _ in range(n_assets)]
    denominator = observations - ddof
    if denominator <= 0:
        raise ValueError(
            f"sample_covariance needs more observations than ddof; got "
            f"{observations} observations for ddof={ddof}."
        )
    for i in range(n_assets):
        for j in range(i, n_assets):
            total = 0.0
            left = panel[instruments[i]]
            right = panel[instruments[j]]
            for k in range(observations):
                total += (left[k] - means[i]) * (right[k] - means[j])
            value = total / denominator * annualization_periods
            covariance[i][j] = value
            covariance[j][i] = value
    return instruments, covariance


def risk_contributions(
    weights: list[float],
    covariance_matrix: list[list[float]],
) -> list[float]:
    """``RC_i = w_i (Sigma w)_i / sigma_p^2``, as **fractions of total risk**.

    The same Euler decomposition ``marginal_risk_contributions`` publishes, but
    returned as a plain vector rather than a ``ModelResult`` because the
    optimiser calls it in a tight loop and a ``ModelResult`` per iteration would
    allocate the whole reporting surface for an intermediate number.

    ``marginal_risk_contributions`` remains the function a *caller* should use
    for a report; this is the arithmetic both share. They are cross-checked
    against each other in the live check, which is what keeps the two from
    drifting.

    **The denominator is the VARIANCE, not the volatility.** The unnormalised
    contributions ``w_i (Sigma w)_i`` sum to ``w' Sigma w = sigma_p^2``, so
    dividing by that total is what makes them shares. Dividing by ``sigma_p``
    instead would produce numbers summing to ``sigma_p`` rather than 1 — a
    self-consistent vector that is not a partition of risk. The same distinction
    governs ``_ccd_step``'s right-hand side, and getting it wrong there is the
    defect ``test_the_ccd_step_solves_the_two_asset_oracle_exactly`` pins.

    Raises:
        ValueError: on a zero or negative portfolio variance — risk shares are
            undefined when there is no total to divide.
    """
    variance = _quadratic_form(weights, covariance_matrix)
    if variance <= 0.0:
        raise ValueError(
            f"Portfolio variance is {variance!r} (non-positive); risk "
            f"contributions are shares of a total and are undefined without one."
        )
    n = len(weights)
    marginal = [sum(covariance_matrix[i][j] * weights[j] for j in range(n)) for i in range(n)]
    raw = [weights[i] * marginal[i] for i in range(n)]
    total = sum(raw)
    if total <= 0.0:
        raise ValueError(
            f"Unnormalised risk contributions sum to {total!r}; the covariance "
            f"does not describe a book with positive total risk."
        )
    return [value / total for value in raw]


def _risk_parity_objective(
    weights: list[float],
    covariance_matrix: list[list[float]],
    targets: list[float],
) -> float:
    """``SUM_i (RC_i - b_i)^2`` — the quantity the solver minimises.

    Squared deviation rather than the sum of absolute deviations because the
    squared form is what makes the coordinate-descent update below have a
    closed form; the minimum is at the same point since both are zero exactly
    when every ``RC_i == b_i``.
    """
    contributions = risk_contributions(weights, covariance_matrix)
    return sum((contributions[i] - targets[i]) ** 2 for i in range(len(weights)))


def _ccd_step(
    weights: list[float],
    covariance_matrix: list[list[float]],
    targets: list[float],
    index: int,
) -> float:
    """One **cyclical coordinate descent** update for asset ``index``.

    The published algorithm (Griveau-Billion, Richard & Roncalli 2013,
    *"A Fast Algorithm for Computing High-dimensional Risk Parity Portfolios"*),
    which is the closed-form Newton step for the risk-budgeting problem that
    riskfolio-lib's own optimiser is built on. It is implemented here rather
    than pulled in as a dependency because it is **twenty lines of auditable
    arithmetic** and this project's risk budgets must not depend on a BLAS
    build — the same reason ``_quadratic_form`` is written out.

    The step is derived from ``d(SUM_j (RC_j - b_j)^2)/dw_i = 0`` and, for the
    volatility risk measure, reduces to a fixed-point update: the new ``w_i``
    solves a quadratic whose coefficients come from the rest of the book.

    **The right-hand side is ``b_i * sigma_p^2`` — the VARIANCE, not the
    volatility.** This is the one place the algebra is easy to get wrong and
    impossible to notice from the output, so it is stated explicitly and pinned
    by a closed-form oracle test. The fixed point comes from the *unnormalised*
    Euler contribution, which sums to the portfolio **variance**:

        w_i * (Sigma w)_i  =  b_i * sigma_p^2

    Writing ``(Sigma w)_i = a_i + Sigma_ii w_i`` with ``a_i`` the cross term
    (the part not involving ``w_i``) gives ``Sigma_ii w_i^2 + a_i w_i -
    b_i sigma_p^2 = 0``, whose positive root is the update. Substituting
    ``sigma_p`` for ``sigma_p^2`` — the natural-looking slip, since the same
    paragraph also reasons about volatilities — produces a step that is
    *stable* and *monotone* and converges to the **wrong book**: on the
    uncorrelated two-asset oracle with vols 20%/5% and a 50/50 budget it
    settles at ``w = [0.1214, 0.8786]`` with risk contributions
    ``[0.2339, 0.7661]`` instead of the exact ``[0.2, 0.8]`` / ``[0.5, 0.5]``,
    and it does not converge at all (the objective stalls at ~1.6e-1 no matter
    the iteration budget). It was caught by the oracle, not by the live data,
    which looked plausible at every step.

    Returns the updated weight for ``index`` (unclipped; the caller re-imposes
    the positivity and normalisation constraints).
    """
    n = len(weights)
    # The part of (Sigma w) that does NOT depend on w_i.
    partial = [
        sum(covariance_matrix[k][j] * weights[j] for j in range(n) if j != index) for k in range(n)
    ]

    sigma_ii = covariance_matrix[index][index]
    if sigma_ii <= 0.0:
        raise ValueError(
            f"covariance_matrix[{index}][{index}]={sigma_ii} is non-positive. A "
            f"risk-parity weight is 1/sqrt(variance) for the uncorrelated case, "
            f"so a zero-variance instrument has no finite weight."
        )

    # Cross term a_i = SUM_{j != i} Sigma_ij w_j = partial[index].
    a_i = partial[index]
    target = targets[index]
    if target <= 0.0:
        raise ValueError(f"target {target!r} for asset {index} is not positive.")

    # Solve  Sigma_ii w_i^2 + a_i w_i - b_i * sigma_p^2 = 0  for the positive
    # root. `sigma_p^2` is the UNNORMALISED total risk, so the RHS is the
    # variance. See the docstring: using sigma_p here converges, smoothly, to
    # the wrong portfolio.
    current_variance = _quadratic_form(weights, covariance_matrix)
    sigma_p_squared = max(current_variance, _CCD_SIGMA_FLOOR)
    discriminant = a_i * a_i + 4.0 * sigma_ii * target * sigma_p_squared
    return (-a_i + math.sqrt(discriminant)) / (2.0 * sigma_ii)


#: Floor for the portfolio-volatility estimate used inside the CCD step. The
#: published algorithm scales by a damped ``sigma_p``; a literal ``1.0`` is the
#: convention in the reference implementation and it only matters while the
#: iterate is still far from the solution, so it is named rather than inline.
_CCD_SIGMA_FLOOR = 1e-12


def compute_risk_parity_weights(
    inputs: RiskBudgetInputs,
    *,
    tolerance: float | None = None,
    max_iterations: int = 10_000,
) -> ModelResult:
    """Weights whose **risk contributions** match the target budget (Section 9.2).

    Module 17.1's core principle, implemented: size by **risk** contribution,
    not by notional. A high-volatility instrument takes a *smaller* dollar
    position so that it contributes the same risk as a low-volatility one. The
    output is therefore **weights**, and they are not the input budget — the
    budget is in risk units and the weights are in capital units, and the
    function publishes both so the gap is visible.

    The optimiser
    -------------
    Cyclical coordinate descent on ``SUM_i (RC_i - b_i)^2`` (Griveau-Billion et
    al. 2013), each coordinate updated by its closed-form Newton step and
    renormalised to sum to 1 after every sweep. It converges monotonically on a
    positive-definite covariance and is deterministic: no random initialisation,
    no tolerance-dependent path, no BLAS-dependent summation order. That matters
    for a risk budget, which a desk reconciles against a previous run.

    **``riskfolio-lib`` is the specification's intended backend and is NOT
    used.** Section 9.2 names it, Section 4 lists it as an optional dependency,
    and Section 12 anticipates filling in this body. The decision not to is
    recorded in ``docs/DECISIONS.md``: the algorithm is twenty lines, the
    library would add a heavy transitive dependency (and a CVXPY/CLARABEL solver
    stack) whose *solution* is not reproducible to the last digit, and Module
    17.1 is exactly the place where this project has already decided that
    reproducibility beats convenience (``_quadratic_form``, ``models/risk.py``).
    The result is cross-checked against a **closed-form oracle** in the
    two-asset case, where the exact risk-parity solution is known, so the
    correctness argument does not rest on the implementation being trusted.

    Three things the specification leaves implicit, all defects
    ----------------------------------------------------------
    1. **The covariance is an estimate and its window is not stated.** Returns
       alone do not determine a covariance; the *estimator* and the *window*
       do, and a risk budget computed over a quiet window differs materially
       from one over a crisis. The estimator is the plain sample covariance
       (``sample_covariance``), the window is whatever the caller supplied, and
       the observation count is published.
    2. **The target budget may be unreachable, and the solver would still
       return something.** With N assets and a positive-definite covariance the
       interior solution exists, but with an *ill-conditioned* matrix the CCD
       iterate can stall above tolerance. The function therefore **reports the
       achieved contributions and the worst target error** and warns when the
       solve did not converge — rather than returning weights that look like a
       solution to a problem it did not solve.
    3. **A risk budget is not a trade.** The weights this returns are *capital*
       weights for a book, and ``translate_thesis_to_position`` is the function
       that turns a *thesis* into a size. Nothing here places an order.

    The LTCM caveat is reported on every run (Module 17.1's mandated warning),
    and the **stressed re-solve** is the substance of it: the same budget is
    re-solved at the configured stressed correlation, so a budget that only
    holds when correlations are low is visible as a divergence rather than
    described in prose.
    """
    instruments = inputs.instruments
    panel = {name: inputs.instrument_returns[name] for name in instruments}
    targets = [inputs.target_risk_contribution[name] for name in instruments]
    n = len(instruments)

    settings = get_settings()
    annualization = settings.risk.risk_parity_annualization_periods
    stress_correlation = settings.risk.stress_corr
    # The tolerance is a config leaf (`risk.risk_parity_tolerance`) and the
    # parameter is an OVERRIDE: an explicit `tolerance` from the caller wins,
    # and `None` (the default) takes the configured value. Before this the
    # parameter default `DEFAULT_RISK_PARITY_TOLERANCE` was always shadowing the
    # leaf, so `risk.risk_parity_tolerance` was dead for the one function it was
    # authored to parameterise.
    if tolerance is None:
        tolerance = settings.risk.risk_parity_tolerance

    _, covariance = sample_covariance(panel, annualization_periods=annualization)
    observations = len(panel[instruments[0]])

    # --- the solve ------------------------------------------------------
    # Start from equal weights. The problem is not convex in w for an arbitrary
    # covariance, so the starting point is part of the result: equal weights is
    # the symmetric, budget-agnostic choice, and it is stated here so a caller
    # can reproduce it. The loop itself lives in `_solve_risk_parity` so the
    # stressed re-solve below cannot drift from the normal solve.
    weights, converged, iterations = _solve_risk_parity(
        covariance, targets, n, tolerance, max_iterations
    )

    achieved = risk_contributions(weights, covariance)
    worst_error = max(abs(achieved[i] - targets[i]) for i in range(n))
    variance = _quadratic_form(weights, covariance)
    portfolio_vol = math.sqrt(variance) if variance > 0.0 else 0.0

    # --- the correlation stress re-solve (Module 17.1's LTCM caveat) -----
    stressed_covariance = stress_correlations(
        covariance, stress_correlation, only_correlations_that_rise=True
    )
    stressed_weights, _, _ = _solve_risk_parity(
        stressed_covariance, targets, n, tolerance, max_iterations
    )
    stressed_achieved = risk_contributions(stressed_weights, stressed_covariance)
    stressed_worst_error = max(abs(stressed_achieved[i] - targets[i]) for i in range(n))
    # The MAXIMUM absolute weight change is the actionable number: it is the
    # size of the rebalance the stress would demand, not a summary statistic.
    max_weight_shift = max(abs(stressed_weights[i] - weights[i]) for i in range(n))

    warnings: list[str] = [
        "Correlation is an ESTIMATE and rises toward 1 in a crisis — the "
        "diversification this budget relies on is largest exactly when it will "
        "be least available (Module 17.1, the LTCM lesson). The stressed "
        "re-solve is reported beside it and is the number to size against.",
        "The sample covariance is BACKWARD-LOOKING and noisy. With N "
        "instruments it has N(N+1)/2 parameters, so a budget built on a short "
        "window and many instruments rests on more parameters than data.",
    ]
    if not converged:
        warnings.append(
            f"The risk-parity solve did NOT converge within {max_iterations} "
            f"iterations; the worst achieved-vs-target error is {worst_error:.6f}. "
            f"The weights are the best iterate, NOT a solution to the stated "
            f"budget. Widen the window, drop a collinear instrument, or raise "
            f"the iteration budget."
        )
    if max_weight_shift > settings.risk.risk_parity_stress_shift_threshold:
        warnings.append(
            f"Under the stressed correlation ({stress_correlation}), the "
            f"same risk budget implies a materially different book: the largest "
            f"weight moves by {max_weight_shift:.4f}. A budget that only holds "
            f"at normal correlations is not a budget for the regime it exists to "
            f"survive."
        )

    confidence = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=not converged,
            # A sample covariance is an estimate, not a calibrated model: the
            # estimator choice (plain, unshrunk), the window, and the
            # normal-correlation assumption are all conventions this module has
            # not calibrated against realized out-of-sample risk.
            is_heuristic_not_calibrated=True,
            depends_on_unobservable=False,
        )
    )

    return ModelResult(
        model_name="compute_risk_parity_weights",
        country="us",
        as_of=utc_now(),
        value={
            # The answer: capital weights whose risk contributions hit the
            # budget. Kept as a dict keyed by instrument name rather than a bare
            # vector, because a caller must not have to remember the order.
            "weights": {instruments[i]: round(weights[i], 10) for i in range(n)},
            "risk_contributions": {instruments[i]: round(achieved[i], 10) for i in range(n)},
            "target_risk_contribution": {instruments[i]: targets[i] for i in range(n)},
            # The notional-vs-risk gap, which is the whole economic point: the
            # weight vector and the budget are different objects.
            "notional_vs_risk_gap": {
                instruments[i]: round(weights[i] - achieved[i], 10) for i in range(n)
            },
            "portfolio_volatility_annualized": round(portfolio_vol, 10),
            "stressed_weights": {instruments[i]: round(stressed_weights[i], 10) for i in range(n)},
            "max_weight_shift_under_stress": round(max_weight_shift, 10),
            "worst_target_error": round(worst_error, 12),
            "stressed_worst_target_error": round(stressed_worst_error, 12),
            "observations": observations,
            "annualization_periods": annualization,
            "iterations": iterations,
            "converged": converged,
            "stressed_correlation": stress_correlation,
        },
        confidence=confidence,
        interpretation=(
            f"Risk-budgeted weights over {n} instruments ({observations} "
            f"observations, {annualization}/yr); worst target error "
            f"{worst_error:.2e}" + ("" if converged else " (NOT CONVERGED)")
        ),
        context=(
            "Module 17.1: weights are chosen so each instrument CONTRIBUTES its "
            "target share of total portfolio risk, which is not its notional "
            "share. Under the stressed correlation the same budget implies a "
            "different book; `max_weight_shift_under_stress` is that difference. "
            "This function reports weights and NEVER places an order."
        ),
        inputs_used=["instrument_returns", "target_risk_contribution"],
        warnings=warnings,
        data_quality_flags_present=not converged,
    )


def _solve_risk_parity(
    covariance: list[list[float]],
    targets: list[float],
    n: int,
    tolerance: float,
    max_iterations: int,
) -> tuple[list[float], bool, int]:
    """The CCD solve, factored out so the stress re-solve reuses it exactly.

    Duplicating the loop for the stressed case would let the two drift — the
    normal solve and the stressed solve must differ **only** in the covariance,
    or the reported shift would confound a correlation change with a change of
    algorithm.

    Returns ``(weights, converged, iterations)``. **``converged`` is returned
    rather than raised on**: a non-converged solve is a *result* this function
    is required to report (the weights are the best iterate, not a solution),
    and turning it into an exception would let the caller's `except` discard
    the very numbers the warning needs to quote.

    The stopping test is on ``SUM_i (RC_i - b_i)^2 <= tolerance**2`` — the
    squared objective against the squared tolerance, **not** the objective
    against the tolerance. Comparing a sum of squares to a linear tolerance
    would silently loosen the standard by its own square root, so the two
    sides carry matched dimensions.
    """
    weights = [1.0 / n] * n
    converged = False
    # `iterations` is the count reported on the result, so it must be readable
    # after the loop; the range is consumed through an explicit index so the
    # final value is the number of sweeps actually run, not one past it.
    iterations = 0
    for sweep in range(1, max_iterations + 1):
        iterations = sweep
        for index in range(n):
            updated = _ccd_step(weights, covariance, targets, index)
            if updated > 0.0:
                weights[index] = updated
        total = sum(weights)
        if total <= 0.0:
            raise ValueError(
                "The risk-parity iteration collapsed to a non-positive weight "
                "vector. This happens when the covariance is not positive "
                "definite — most often because correlations were specified "
                "independently and form an impossible combination."
            )
        weights = [value / total for value in weights]
        if _risk_parity_objective(weights, covariance, targets) <= tolerance**2:
            converged = True
            break
    return weights, converged, iterations


def stress_correlations(
    covariance_matrix: list[list[float]],
    stressed_correlation: float,
    *,
    only_correlations_that_rise: bool = True,
) -> list[list[float]]:
    """Replace every off-diagonal correlation with the stressed value.

    Section 21.1's ``correlation_stressed`` (``settings.yaml``:
    ``risk.stress_correlation``, default ``0.9``) applied to a covariance
    matrix. Variances are preserved exactly — only the correlations move — so
    the stressed book differs from the normal one **only** because of the
    correlation assumption, which is what makes the comparison a stress test
    rather than a second estimate.

    **``only_correlations_that_rise = True`` by default, and that is a
    substantive choice.** *"Correlations converge toward 1 in a crisis"* is the
    Module 17.1 lesson, and it is a statement about the **upper tail**: an
    already-negative correlation (a genuine hedge, e.g. long bonds against
    equities) is not claimed to become *more* negative in a crisis, and forcing
    it to +0.9 would model a flight-to-quality asset as a source of crisis
    contagion.

    The default therefore raises a correlation **only when it is non-negative
    and below the stressed value**, and leaves a genuinely negative one alone:

        rho_stressed_ij = max(rho_ij, rho_stress)   if rho_ij >= 0
                        = rho_ij                     if rho_ij <  0

    **The negative branch is the part that is easy to get wrong.** A plain
    ``max(rho_ij, rho_stress)`` reads as "raise it toward the stress", but
    applied to ``rho_ij = -0.5`` it returns ``+0.9`` — the *opposite* sign —
    and it does so silently, because the result is still a legal correlation.
    The hedge becomes the largest source of contagion in the stressed book and
    the reported ``max_weight_shift_under_stress`` is then driven by an
    assumption nobody made. This project has already measured the effect on real
    US pairs (``models/yield_curve.py``, D-062 probe P2): stressed correlations
    run ``-0.623 .. 0.858`` across eight cross-market pairs, so a flat push to
    0.9 does not describe stress — it describes a different world.

    Both modes are reachable and the choice is reported by the caller that uses
    it. ``only_correlations_that_rise = False`` applies the flat
    ``rho_stress`` everywhere, off-diagonal, which is the correct input when the
    hypothesis under test *is* "every pair converges" — an assumption to be
    stated, not the default.

    The result is **not guaranteed positive semi-definite** — raising arbitrary
    correlations can make a matrix infeasible — so the caller's solver is the
    check: an infeasible matrix will fail to yield positive weights and that
    raises rather than producing a false budget. The condition number is
    reported so an ill-conditioned stress is visible before the solve.
    """
    if not 0.0 < stressed_correlation <= 1.0:
        raise ValueError(
            f"stressed_correlation must be in (0, 1], got {stressed_correlation}. "
            f"A stressed correlation is a positive dependence assumption; a value "
            f"above 1 is not a correlation."
        )

    n = len(covariance_matrix)
    standard_deviations = [math.sqrt(covariance_matrix[i][i]) for i in range(n)]
    stressed: list[list[float]] = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j:
                stressed[i][j] = covariance_matrix[i][i]
                continue
            denominator = standard_deviations[i] * standard_deviations[j]
            if denominator == 0.0:
                # A zero-variance instrument has no correlation; its covariance
                # with everything is already zero and stays zero.
                stressed[i][j] = 0.0
                continue
            current = covariance_matrix[i][j] / denominator
            # Clamp to the legal interval: a sample correlation from a short
            # window can exceed 1 by float noise, and sqrt of a negative would
            # surface as a domain error far from its cause.
            current = max(-1.0, min(1.0, current))
            if only_correlations_that_rise:
                # A negative correlation is a HEDGE and is preserved: "correlations
                # converge toward 1" is a claim about the upper tail, and a plain
                # `max(current, stressed)` would flip -0.5 to +0.9, turning the
                # hedge into the stressed book's largest source of contagion.
                applied = max(current, stressed_correlation) if current >= 0.0 else current
            else:
                applied = stressed_correlation
            stressed[i][j] = applied * denominator
    return stressed


# ---------------------------------------------------------------------------
# Module 17.4 — thesis -> position translation (Section 9.3, Phase 4)
# ---------------------------------------------------------------------------

#: Why Section 9.3's translation produced the number it produced (or none).
#:
#: **Five of the nine members are refusals, and that ratio is the design.** A
#: function that sizes a thesis has five distinct ways to be asked for
#: something it must not produce, and every one of them is reachable on a real
#: thesis today — a stand-down, an analytical-only instrument, an
#: uncalibrated distribution, a negative-edge distribution, and a missing risk
#: budget. Collapsing them into one "refused" would make the *reason* prose
#: again, and this project has measured three times (D-054/D-056/D-057) that
#: the failure mode of these mechanisms is **silence**, not a wrong number: a
#: consumer that cannot distinguish "no edge" from "no budget supplied" reads
#: whichever one happens to be the default as the other.
#:
#: ``"refused_not_a_trade"``
#:     The thesis carries a no-trade idea (``TradeIdea.is_trade`` is False) or
#:     an analytical-only instrument. Section 16.3 makes NO TRADE a first-class
#:     outcome; there is nothing to size, and inventing a size for it would
#:     manufacture the position the stand-down refused.
#: ``"refused_scenarios_uncalibrated"``
#:     Section 25: the scenario probabilities are not calibrated, so
#:     ``apply_fractional_kelly`` must not be called on them. **This is the
#:     live state of every thesis today.**
#: ``"refused_no_edge"``
#:     Kelly's growth-optimal fraction is zero. A **decision to take no
#:     position**, not missing data — the distinction ``SizingOutcome`` exists
#:     to carry.
#: ``"refused_no_risk_budget"``
#:     The instrument has no budget line — an allocation of zero. Kelly
#:     produced a size and the book has allocated this instrument no risk; a
#:     zero budget is a decision, not a small number.
#: ``"sized_by_kelly"``
#:     Kelly produced the number and no limit bound it.
#: ``"clipped_by_position_limit"``
#:     The position cap produced the number. Kelly's pre-clip request is
#:     published beside it, because a binding cap collapses every confident
#:     view onto one size (D-057's P5).
#:
#: **There is deliberately no ``"refused_no_scenarios"`` member.** It was in the
#: first two drafts, and removing it is the same decision as removing the
#: ``_reconciled`` pair below — a member for a path that cannot run reads as a
#: path that *does* run. This one took two passes to see because its **first**
#: justification was sound and only its **reachability** was false: "we have
#: probabilities we may not use" and "we have no probabilities" genuinely need
#: different repairs, but no ``MacroThesis`` can be in the second state here.
#: ``_enforce_scenario_status_matches_distribution`` refuses an empty
#: distribution carrying a non-``empty_no_trade`` status, and gate 2 refuses
#: every non-``calibrated`` status — so an empty distribution reaching the Kelly
#: call is impossible. Enumerated over the 4 instruments x 3 statuses x {0, 1}
#: branches cross-product (24 cells): produced by **none**. See Gate 3's comment.
#:
#: **There is deliberately no ``"_reconciled"`` member.** The first draft had
#: two (``sized_by_kelly_reconciled`` / ``clipped_by_position_limit_reconciled``)
#: for a risk-budget reconciliation that turned out to be a unit error — see the
#: Gate 4 comment. A member for a path that cannot run reads as a path that
#: *does* run, and this project's recurring defect is precisely a declared,
#: consumed, unreachable branch (D-045/D-046/D-048, **O-53**). The risk
#: allocation is published as a **bound** (``permitted_risk_contribution``)
#: instead, which is what the specification's "portfolio risk budget config"
#: actually supports in a function with no covariance.
PositionTranslationOutcome = Literal[
    "refused_not_a_trade",
    "refused_scenarios_uncalibrated",
    "refused_no_edge",
    "refused_no_risk_budget",
    "sized_by_kelly",
    "clipped_by_position_limit",
]

_TRANSLATION_OUTCOMES: frozenset[str] = frozenset(get_args(PositionTranslationOutcome))


def _as_translation_outcome(value: str) -> PositionTranslationOutcome:
    """Narrow a runtime string to the ``PositionTranslationOutcome`` Literal.

    The Kelly gate reports its verdict as a plain ``str``. mypy cannot narrow a
    ``str`` to a ``Literal``, so the previous line here was
    ``outcome: PositionTranslationOutcome = kelly_outcome  # type: ignore[assignment]``
    — a suppression that made the declaration a lie the checker was told not to
    look at. A suppression hides the invariant; this function checks it.

    The membership test is the point. If the Kelly gate ever emits a verdict
    that is not in the Literal, this raises naming the value, instead of the
    value flowing into ``TranslationOutcome`` and being rejected later by
    Pydantic at a distance from its cause.
    """
    if value not in _TRANSLATION_OUTCOMES:
        raise ValueError(
            f"kelly gate produced outcome={value!r}, which is not a "
            f"PositionTranslationOutcome. Permitted: {sorted(_TRANSLATION_OUTCOMES)}. "
            "Either the gate gained a verdict this function does not model, or the "
            "two have drifted apart — both must be reconciled, not suppressed."
        )
    return cast("PositionTranslationOutcome", value)


#: The **one** constraint that produced the published notional.
#:
#: Named as a single member rather than a list because a list invites a caller
#: to intersect it and get an empty set where one constraint demonstrably
#: bound. ``"none"`` means no constraint was evaluated at all — it is the
#: companion of every ``refused_*`` outcome and must not be read as "nothing
#: bound".
#:
#: ``"risk_budget"`` is deliberately **absent**. It was in the first draft for a
#: reconciliation that turned out to be a unit error (Gate 4), and a member for
#: a path that cannot run is the declared-consumed-unreachable branch this
#: project keeps finding (D-045/D-046/D-048, O-53). A risk allocation that is
#: tighter than the position cap does **not** bind the number; it is published
#: as ``permitted_risk_contribution`` and flagged in the warnings, while the
#: binding constraint correctly names the cap that produced the figure.
#:
#: ``"missing_risk_budget"`` was in the draft too, and its removal is the
#: subtler decision. Keeping it meant that a thesis sized at the position cap
#: with no budget supplied reported ``"missing_risk_budget"`` — which **discarded
#: the fact that the cap had produced the number**, so a reader could no longer
#: tell whether any limit had bound. A missing budget is a fact about *which
#: checks ran*, not about which constraint produced the figure: it is carried by
#: ``permitted_risk_contribution == 1.0`` plus a warning, and this field reports
#: only the provenance of the number.
PositionBinding = Literal[
    "none",
    "kelly",
    "position_limit",
]

#: Section 9.3's mandated gate, carried on **every** output this section
#: produces, including the ones that refuse to size.
#:
#: It is a constant rather than a literal at each construction site because it
#: is a **contract term**, not a caveat: the sentence it embodies is the whole
#: difference between a reasoning layer and a signal generator (Section 1.1),
#: and a caller that strips it, or a future edit that rewords it at one site,
#: changes what the output promises without changing any number in it.
SIGN_OFF_REQUIRED = (
    "PROPOSAL ONLY — this is not an order and not an instruction to trade. "
    "Section 9.3 requires a human to sign off on any size before it is acted "
    "on, and execution remains a deliberate, separate decision rather than an "
    "automatic consequence of a thesis existing. No execution path in this "
    "system reads this value."
)

#: The fallback ``sizing_logic`` on a refusal that arrived with an empty one.
#:
#: ``TradeIdea.sizing_logic`` defaults to ``""`` and a stand-down built by
#: ``render_no_trade_thesis`` does always carry text — but a ``TradeIdea`` can
#: be constructed standalone (its own validator says so), so the empty string is
#: reachable, and copying it into the proposal would publish a refusal with no
#: statement of what was not done. This is the honest replacement: it says the
#: mechanism is "none", which is true on every refusal path, rather than
#: echoing the Phase-1 sentence (``SIZING_LOGIC_PHASE_1``), which would claim
#: human sizing happened when this function declined to size at all.
SIZING_LOGIC_REFUSED = "none — no size derived (see outcome and reason)"


class ProposedPosition(BaseModel):
    """What Section 9.3 emits: a proposed **notional fraction**, and its terms.

    The type is deliberately not ``float``. §9.3 asks for "a proposed notional
    size", and a bare number is exactly the shape that loses everything which
    makes the number safe to read: which sizing mechanism produced it, whether
    a limit bound it, whether the distribution underneath it was allowed to be
    used at all, and whether the risk budget agrees with it. Every one of those
    is a place this project has already measured a **silent** failure, so each
    is a field rather than a paragraph.

    Fields, and why each exists
    ---------------------------
    ``outcome``
        The **grader**. A consumer that branches on the size alone cannot tell
        "the book is bigger because the view is stronger" from "the book is
        bigger because nothing was checked" — the failure direction **O-86**
        names one layer up, where ``WATCH`` cannot distinguish "no edge" from
        "waiting". The six members are exhaustive over the refusal and sizing
        paths, and the ``Literal`` is what makes that checkable. "Exhaustive"
        is a claim this file has now had to **repair twice**: the shipped
        live check recounts the members against the outcomes the code actually
        produces, because the first draft declared seven and produced five
        (see Gate 3's comment and ``scripts/live_thesis_position_check.py``
        section 5).
    ``fraction_of_capital`` / ``requested_fraction_of_capital``
        The proposal and the pre-clip request, mirroring
        ``apply_fractional_kelly``'s contract. A binding cap **destroys the
        conviction information** (D-057's P5), so publishing only the clipped
        number makes four different views look identical.
    ``notional_fraction_after_constraints``
        The size after every constraint that **could** be evaluated. Today it
        always equals ``fraction_of_capital``: the only limits available to a
        function with no covariance are the position cap (already applied
        inside ``apply_fractional_kelly``) and the risk budget (published as a
        bound, not applied — Gate 4). It is a field rather than a synonym so
        that a future constraint which *does* reduce the number has somewhere
        to land without changing the contract, and so that its equality with
        ``fraction_of_capital`` is an observable fact rather than an assumption.
    ``binding_constraint``
        *Which* constraint produced the final number. This is the field a desk
        actually argues with, and inferring it from three numbers is how a
        position cap gets mistaken for a risk-budget limit.
    ``permitted_risk_contribution``
        The risk contribution the position is **allowed** to carry, given the
        portfolio-level budget: the allocation itself, or ``1.0`` when none was
        supplied. It is a *bound*, not a measurement, and — importantly — it is
        **not applied to the size**: converting a risk share into a notional
        needs a covariance this function does not hold, and the conversion was
        measured to be wrong by 6.7x when attempted. Read it beside
        ``binding_constraint``, never instead of it.
    """

    model_config = ConfigDict(extra="forbid")

    outcome: PositionTranslationOutcome = Field(
        description="Which gate or mechanism determined the proposal."
    )
    reason: str = Field(
        min_length=1,
        description=(
            "Plain-language statement of the outcome. Non-empty on EVERY path, "
            "including the refusals — a refusal without a reason is "
            "indistinguishable from a bug."
        ),
    )
    instrument: str = Field(
        description=(
            "The thesis's instrument, or the no-trade sentinel. Passed through "
            "unchanged (Section 22.12) and never substituted."
        ),
    )
    direction: str = Field(description='"long" | "short" | "n/a".')
    timeframe: str = Field(description="The thesis's stated horizon.")
    fraction_of_capital: float = Field(
        ge=0.0,
        description=(
            "The proposed notional, as a FRACTION of capital (0.08 = 8%). "
            "0.0 on every refusal path, where it is a DECISION rather than a "
            "missing value — read ``outcome`` before reading this."
        ),
    )
    requested_fraction_of_capital: float = Field(
        ge=0.0,
        description=(
            "What Kelly asked for before the position cap. Published so a "
            "binding cap does not flatten every confident view to one size "
            "(D-057's P5)."
        ),
    )
    notional_fraction_after_constraints: float = Field(
        ge=0.0,
        description=(
            "The size after every constraint that could be evaluated. Equals "
            "``fraction_of_capital`` today (the position cap is already applied "
            "upstream and the risk budget is a published bound, not an applied "
            "one). A limit may only ever LOWER it, so it is always <= "
            "``fraction_of_capital``."
        ),
    )
    binding_constraint: PositionBinding = Field(
        description="Which constraint produced ``notional_fraction_after_constraints``."
    )
    permitted_risk_contribution: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Share of total portfolio risk the position is allowed to carry, as "
            "a FRACTION in [0, 1]: the supplied allocation, or 1.0 when none was "
            "supplied. A BOUND, not a measurement, and NOT applied to the size — "
            "a risk share is not convertible to a notional without a covariance. "
            "1.0 means 'nothing bounded it', which is a different claim from 'it "
            "contributes all the risk'; read ``binding_constraint``."
        ),
    )
    scenario_sizing_permitted: bool = Field(
        description=(
            "Whether Section 25 permitted Kelly to read the scenario "
            "distribution at all. False whenever the outcome is a refusal, so "
            "the field can never read as permission that was not granted."
        ),
    )
    sizing_logic: str = Field(
        description=(
            "The mechanism, named. Never the Phase-1 human-determined sentence: "
            "a translated proposal that still says 'human-determined' is a "
            "label that outlived its truth."
        ),
    )
    requires_human_sign_off: bool = Field(
        default=True,
        description=(
            "Always True. Present because a caller reading this object in "
            "isolation must not have to find the warning in ``warnings`` to "
            "learn that it is a proposal."
        ),
    )

    @model_validator(mode="after")
    def _refusals_are_internally_consistent(self) -> ProposedPosition:
        """Keep the refusal shape and the arithmetic shape from contradicting.

        Two rules, both about claims that a reader would otherwise have to
        infer from numbers:

        1. **A refusal carries no size and no binding constraint.** An
           ``outcome`` starting ``"refused_"`` with a non-zero notional would
           be a proposal wearing a refusal's label — the same confusion
           ``trade_idea``'s no-trade validator prevents one layer up.
           **All THREE size fields are checked, and that is not redundancy.**
           The first version tested ``fraction_of_capital`` and
           ``notional_fraction_after_constraints`` and left
           ``requested_fraction_of_capital`` out — and because the two it did
           test are *always* written together (``notional_fraction_after_
           constraints`` equals ``fraction_of_capital`` on every path today),
           an ``and`` in place of the ``or`` still refused every input the
           suite exercised. Measured, the shipped guard accepted
           ``requested_fraction_of_capital=0.05`` on a refusal. The mutation
           sweep found the omission; the third field is what closes it. The
           ``requested`` number is the one a reader would mistake for the
           proposal's true size (D-057's P5), so it is the *most* dangerous of
           the three to leave unguarded.
        2. **The constrained notional is never larger than the unconstrained
           one.** Every constraint this function can evaluate reduces exposure,
           and a limit that increases it is not a limit. Checked with a
           tolerance because both numbers are rounded for publication and a
           strict comparison on rounded values can fail on a difference that
           does not exist. This invariant is what would catch a future edit
           that let the risk budget lever a position *up*.
        """
        if self.outcome.startswith("refused_"):
            if (
                self.fraction_of_capital != 0.0
                or self.requested_fraction_of_capital != 0.0
                or self.notional_fraction_after_constraints != 0.0
            ):
                raise ValueError(
                    f"outcome={self.outcome!r} is a refusal but a non-zero size "
                    f"was published (fraction_of_capital="
                    f"{self.fraction_of_capital!r}, requested_fraction_of_capital="
                    f"{self.requested_fraction_of_capital!r}, after_constraints="
                    f"{self.notional_fraction_after_constraints!r}). A refusal "
                    f"carries no size; publishing one makes the refusal look "
                    f"like a small position."
                )
            if self.binding_constraint != "none":
                raise ValueError(
                    f"outcome={self.outcome!r} is a refusal but "
                    f"binding_constraint={self.binding_constraint!r}. No "
                    f"constraint produced a size that was not produced."
                )
        if self.notional_fraction_after_constraints > self.fraction_of_capital + 1e-12:
            raise ValueError(
                f"notional_fraction_after_constraints="
                f"{self.notional_fraction_after_constraints!r} exceeds the "
                f"unconstrained fraction_of_capital={self.fraction_of_capital!r}. "
                f"Limits reduce exposure; a reconciliation step that raises it "
                f"is not applying a limit."
            )
        return self


class ThesisPositionInputs(BaseModel):
    """Everything Section 9.3's translation needs, and nothing it can invent.

    The spec's signature is ``translate_thesis_to_position(thesis, risk_budget)``
    — prose, no types. This is that signature typed, and the typing is where
    three of the section's defects live.

    ``risk_budget_target`` — why the *shares* and not the *book*
    ----------------------------------------------------------
    Section 9.3 says "portfolio-level risk budget config". There are two
    objects that could mean and they are **not** interchangeable:

    * ``compute_risk_parity_weights`` consumes a **list of targets across the
      whole book** and returns the weight vector for that book.
    * A *three-line thesis* needs **one instrument's share of portfolio risk**
      — not five weights — because the thesis knows about one instrument.

    Passing the whole book would be worse than awkward, it would be **wrong**:
    the function has no covariance, cannot estimate the book's total risk, and
    would therefore be unable to convert "12% of risk" into a notional. What it
    *can* do honestly is read the instrument's budgeted risk share as a
    **ceiling on its notional**, which is what this field is and what
    ``permitted_risk_contribution`` publishes. The conversion from a risk share
    to a notional happens inside ``compute_risk_parity_weights``, where a
    covariance exists, and **nowhere else** in this module.

    ``None`` is a supported input with a defined meaning
    --------------------------------------------------
    A bare ``MacroThesis`` — the common case, and the one §9.3's prose implies
    — has no budget attached. In that case the function still does its job
    (Kelly, limits, the sign-off gate) and records that **no portfolio-level
    check ran** — via ``permitted_risk_contribution == 1.0`` and a warning,
    because the binding constraint must keep naming what produced the number.
    That is a deliberate choice over raising: the risk budget is one of three inputs and
    the other two are sufficient to produce a *disclosed* proposal. Raising
    would instead make the integration look like it worked by making it
    impossible to call.

    It is **not**, however, allowed to be treated as "no limit": the published
    bound and the warning both say the check did not run, and the
    permitted contribution is reported as ``1.0`` ("nothing bounded this")
    rather than as a number the caller might mistake for an allocation.
    """

    model_config = ConfigDict(extra="forbid")

    thesis: MacroThesis = Field(description="The thesis to translate (Section 7.1).")
    risk_budget_target: RiskBudgetTarget | None = Field(
        default=None,
        description=(
            "This instrument's budgeted share of TOTAL PORTFOLIO RISK, as a "
            "fraction. ``None`` means no portfolio-level budget was supplied: "
            "the proposal is still produced and the outcome records that the "
            "risk-budget check did not run."
        ),
    )

    @model_validator(mode="after")
    def _budget_must_name_a_position_the_thesis_holds(self) -> ThesisPositionInputs:
        """Refuse a budget line for a *different* instrument than the thesis.

        This is the input-side twin of the refusals, and it is checked here
        rather than inside the function because the two failures are different
        in kind. A no-trade thesis with no budget is a **normal** input with a
        defined outcome; a live SPY thesis carrying a TLT budget line is a
        **caller error**, and no output of this function would be right.

        Without this check the failure is exactly the class this module keeps
        measuring: the function would size SPY against a budget intended for
        TLT, publish a plausible number, and name no instrument mismatch
        anywhere — a **false attribution of a risk limit**, which is worse than
        an unenforced one because the output claims the check passed.
        """
        target = self.risk_budget_target
        if target is None:
            return self
        idea = self.thesis.trade_idea
        if not idea.is_trade:
            # A budget for an instrument the thesis is not holding is a caller
            # error, but it is reported by the function (which owns the
            # refusal taxonomy) rather than raised here, so a whole batch of
            # theses cannot be lost to one stale budget line.
            return self
        if target.instrument != idea.instrument:
            raise ValueError(
                f"risk_budget_target names {target.instrument!r} but the thesis's "
                f"trade idea is {idea.instrument!r}. A budget line describes the "
                f"risk a NAMED instrument may carry; sizing {idea.instrument!r} "
                f"against {target.instrument!r}'s allocation would publish a "
                f"proposal that claims a portfolio check it did not perform, and "
                f"no field on the output would show the mismatch."
            )
        return self


def translate_thesis_to_position(inputs: ThesisPositionInputs) -> ModelResult:
    """Turn a thesis into a **proposed** notional size — never into an order.

    Section 9.3. The specification's own framing is the thing to preserve and
    the easiest thing to lose: this function is what Section 1.1 calls the
    reasoning layer's *output*, and it exists so that the answer to "how big?"
    is **stated** rather than left to whoever reads the thesis. It is not a
    signal generator, it does not place orders, and no execution path reads its
    result (``SIGN_OFF_REQUIRED``, carried on every result this function
    returns, including the refusals).

    The gates, in the order they are applied
    ----------------------------------------
    Each gate can only **stop** the proposal; none can enlarge it. The order is
    the cheapest-and-most-fundamental first, so the reason reported is the most
    fundamental one true of the input. There are **four**, not five: a gate that
    cannot fire is not a gate, and the one that used to be third was measured
    unreachable (see Gate 3's comment).

    1. **Is there a trade at all?** Two checks, because one is not enough.
       ``TradeIdea.is_trade`` covers a stand-down (``instrument == "NONE"``,
       Section 16.3) *and* the analytical-only sentinel
       (``ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT``, Section 22.12), and each
       gets a **different reason** — a thesis whose instrument is exactly the
       no-trade sentinel gets the Q6/Q7/Q8 explanation, anything else gets the
       production-universe one. Then ``ProductionUniverse.permits`` catches the
       case ``is_trade`` cannot: an instrument string that is neither sentinel
       but is still not executable. Measured on the first draft, a thesis
       carrying ``"HY credit spread"`` was refused as
       ``refused_scenarios_uncalibrated`` — right outcome, **wrong reason**,
       which reads as "calibrate your probabilities" when the truth is "the
       desk cannot put this on". The two sentinels are compared against their
       **constants**, never against a re-typed literal: they are different
       strings (``"NONE"`` and
       ``"ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT"``), and only the first is a
       value ``TradeIdea`` treats as a no-trade. See **O-53** and **O-93**.
    2. **May Kelly read the distribution?** Section 25's prohibition. Measured
       on every live thesis today: ``scenario_sizing_permitted`` is False
       because the probabilities are the specification's illustrative literals.
       A sizer that skipped this gate would put on a position derived from
       numbers nobody has calibrated, and the direction of that failure is
       *prudence-shaped* — the probabilities are small and the resulting size
       looks modest (D-057's failure direction, which is why it needs a gate
       rather than a comment). This gate subsumes the old "is there a
       distribution?" gate: ``scenario_sizing_permitted`` is a status-only
       predicate, and the schema ties the status to the distribution.
    3. **Kelly.** ``apply_fractional_kelly`` — the real growth-optimal Kelly
       over the full distribution, divided by the mandatory divisor, clipped
       against the hard position limit. Its own ``outcome`` is propagated, not
       re-derived from the numbers (the numbers cannot distinguish "Kelly said
       this" from "the cap said this" — D-057's P5).
    4. **The risk budget.** The instrument's budgeted share of portfolio risk.
       It is **published, not applied**, and this is the function's most
       important restraint — see the four costs below and the Gate 4 comment.
       A risk share cannot be converted to a notional without a covariance, and
       §9.3 supplies none.

    What the specification leaves implicit, and what each gap costs
    -------------------------------------------------------------
    1. **"A proposed notional size" has no unit in the spec text.** Section 4's
       ``RiskLimits`` are fractions of capital, ``apply_fractional_kelly``
       returns a fraction of capital, and a dollar figure would need a capital
       base that no object in this system holds. The unit is therefore a
       **fraction of capital**, stated on every field, because a notional with
       no base is the same class of defect as D-054's percent-in-a-fraction
       field — and this module has already paid for that one.
    2. **The spec assumes a risk budget always exists.** §9.3's prose takes
       "a ``MacroThesis`` + portfolio-level risk budget config" as though both
       were always present. Measured, a bare thesis has no budget, so the
       missing case is a **reachable normal input** and gets a named outcome
       rather than a silent pass.
    3. **The spec silently assumes a risk budget is convertible into a
       notional.** It is not, and the first implementation assumed it was:
       multiplying the capital fraction by the risk share produced **0.018**
       where the answer was 0.12. The tempting repair — "risk share >= notional
       share, so a risk budget is a notional bound" — is **false in 100% of
       20 000 probed covariance/weight draws**. The reconciliation is therefore
       not performed at all: the allocation is published, the sizing stays on
       the constraint that *is* expressible, and a warning names the gap. The
       invariant "no path may increase the size" is enforced by the output type
       itself, so a future edit that lets the budget lever a position *up*
       fails at construction rather than in a reader's head.
    4. **§16.2 Q12 asks "what portfolio exposures already exist?" and this
       function cannot answer it.** A real concentration check needs the axe's
       factor loadings (Module 18, Phase 5+) and the existing book. What ships
       is the **budget** half of Q12; the exposure half is not computed, is
       reported as not computed, and is **O-93**.

    Why this is not "wiring the risk axis into the builder"
    -----------------------------------------------------
    It is the function, not the wiring. ``thesis_layer/builder.py``'s note at
    its risk-axis paragraph says wiring would "build a Phase 4 layer early";
    Phase 4 is when that stops being early, but the **hook** is a separate
    increment from this one — the builder must gain a risk-budget parameter
    whose default preserves today's behaviour, and the orchestrator must supply
    a real book. Shipping the function first is what lets the hook be reviewed
    as a wiring change rather than as a wiring change *plus* an algorithm.

    Confidence is computed from stated facts (Section 22.8), and the two facts
    that dominate here are that the scenario probabilities are judgements
    rather than measurements and that the covariance needed to verify the risk
    ceiling is absent. The honest reading is the project's low bound rather
    than the midpoint.
    """
    settings = get_settings()
    thesis = inputs.thesis
    idea = thesis.trade_idea

    # -- Gate 1. Is there anything to size? ------------------------------
    # TWO checks, and the second one was missing from the first draft.
    #
    # (a) `is_trade` — the thesis's own statement. False for a stand-down
    #     (`instrument == "NONE"`, Section 16.3) AND for the explicit
    #     analytical-only sentinel (Section 22.12).
    # (b) `ProductionUniverse.permits` — the *universe's* statement, which is
    #     not the same check. `is_trade` compares against one sentinel string,
    #     so an instrument like `"HY credit spread"` passes it: the string is
    #     not `"NONE"`, so the thesis calls itself a trade. Measured on the
    #     first draft, that input produced `refused_scenarios_uncalibrated` —
    #     a **correct refusal for the wrong reason**, which reads as "your
    #     probabilities need calibrating" when the truth is "the desk cannot
    #     execute this at all". The universe check is what distinguishes them,
    #     and it is the same check `select_instrument` applies upstream.
    #
    # Both sentinels are compared against their CONSTANTS. `"NONE"` is a legal
    # `TradeIdea.instrument` value (O-53), so a re-typed literal here would be
    # the one place the false-executability risk O-53 names becomes real.
    universe = ProductionUniverse()
    if not idea.is_trade or idea.instrument == ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT:
        if idea.instrument == NO_PRODUCTION_INSTRUMENT:
            reason = (
                "The thesis is a NO-TRADE (instrument is the no-trade sentinel): "
                "Q6, Q7 or Q8 stood the sentence down, and Section 16.3 makes "
                "that a first-class outcome. There is nothing to size, and "
                "sizing it would manufacture the position the stand-down refused."
            )
        else:
            reason = (
                f"The thesis's instrument ({idea.instrument!r}) is outside the "
                f"production execution universe (Section 22.12), so it is an "
                f"analytical read rather than a position. Sizing it would "
                f"attribute a notional to an instrument the desk cannot put on."
            )
        return _refuse(
            thesis=thesis,
            outcome="refused_not_a_trade",
            reason=reason,
        )

    if not universe.permits(idea.instrument):
        return _refuse(
            thesis=thesis,
            outcome="refused_not_a_trade",
            reason=(
                f"{idea.instrument!r} is not in the production execution "
                f"universe (Section 22.12): it matches no permitted category "
                f"(rates, FX, broad equity indices) and/or matches an excluded "
                f"one. A trade idea whose instrument the desk cannot put on "
                f"cannot be sized — the correct result is the analytical read "
                f"the universe already gave, not a notional."
            ),
        )

    # -- Gate 2. Section 25: may Kelly read these probabilities? ---------
    if not thesis.scenario_sizing_permitted:
        return _refuse(
            thesis=thesis,
            outcome="refused_scenarios_uncalibrated",
            reason=(
                f"scenario_distribution_status="
                f"{thesis.scenario_distribution_status!r}. Section 25 permits "
                f"Kelly sizing only from a CALIBRATED, non-empty distribution; "
                f"these probabilities are not calibrated, so no size may be "
                f"derived from them. The thesis's own sizing_logic still applies "
                f"and a human may size it — but this function will not, because "
                f"a size derived from uncalibrated probabilities is an "
                f"uncalibrated size wearing a number."
            ),
        )

    # -- Gate 3. There is no gate 3. -------------------------------------
    #
    # Gate 3 was a check on the EMPTINESS of the distribution, and it was dead
    # code — for a different reason than the mass check it replaced, which is
    # why it survived that repair and needed its own.
    #
    # `MacroThesis._enforce_scenario_status_matches_distribution` is a
    # **two-directional** invariant:
    #
    #   * non-empty + `empty_no_trade`               -> raises
    #   * empty     + (`calibrated` | `unavailable`) -> raises
    #
    # So a `MacroThesis` that reaches this line is either (non-empty) or
    # (`empty_no_trade`, empty). Gate 2 then refuses everything that is not
    # `calibrated` — and `scenario_sizing_permitted` is defined as
    # `status == "calibrated"`, a **status-only** predicate that never inspects
    # the distribution. The surviving combination is therefore
    # `calibrated` + non-empty, which is exactly what gate 2 already
    # guaranteed, and `if not scenarios` can never fire.
    #
    # Measured, not argued: the 4 instruments x 3 statuses x {0, 1} branches
    # cross-product (24 cells) was enumerated, and `refused_no_scenarios` is
    # produced by **none** of them. Every empty distribution reaching this
    # function is either refused at construction or refused by gate 2. The
    # builder confirms the same fact from the other side — it never produces an
    # empty `scenario_distribution` at all.
    #
    # The branch is therefore removed rather than left as a safety net, on the
    # same rule as the mass check: one rule, one enforcement point, at the
    # object that owns the invariant. A duplicate that cannot run is not a
    # safety net; it is a claim that this function checks something it does
    # not, and it makes `refused_no_scenarios` a `Literal` member that no input
    # can produce — the project's most frequently found defect class
    # (D-045/D-046/D-048, O-53). The member is removed with it. If a future
    # caller can construct an empty calibrated distribution, the repair is to
    # relax `MacroThesis`'s invariant — not to reinstate a branch here that the
    # schema has already made unreachable.
    #
    # `apply_fractional_kelly` retains its own empty-`scenarios` guard (a
    # negative-input contract check), so the primitive is still defended at its
    # own boundary; nothing about that contract changes.

    # -- Gate 3. Kelly, with the mandatory fractional divisor. -----------
    limits = RiskLimits.from_settings()
    kelly = apply_fractional_kelly(
        KellyInputs(
            scenarios=list(thesis.scenario_distribution),
            payoff_unit=_KELLY_UNIT,
            limits=limits,
        )
    )
    kelly_value = kelly.value
    assert isinstance(kelly_value, dict)
    fraction = float(kelly_value["fraction_of_capital"])
    requested = float(kelly_value["requested_fraction_of_capital"])
    kelly_outcome = str(kelly_value["outcome"])

    # `no_edge` is Kelly's own refusal and is NOT the same claim as any of the
    # three above: it is a decision that no positive size has positive expected
    # log growth. Returned before the risk budget is consulted, because a
    # budget cannot admit a position Kelly declined to take.
    if kelly_outcome == "no_edge":
        return _refuse(
            thesis=thesis,
            outcome="refused_no_edge",
            reason=(
                "The growth-optimal fraction is ZERO: no positive size has "
                "positive expected log growth for this distribution. This is a "
                "decision to take no position, not a missing value — a positive "
                "expected VALUE is not sufficient (LTCM's positions were "
                "positive-EV)."
            ),
            scenario_sizing_permitted=True,
        )

    # -- Gate 4. The portfolio-level risk budget. ------------------------
    #
    # WHAT THIS GATE CAN AND CANNOT DO, because the first implementation of it
    # was wrong in exactly the direction this module keeps measuring.
    #
    # A `RiskBudgetTarget` allocates **risk**, and a notional is **capital**.
    # Converting one to the other needs a covariance — `RC_i = w_i(Sigma w)_i /
    # sigma_p^2` — and this function has none. The first version of this gate
    # therefore did the arithmetic anyway: `multiplier = min(1.0, risk_share)`,
    # which multiplies a capital fraction by a risk fraction. Measured on the
    # shipped configuration it returned **0.018** for a 12% risk allocation
    # against a 15% position cap, where the answer is 0.12 — a **6.7x**
    # understatement that is invisible in the output, because 0.018 is a
    # perfectly plausible position size. D-054/D-056/D-057's failure direction,
    # reached by a different route.
    #
    # The tempting repair is worse. "A position's risk share is at least its
    # notional share, so a risk budget is a notional bound" is the intuition
    # that would justify `notional <= risk_budget`, and it is **false**.
    # Probed over 20 000 random positive-definite covariances and random long-only
    # weights, the claim fails in **100%** of trials (largest single violation
    # 1792x): a 33.3% dollar weight in a 16%-vol / 14%-vol / 15%-vol book
    # contributed **29.9% / 27.0% / 43.1%** of the risk, and a 20% dollar weight
    # in gold-vs-equities contributed **6.8%**. Risk share is a property of the
    # covariance, not of the weight, in **both** directions.
    #
    # So there is no honest numeric reconciliation, and this gate does the two
    # things that ARE honest instead:
    #
    #   1. **It states the bound** — `permitted_risk_contribution` is the
    #      allocation, and `binding_constraint` says whether it was the risk
    #      budget or the position cap that produced the *number*.
    #   2. **It refuses only what is unambiguously unaffordable.** A risk
    #      allocation of zero, or one smaller than the position cap, means the
    #      book has budgeted less risk to this instrument than the cap would
    #      permit it to take — and since the two are not convertible, the only
    #      safe reading of "I have less risk budget than my notional cap" is to
    #      hand the sizing back to the constraint that IS expressible, which is
    #      the position cap, having **named** that the risk budget is tighter.
    #
    # The consequence is disclosed rather than hidden: the risk budget does
    # **not** reduce the number, and the output says so on every path where it
    # could not — which is what distinguishes this from the silent 6.7x error
    # the first version shipped.
    target = inputs.risk_budget_target
    permitted = 1.0
    # The binding constraint names what produced the NUMBER, and the missing
    # budget is tracked SEPARATELY from it. An earlier draft assigned
    # `binding = "missing_risk_budget"` and thereby discarded the fact that the
    # position cap had produced the figure -- so a thesis sized at the cap
    # reported "no budget" and a reader could not tell whether a limit had
    # bound at all. Two facts, two fields.
    binding: PositionBinding = (
        "position_limit" if kelly_outcome == "clipped_by_position_limit" else "kelly"
    )
    risk_budget_missing = target is None
    budget_warnings: list[str] = []
    risk_budget_is_tighter = False

    if target is None:
        budget_warnings.append(
            "No portfolio-level risk budget was supplied, so the Q12 check did "
            "NOT run: nothing verified that this position's risk fits the "
            "book's existing allocation. The size below is constrained only by "
            "the position cap — read this as 'unchecked', not as 'checked and "
            "clear'."
        )
    else:
        target_share = target.target_risk_contribution_pct
        # A zero allocation is its own outcome rather than a multiplier of
        # zero: "the book allocated this instrument no risk" is a different
        # fact from "the allocation reduced the size", and a consumer repairing
        # one should not be shown the other.
        if target_share <= 0.0:
            return _refuse(
                thesis=thesis,
                outcome="refused_no_risk_budget",
                reason=(
                    f"risk_budget_target allocates {target.instrument} "
                    f"{target_share!r} of total portfolio risk. A zero "
                    f"allocation is the book saying this instrument carries no "
                    f"risk budget, so no notional may be attributed to it — a "
                    f"zero budget is a decision, not a small number."
                ),
                scenario_sizing_permitted=True,
            )
        allowed_share = limits.max_position_pct_of_portfolio
        permitted = target_share
        risk_budget_is_tighter = target_share < allowed_share
        budget_warnings.append(
            f"The risk budget did NOT scale the size, and that is deliberate. "
            f"`risk_budget_target` allocates {target.instrument} {target_share!r} "
            f"of total portfolio RISK; the published size is a fraction of "
            f"CAPITAL. Converting one to the other needs the instrument's "
            f"volatility and its correlations with the book's other holdings, "
            f"and Section 9.3 gives this function no covariance — so the "
            f"conversion is not performed rather than approximated. The "
            f"allocation is published as `permitted_risk_contribution` for a "
            f"caller that holds one (use `compute_risk_parity_weights`, which "
            f"does)."
        )
        if risk_budget_is_tighter:
            budget_warnings.append(
                f"The risk allocation ({target_share:.4f}) is TIGHTER than the "
                f"position cap ({allowed_share:.4f}), so the book has budgeted "
                f"less risk to this instrument than the cap would let it take. "
                f"Because the two are not convertible without a covariance, the "
                f"size is left on the expressible constraint (the cap) and this "
                f"flag is raised — the position cap governs the NUMBER, and the "
                f"risk budget is the binding POLICY. A caller who wants the risk "
                f"budget to govern the number must supply a covariance."
            )

    final_fraction = fraction
    outcome = _as_translation_outcome(kelly_outcome)

    warnings = [
        SIGN_OFF_REQUIRED,
        *kelly.warnings,
        *budget_warnings,
    ]
    warnings.append(
        "This function sizes ONE instrument against a stated budget. It does "
        "NOT verify the resulting book's factor concentration (Module 18 / "
        "Section 16.2 Q12's exposure half), which needs the axe's loadings and "
        "is Phase 5+. Recorded as O-93."
    )

    confidence = compute_confidence(
        ConfidenceInputs(
            # The distribution is calibrated (gate 2 passed) but the risk
            # ceiling is unverifiable here, because verifying it needs a
            # covariance this function does not hold. That is a data gap in
            # the sense Section 5.4 means, so the flag is set.
            data_quality_flags_present=risk_budget_missing,
            is_heuristic_not_calibrated=False,
            depends_on_unobservable=False,
        )
    )

    if binding == "position_limit":
        interpretation = (
            f"Proposed {final_fraction:.4f} of capital in {idea.instrument} "
            f"({idea.direction}, {idea.timeframe}) — limited by the "
            f"{limits.max_position_pct_of_portfolio:.4f} position cap"
        )
    else:
        interpretation = (
            f"Proposed {final_fraction:.4f} of capital in {idea.instrument} "
            f"({idea.direction}, {idea.timeframe}) — Kelly size, no limit bound"
        )
    if risk_budget_missing:
        interpretation += "; portfolio-level risk check NOT run (no budget)"
    if risk_budget_is_tighter:
        interpretation += (
            f"; the {target_share:.4f} risk allocation is TIGHTER than the "
            f"{limits.max_position_pct_of_portfolio:.4f} position cap but is not "
            f"convertible to a notional without a covariance, so it is published "
            f"as a bound rather than applied"
        )

    reason_parts = [
        f"Kelly scaled by the mandatory 1/{settings.kelly.divisor:.1f} fractional divisor",
    ]
    if binding == "position_limit":
        reason_parts.append("then clipped by the position cap")
    if risk_budget_is_tighter:
        reason_parts.append(
            f"then NOT reduced by the {target_share:.4f} risk allocation, which "
            f"is not convertible to a notional without a covariance"
        )
    elif target is not None:
        reason_parts.append(
            f"then left unconstrained by the {target_share:.4f} risk allocation, "
            f"which is looser than the position cap"
        )
    if risk_budget_missing:
        reason_parts.append("with no portfolio-level risk check run (no budget)")
    reason = "; ".join(reason_parts) + "."

    proposal = ProposedPosition(
        outcome=outcome,
        reason=reason,
        instrument=idea.instrument,
        direction=idea.direction,
        timeframe=idea.timeframe,
        fraction_of_capital=round(final_fraction, 10),
        requested_fraction_of_capital=round(requested, 10),
        notional_fraction_after_constraints=round(final_fraction, 10),
        binding_constraint=binding,
        permitted_risk_contribution=round(permitted, 10),
        scenario_sizing_permitted=True,
        sizing_logic=(
            f"fractional_kelly(scenarios, confidence) / "
            f"{settings.kelly.divisor:.1f}"
            + (
                ", risk allocation published as a bound (not convertible without a covariance)"
                if target is not None
                else ", no portfolio risk budget supplied"
            )
        ),
    )

    return ModelResult(
        model_name="translate_thesis_to_position",
        country=thesis.country,
        as_of=utc_now(),
        value=proposal.model_dump(mode="json"),
        confidence=confidence,
        interpretation=interpretation,
        context=(
            "Section 9.3: a MacroThesis translated into a PROPOSED notional, "
            "still requiring human sign-off. This is the reasoning layer's "
            "output boundary — it reports a size and NEVER places an order, and "
            "no execution path reads this value."
        ),
        inputs_used=["thesis", "risk_budget_target"],
        warnings=warnings,
        data_quality_flags_present=risk_budget_missing,
    )


def _refuse(
    *,
    thesis: MacroThesis,
    outcome: PositionTranslationOutcome,
    reason: str,
    scenario_sizing_permitted: bool = False,
) -> ModelResult:
    """Every refusal path, in one place, so none of them can drift.

    Four distinct refusals leave this function with the same *shape* and
    different *reasons*, and the shape is what a consumer branches on. Building
    them through one constructor is not tidiness: it is what guarantees the two
    properties the refusals exist to have — a non-empty reason on every path,
    and a zero size that is never mistakable for a small position.

    ``scenario_sizing_permitted`` defaults to ``False`` and is passed ``True``
    only by the two refusals that occur **after** Section 25's gate was passed
    (no-edge and no-risk-budget). The field means "Kelly was allowed to read the
    distribution", so reporting ``False`` on a path where it was would
    understate what the function did, and reporting ``True`` on a path where it
    was not is exactly the false permission this field exists to rule out.
    """
    idea = thesis.trade_idea
    proposal = ProposedPosition(
        outcome=outcome,
        reason=reason,
        instrument=idea.instrument,
        direction=idea.direction,
        timeframe=idea.timeframe,
        fraction_of_capital=0.0,
        requested_fraction_of_capital=0.0,
        notional_fraction_after_constraints=0.0,
        binding_constraint="none",
        # No constraint bound anything, because nothing was sized. 1.0 is
        # "unbounded" here and the binding constraint above is what says
        # whether any check ran at all.
        permitted_risk_contribution=1.0,
        scenario_sizing_permitted=scenario_sizing_permitted,
        sizing_logic=idea.sizing_logic or SIZING_LOGIC_REFUSED,
    )

    return ModelResult(
        model_name="translate_thesis_to_position",
        country=thesis.country,
        as_of=utc_now(),
        value=proposal.model_dump(mode="json"),
        confidence=compute_confidence(
            ConfidenceInputs(
                # A refusal is the absence of a size, not a measurement of one,
                # so its confidence reads at the floor rather than at the base.
                data_quality_flags_present=True,
                is_heuristic_not_calibrated=True,
                depends_on_unobservable=False,
            )
        ),
        interpretation=f"NO PROPOSAL — {outcome}: {reason}",
        context=(
            "Section 9.3's translation declined to produce a size. The refusal "
            "is the answer: Section 1.1's reasoning layer reports that no clean "
            "position follows from this thesis rather than manufacturing one."
        ),
        inputs_used=["thesis", "risk_budget_target"],
        warnings=[SIGN_OFF_REQUIRED],
        data_quality_flags_present=True,
    )
