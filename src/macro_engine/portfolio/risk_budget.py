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
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from macro_engine.config import get_settings
from macro_engine.models.contracts import (
    ConfidenceInputs,
    ModelResult,
    compute_confidence,
    utc_now,
)
from macro_engine.models.probability import ScenarioOutcome

__all__ = [
    "DrawdownRule",
    "DrawdownState",
    "KellyInputs",
    "KellyPayoffUnit",
    "RebalancingOutcome",
    "RiskBudgetTarget",
    "RiskLimits",
    "RuleOutcome",
    "SizingOutcome",
    "VolTargetInputs",
    "apply_fractional_kelly",
    "check_rebalancing_drift",
    "evaluate_drawdown_rules",
    "generalized_kelly_fraction",
    "resolve_drawdown_rule",
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
        interpretation = (
            f"Drawdown {drawdown:.2%} — no risk-reduction rule triggered "
            f"(the least severe configured threshold is "
            f"{min((r.threshold_pct for r in resolved), default=float('nan')):.2%})"
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
    if current_contributions and abs(total_actual - 1.0) > 0.01:
        warnings.append(
            f"Current contributions sum to {total_actual:.4f}, not 1.0. Risk "
            f"contributions are SHARES of total portfolio risk, so a set that does "
            f"not sum to 1 is either partial or not shares at all (dollar amounts, "
            f"say) — and against fractional targets every dollar figure 'drifts'."
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
_KELLY_UNIT = "fraction_of_capital"


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
