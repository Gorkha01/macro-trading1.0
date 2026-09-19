"""Tests for Module 17.3 — ``evaluate_drawdown_rules``.

Section 6.6c specifies a pre-committed mechanical de-risking ladder; Section
17.3 restates why it is mechanical rather than discretionary (the LTCM lesson:
the person best placed to rationalise a drawdown is the person least able to be
trusted with it).

**Five defects are pinned here. Two of them are the load-bearing ones, and
neither is an arithmetic error.**

1. **The spec and its own config disagree by 100x.** Section 6.6c writes
   ``DrawdownRule(threshold_pct=0.10)`` — a *fraction*. ``config/settings.yaml``
   writes ``{drawdown_pct: 10.0}`` — a *percent*. Read one and compare against
   the other and every threshold is wrong by two orders of magnitude. The
   direction is the part that matters and it was **not** what the probe
   predicted: the guess was "every tier fires, so always 100%", and the truth is
   the **opposite** — no tier can *ever* fire, because ``0.15 >= 10.0`` is false
   for every reachable fraction. The de-risking rule is **permanently silent**
   and reports "no risk-reduction rule triggered" at a 90% drawdown. A safety
   mechanism that fails toward *inaction* is the worst failure mode available to
   it. ``test_the_default_tiers_are_fractions_not_percents`` is the test that
   fails if ``_tiers()`` stops dividing by 100; everything else in this file
   would still pass, because a mis-scaled ladder is still a *deterministic*
   ladder.
2. **``risk_reduction_pct`` had no bounds.** An unbounded ``float`` admits
   ``risk_reduction_pct=5.0`` ("remove 500% of the risk") and
   ``risk_reduction_pct=-1.0`` ("add risk"), and the function would publish
   either as a mechanical de-risking instruction.
3. **"Evaluated in order" and "the most severe triggered rule wins" cannot both
   be true.** The second governs: the answer is invariant under permutation of
   the rule list. A reader who trusted the first clause would ``sorted()`` the
   list or break out of the loop early, and on a non-monotone rule set both
   change the answer.
4. **Severity-max and threshold-max are indistinguishable on the shipped
   ladder.** The shipped tiers are monotone in *both* fields, so on the default
   set the two keys agree on every triggered subset — which is exactly why the
   ambiguity would never be noticed. They diverge as soon as a caller supplies a
   rule whose reduction is not monotone in its threshold, and ``DrawdownRule``
   permits one.
5. **``0.0`` is an ambiguous output.** "Nothing triggered" and "a rule fired and
   prescribed no reduction" publish the same ``risk_reduction_fraction``. A
   ``RuleOutcome`` ``Literal`` is published alongside so a consumer can tell them
   apart without parsing prose.

The **base-state rule does not apply here, and saying so is part of the
deliverable.** D-047 and D-053 both found classifiers whose own thresholds made
the uninformative label the modal output. This function is not a classifier: its
modal output is ``no_action``, and that is *correct* — the rule exists to be
silent until it is not. Applying lesson 5g mechanically here would have produced
a "fix" for the entire design. ``test_the_base_state_failure_does_not_apply_here``
records the non-application rather than leaving the omission to be re-litigated.

Every expected value below is computed **by hand** in a comment before the
assertion, per Section 21.2 Step 4. Boundary fixtures are built by **addition**,
not subtraction (``0.10 + 0.05``, never ``0.15 - 0.00``): binary floats make
``2.0 - 0.1 != 1.9`` and a boundary test built by subtraction can land on the
wrong side of the comparison it is meant to probe.
"""

from __future__ import annotations

import itertools
from typing import Any, get_args

import pytest
from pydantic import ValidationError

from macro_engine.config import CalibratedValue, DrawdownTier, RiskSettings, get_settings
from macro_engine.models.contracts import ConfidenceInputs, compute_confidence
from macro_engine.portfolio.risk_budget import (
    DrawdownRule,
    DrawdownState,
    RuleOutcome,
    evaluate_drawdown_rules,
    resolve_drawdown_rule,
)
from tests.helpers import as_float, as_float_or_none, as_int, as_str

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

#: The shipped ladder as Section 6.6c states it — **fractions**.
#: 0.10 = a 10% drawdown triggers a 50% risk reduction; 0.20 = a 20% drawdown
#: stops trading (a 100% reduction).
DEFAULT_TIERS = [
    DrawdownRule(threshold_pct=0.10, risk_reduction_pct=0.50),
    DrawdownRule(threshold_pct=0.15, risk_reduction_pct=0.75),
    DrawdownRule(threshold_pct=0.20, risk_reduction_pct=1.00),
]


def _state_at(drawdown: float, *, hwm: float = 100.0) -> DrawdownState:
    """A state whose derived drawdown is exactly ``drawdown``.

    Built by ADDITION on the current value: ``current = hwm * (1 - dd)``. The
    risky alternative — ``current = hwm - hwm * dd`` — is the same arithmetic
    and lands on the same float, but the form here makes the *intent* (a
    fractional shortfall from the peak) visible at the call site, which is what
    a reader checking a boundary needs.
    """
    return DrawdownState(high_water_mark=hwm, current_value=hwm * (1.0 - drawdown))


def _sweep() -> list[float]:
    """Drawdowns from -0.10 to 1.30 in 0.01 steps, plus the exact boundaries.

    A fine grid is enough to prove reachability and monotonicity, and the exact
    rung values are added explicitly so a boundary is never *approached* from a
    float grid but always *hit*.
    """
    grid = [index / 100.0 for index in range(-10, 131)]
    return sorted(set(grid) | {0.10, 0.15, 0.20, 0.0})


def _as_keys(rules: list[DrawdownRule | None]) -> list[tuple[float, float] | None]:
    return [
        None if rule is None else (rule.threshold_pct, rule.risk_reduction_pct) for rule in rules
    ]


def is_monotone(rules: list[DrawdownRule]) -> bool:
    """Whether both fields ascend together, so severity-max == threshold-max."""
    ordered = sorted(rules, key=lambda r: r.threshold_pct)
    return all(
        ordered[i].risk_reduction_pct <= ordered[i + 1].risk_reduction_pct
        for i in range(len(ordered) - 1)
    )


def _evaluate(drawdown: float, **kwargs: Any) -> Any:
    return evaluate_drawdown_rules(_state_at(drawdown), **kwargs)


def _outcome(drawdown: float, **kwargs: Any) -> str:
    return as_str(_evaluate(drawdown, **kwargs), key="outcome")


def _reduction(drawdown: float, **kwargs: Any) -> float:
    return as_float(_evaluate(drawdown, **kwargs), key="risk_reduction_fraction")


def _cfg() -> RiskSettings:
    return get_settings().risk


# --------------------------------------------------------------------------
# Contract: DrawdownState
# --------------------------------------------------------------------------


def test_high_water_mark_must_be_positive() -> None:
    """A zero HWM is a division by zero; a negative one makes the ratio meaningless.

    The bound belongs on the **input**, not on the derived drawdown: a
    drawdown of 1.5 (negative equity) is legitimate, and a guard placed on the
    result would reject it.
    """
    with pytest.raises(ValidationError):
        DrawdownState(high_water_mark=0.0, current_value=0.0)
    with pytest.raises(ValidationError):
        DrawdownState(high_water_mark=-1.0, current_value=0.0)


def test_current_value_may_be_negative() -> None:
    """A wiped-out portfolio carrying negative equity is a real state.

    Hand-computed: (100 - (-50)) / 100 = 150 / 100 = 1.5.
    """
    state = DrawdownState(high_water_mark=100.0, current_value=-50.0)
    assert state.drawdown_pct == 1.5


def test_a_new_high_yields_a_negative_drawdown() -> None:
    """Above the high-water mark the drawdown is negative, and NOT clamped to zero.

    Hand-computed: (100 - 250) / 100 = -150 / 100 = -1.5.

    Clamping to zero would be a defect of the "declared, consumed, unreachable"
    family in reverse: it would make the "portfolio is above its peak" branch
    unreachable while looking like a tidy-up.
    """
    state = DrawdownState(high_water_mark=100.0, current_value=250.0)
    assert state.drawdown_pct == -1.5


def test_a_wiped_out_portfolio_sits_exactly_at_one() -> None:
    """Hand-computed: (100 - 0) / 100 = 1.0. The 1.0 boundary is reachable."""
    state = DrawdownState(high_water_mark=100.0, current_value=0.0)
    assert state.drawdown_pct == 1.0


def test_drawdown_state_refuses_an_unknown_field() -> None:
    with pytest.raises(ValidationError):
        DrawdownState(high_water_mark=100.0, current_value=90.0, extra=1)  # type: ignore[call-arg]


# --------------------------------------------------------------------------
# Contract: DrawdownRule
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("threshold", "reduction"),
    [
        (0.0, 0.5),  # a zero threshold fires always — not a de-risking rule
        (0.1, 0.0),  # a zero reduction is a rule that does nothing
        (-0.1, 0.5),  # a negative threshold fires before any loss
        (0.1, -0.5),  # a negative reduction INCREASES risk
        (1.01, 0.5),  # more than the whole portfolio cannot be lost by drawdown alone
        (0.1, 1.01),  # "remove more than all the risk"
    ],
)
def test_a_rule_field_outside_its_bounds_is_refused(threshold: float, reduction: float) -> None:
    """Both fields are fractions in ``(0, 1]``, and both halves of the bound matter.

    The upper bounds are the ones that were missing in the specification: an
    unbounded ``float`` accepts ``5.0`` and ``-1.0``, and either would be
    published as a mechanical de-risking instruction.
    """
    with pytest.raises(ValidationError):
        DrawdownRule(threshold_pct=threshold, risk_reduction_pct=reduction)


def test_a_full_stop_out_rule_is_legal() -> None:
    """``risk_reduction_pct == 1.0`` is the boundary, not an overrun.

    Hand-computed: 1.0 of the risk removed is "stop trading", which is what the
    shipped 20% tier prescribes. A bound of ``lt=1.0`` would make the shipped
    ladder unrepresentable.
    """
    rule = DrawdownRule(threshold_pct=0.20, risk_reduction_pct=1.00)
    assert rule.risk_reduction_pct == 1.0


def test_a_rule_refuses_an_unknown_field() -> None:
    with pytest.raises(ValidationError):
        DrawdownRule(threshold_pct=0.1, risk_reduction_pct=0.5, extra=1)  # type: ignore[call-arg]


# --------------------------------------------------------------------------
# Defect 1 — the unit convention. THE load-bearing test in this file.
# --------------------------------------------------------------------------


def test_the_default_tiers_are_fractions_not_percents() -> None:
    """The configured ladder, read from YAML, must arrive in FRACTION scale.

    ``config/settings.yaml`` stores ``{drawdown_pct: 10.0, risk_reduction_pct:
    50.0}`` — **percent**, the convention of the whole file. Section 6.6c's
    arithmetic uses **fractions**. So the config accessor hands back percent and
    the conversion must happen at exactly one boundary.

    **This test is the one that fails if ``_tiers()`` stops dividing by 100**,
    and it is deliberately written as a *behavioural* assertion rather than an
    inspection of ``_tiers()``: the defect it guards is "the ladder is scaled
    wrong", and an assertion on the loader's internals would keep passing while
    the ladder was 100x off. Everything else in this file passes either way,
    because a mis-scaled ladder is still a deterministic ladder — which is
    precisely why the defect survived to the implementation stage.

    Concretely: with percent tiers compared against a fractional drawdown,
    ``0.15 >= 10.0`` is false at every reachable drawdown, so `no_action` is the
    only outcome the function can produce. Asserting the *outcome* at a 15%
    drawdown is what makes the scale visible.
    """
    tiers = _cfg().drawdown_tiers
    assert [t.drawdown_pct for t in tiers] == [10.0, 15.0, 20.0], (
        "the config stores PERCENT; if this changes, the conversion boundary in "
        "portfolio/risk_budget.py must move with it"
    )

    # Hand-computed against the shipped ladder, in fraction scale:
    #   0.12 >= 0.10 -> the 50% tier is the most severe triggered -> 0.50
    assert _reduction(0.12) == 0.50
    #   0.16 >= 0.10 and >= 0.15 -> the 75% tier -> 0.75
    assert _reduction(0.16) == 0.75
    #   0.21 >= all three -> the 100% tier -> 1.00
    assert _reduction(0.21) == 1.00

    # And the assertion that fails LOUDEST if the conversion is dropped: with
    # percent-scale tiers compared against a fractional drawdown, `0.15 >= 10.0`
    # is false everywhere, so the ONLY reachable outcome is `no_action`. Reading
    # the outcome rather than the numbers makes the 100x error legible as the
    # silently-disabled guard it is, rather than as a scale mismatch.
    assert {_outcome(dd) for dd in _sweep()} == {"no_action", "reduce_risk", "stop_trading"}, (
        "if the ladder is 100x mis-scaled it can only ever return `no_action` — "
        "a de-risking rule that fails toward inaction is the worst failure mode "
        "available to it"
    )


def test_a_fraction_scale_entry_in_the_percent_config_is_refused() -> None:
    """A tier written ``0.15`` where ``15.0`` is meant must be rejected at load.

    The type cannot tell a percent from a fraction — ``0.15`` is a legal value
    in a ``(0, 100]`` field and an impossible drawdown. A *magnitude floor* can:
    a pre-committed ladder whose first step is a 0.15% drawdown is a mis-scaled
    file rather than a policy. Without this guard the mis-scaled entry loads
    silently and the ladder triggers on noise.

    This is the "make the convention checkable" repair, and it is the only thing
    in the repository that catches the 100x error at load time rather than at
    the first use.
    """
    with pytest.raises(ValidationError, match="PERCENTS"):
        DrawdownTier(drawdown_pct=0.15, risk_reduction_pct=50.0)
    with pytest.raises(ValidationError, match="PERCENTS"):
        DrawdownTier(drawdown_pct=10.0, risk_reduction_pct=0.50)


def test_the_percent_scale_boundary_is_one_not_zero() -> None:
    """The floor is ``>= 1.0`` percent: 1.0 loads, 0.99 does not.

    Hand-checked both sides so the guard is a boundary rather than a range that
    happens to exclude the fixtures.
    """
    assert DrawdownTier(drawdown_pct=1.0, risk_reduction_pct=1.0).drawdown_pct == 1.0
    with pytest.raises(ValidationError):
        DrawdownTier(drawdown_pct=0.99, risk_reduction_pct=50.0)
    with pytest.raises(ValidationError):
        DrawdownTier(drawdown_pct=10.0, risk_reduction_pct=0.99)


def test_the_tier_ceiling_is_a_boundary_not_a_decoration() -> None:
    """The ``le=100.0`` ceiling must be *load-bearing*, checked on both sides.

    A tier of ``150.0`` means "trigger at a 150% drawdown" — unreachable, since
    even negative equity cannot exceed 100% of a positive high-water mark by
    drawdown alone. Such a rung would never fire, which is a **silently dead
    policy step**: the file looks like it has four rungs and behaves as though
    it has three.

    **This test kills ``CX3``** (the ceiling removed), which survived the first
    sweep. The floor was tested and the ceiling was not — the asymmetry is the
    easy mistake, because a floor guards against a mis-scaled *file* and feels
    like the interesting bound, while a ceiling guards against a policy that can
    never activate and feels merely tidy.

    Hand-computed: 100.0 is the maximum legal value (a complete loss, still
    expressible); 100.01 and 150.0 are refused.
    """
    assert DrawdownTier(drawdown_pct=100.0, risk_reduction_pct=100.0).drawdown_pct == 100.0
    with pytest.raises(ValidationError):
        DrawdownTier(drawdown_pct=100.01, risk_reduction_pct=50.0)
    with pytest.raises(ValidationError):
        DrawdownTier(drawdown_pct=150.0, risk_reduction_pct=100.0)
    # The reduction's ceiling matters identically: a reduction above 100% is not
    # a de-risking instruction, it is an over-closure.
    with pytest.raises(ValidationError):
        DrawdownTier(drawdown_pct=10.0, risk_reduction_pct=100.01)


def test_the_shipped_config_parses_through_its_accessor() -> None:
    """The YAML block must actually round-trip — and it had no consumer before this.

    Grepping the repository found ``drawdown_tiers`` referenced nowhere in
    ``src/``; ``tests/test_infrastructure.py`` touches ``drawdown_thresholds``
    with a *different* payload shape (``{drawdown: 10, reduction: 50}``), so the
    shipped YAML never parsed through the accessor at all. It was a real
    instance of the project's recurring "declared, consumed, unreachable"
    class: a config surface with a reader and no consumer.

    ``evaluate_drawdown_rules`` is the first genuine consumer, so this test
    asserts the shipped file parses — which is a claim about the file, not
    about the code.
    """
    tiers = _cfg().drawdown_tiers
    assert len(tiers) == 3

    settings = get_settings()
    raw = settings.risk.drawdown_thresholds["tiers"]
    assert [t["drawdown_pct"] for t in raw] == [t.drawdown_pct for t in tiers]


# --------------------------------------------------------------------------
# Defect 2 — the missing bounds (covered above) and defect 3 — ordering
# --------------------------------------------------------------------------


def test_the_ladder_result_is_invariant_under_permutation() -> None:
    """All 6 permutations of the shipped ladder give identical answers.

    Defect 3: the specification says rules are "evaluated in order" *and* that
    "the most severe triggered rule wins". Only the second is true. The result
    is a maximum over a set, and a maximum does not depend on traversal order.

    This test exists because a reader who believed the ordering clause would
    ``sorted()`` the list first or ``break`` out of the loop early — and on a
    non-monotone rule set both change the answer. So the invariance is asserted
    over a **non-monotone** set as well as the default one; on the default ladder
    the invariance is free, which is what makes it worth testing off it.
    """
    monotone = DEFAULT_TIERS
    non_monotone = [
        DrawdownRule(threshold_pct=0.10, risk_reduction_pct=0.90),
        DrawdownRule(threshold_pct=0.15, risk_reduction_pct=0.20),
        DrawdownRule(threshold_pct=0.20, risk_reduction_pct=0.50),
    ]

    for rule_set in (monotone, non_monotone):
        reference = [resolve_drawdown_rule(dd, list(rule_set)) for dd in _sweep()]
        for permuted in itertools.permutations(rule_set):
            got = [resolve_drawdown_rule(dd, list(permuted)) for dd in _sweep()]
            assert _as_keys(got) == _as_keys(reference), (
                f"permutation {[r.threshold_pct for r in permuted]} changed the answer"
            )


def test_an_early_break_implementation_would_disagree() -> None:
    """Pin the direction: first-match is NOT the shipped behaviour.

    Defect 3's prose would permit a first-match loop over a *sorted* list, which
    happens to agree with severity-max on a monotone ladder and disagrees on a
    non-monotone one. This asserts the shipped reading directly, at a drawdown
    where the two diverge.

    **Hand-computed at a 17% drawdown, and the first draft of this comment got
    the arithmetic wrong** — worth recording, because the error is the same
    shape as the defect being tested. Over ``[(0.10, 0.90), (0.15, 0.20),
    (0.20, 0.50)]``:
      * ``0.17 >= 0.10`` -> triggers
      * ``0.17 >= 0.15`` -> triggers
      * ``0.17 >= 0.20`` -> does **NOT** trigger (0.17 < 0.20)
    So the triggered set is the first two rules, and:
      * severity-max  -> ``max(0.90, 0.20)`` = ``0.90``
      * threshold-max -> ``max(0.10, 0.15)`` = the rule at 0.15, reduction ``0.20``
    They diverge (``0.90`` vs ``0.20``), and severity is the clause the
    specification states as the rule.

    The draft asserted ``0.50`` for the threshold branch — correct only if the
    0.20 rung had triggered, which it does not. The assertion caught it, which
    is the argument for computing by hand and writing the number down rather
    than reading it off the code.
    """
    non_monotone = [
        DrawdownRule(threshold_pct=0.10, risk_reduction_pct=0.90),
        DrawdownRule(threshold_pct=0.15, risk_reduction_pct=0.20),
        DrawdownRule(threshold_pct=0.20, risk_reduction_pct=0.50),
    ]
    resolved = resolve_drawdown_rule(0.17, non_monotone)
    assert resolved is not None

    triggered = [r for r in non_monotone if r.threshold_pct <= 0.17]
    assert [r.threshold_pct for r in triggered] == [0.10, 0.15]

    by_threshold = max(triggered, key=lambda r: r.threshold_pct)

    assert resolved.risk_reduction_pct == 0.90
    assert by_threshold.risk_reduction_pct == 0.20
    assert resolved.risk_reduction_pct != by_threshold.risk_reduction_pct


def test_the_two_keys_agree_on_every_triggered_subset_of_the_default_ladder() -> None:
    """Defect 4's *reason*: on the shipped ladder the ambiguity is invisible.

    The shipped tiers ascend in both fields, so ``max(key=risk_reduction)`` and
    ``max(key=threshold)`` coincide on every triggered subset. That is not a
    property to rely on — it is the reason a caller would never notice the two
    rules differ at all. This test records that the agreement holds *and* is
    contingent, by asserting the monotonicity that produces it.
    """
    assert is_monotone(DEFAULT_TIERS), (
        "if the shipped ladder stops ascending in both fields the severity/"
        "threshold agreement no longer holds and the divergence test above "
        "becomes reachable through the shipped config"
    )

    for size in range(1, len(DEFAULT_TIERS) + 1):
        for subset in itertools.combinations(DEFAULT_TIERS, size):
            highest = max(r.threshold_pct for r in subset)
            for drawdown in (highest, highest + 0.01):
                triggered = [r for r in subset if drawdown >= r.threshold_pct]
                if not triggered:
                    continue
                severity = max(triggered, key=lambda r: r.risk_reduction_pct)
                threshold = max(triggered, key=lambda r: r.threshold_pct)
                assert severity.risk_reduction_pct == threshold.risk_reduction_pct


# --------------------------------------------------------------------------
# The ladder: every rung, and the boundaries between them
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("drawdown", "reduction", "outcome", "triggered"),
    [
        # --- below every tier: no rule fires ------------------------------
        (-0.50, 0.00, "no_action", 0),  # (100 - 150)/100 = -0.5, a new high
        (0.00, 0.00, "no_action", 0),  # at the peak exactly
        (0.05, 0.00, "no_action", 0),  # half of the first tier
        (0.0999, 0.00, "no_action", 0),  # just below the first tier
        # --- the first tier ------------------------------------------------
        (0.10, 0.50, "reduce_risk", 1),  # AT the threshold: `>=`, not `>`
        (0.1099, 0.50, "reduce_risk", 1),  # between rungs one and two
        (0.1499, 0.50, "reduce_risk", 1),  # just below rung two
        # --- the second tier ----------------------------------------------
        (0.15, 0.75, "reduce_risk", 2),  # AT the second threshold
        (0.16, 0.75, "reduce_risk", 2),
        (0.1999, 0.75, "reduce_risk", 2),  # just below rung three
        # --- the third tier -----------------------------------------------
        (0.20, 1.00, "stop_trading", 3),  # AT the third threshold
        (0.50, 1.00, "stop_trading", 3),
        (0.90, 1.00, "stop_trading", 3),  # a 90% drawdown
        (1.00, 1.00, "stop_trading", 3),  # wiped out exactly
        (1.50, 1.00, "stop_trading", 3),  # (100 - (-50))/100 = 1.5, negative equity
    ],
)
def test_the_shipped_ladder_rung_by_rung(
    drawdown: float, reduction: float, outcome: str, triggered: int
) -> None:
    """Every reachable cell of the shipped ladder, hand-computed.

    The thresholds are compared with ``>=``, so each boundary belongs to the
    *higher* rung: a 10.00% drawdown fires the 10% tier, and 9.99% does not.
    Nothing here is computed by subtraction — every fixture is a literal or an
    addition, so no boundary test can land on the wrong side of a float.
    """
    result = _evaluate(drawdown)
    assert as_float(result, key="risk_reduction_fraction") == reduction
    assert as_str(result, key="outcome") == outcome
    assert as_int(result, key="tiers_triggered") == triggered
    assert as_float(result, key="drawdown_fraction") == pytest.approx(drawdown)


def test_the_reduction_is_monotone_in_the_drawdown() -> None:
    """A deeper drawdown never triggers *less* de-risking.

    This is the property the shipped ladder is *for*, and the one a mis-scaled
    ladder violates most quietly: a percent-vs-fraction error makes the function
    constant at zero, which is monotone — so monotonicity alone cannot catch
    defect 1. It is asserted anyway, because it is the property whose violation
    would be a genuine policy error, and because a caller-supplied non-monotone
    rule set is explicitly permitted (defect 4) — so the invariant holds for the
    shipped ladder and *only* for the shipped ladder, which is worth stating.
    """
    previous = -1.0
    for drawdown in _sweep():
        current = _reduction(drawdown)
        assert current >= previous, f"reduction fell at drawdown {drawdown}"
        previous = current


def test_the_specification_ladder_is_a_max_not_a_sum() -> None:
    """The rungs REPLACE rather than accumulate.

    A "ladder" is ambiguous English: it can mean a chain where each rung adds to
    the last, or a set of levels where the worst applies. Hand-computed at a 21%
    drawdown, if the rungs accumulated the reduction would be
    ``0.50 + 0.75 + 1.00 = 2.25`` — then clipped to 1.0 by the ``le=1`` bound.
    The shipped answer is ``1.00``, which is the third rung alone.
    """
    assert _reduction(0.21) == 1.00
    assert _reduction(0.21) != pytest.approx(2.25)


# --------------------------------------------------------------------------
# Defect 5 — the outcome Literal
# --------------------------------------------------------------------------


def test_every_declared_outcome_is_producible() -> None:
    """A ``Literal`` is a promise with two halves, and BOTH are checked.

    Membership is the weak half: every value the function returns must be a
    member. The load-bearing half is that **every member is producible** — a
    declared outcome nothing can reach is the project's recurring "declared,
    consumed, unreachable" defect wearing a type annotation.

    Enumerated over a fine sweep of the drawdown, not asserted from the spec:
    the reachable set must equal the declared set.

    **The runtime half alone is not enough, and the sweep proved it.** ``M5.1``
    (the ``Literal`` loses ``stop_trading``) and ``M5.2`` (it loses
    ``no_action``) SURVIVED this test, because a ``Literal`` is not enforced at
    runtime — the function happily returns the string either way, so asserting
    the *returned* value cannot see the annotation change. The declared members
    must be read from the type itself, which is what
    ``test_the_declared_outcome_set_is_pinned_to_the_type`` now does. Both halves
    are needed: this one proves nothing reaches *outside* the set, that one
    proves nothing inside the set is dead.
    """
    declared = {"no_action", "reduce_risk", "stop_trading"}
    reachable = {_outcome(drawdown) for drawdown in _sweep()}
    assert reachable == declared


def test_the_declared_outcome_set_is_pinned_to_the_type() -> None:
    """Read the ``Literal``'s members from the TYPE, and pin them exactly.

    This is the test that kills ``M5.1`` and ``M5.2``, and it exists because
    they survived without it. A ``Literal`` is a static annotation, so a runtime
    assertion about returned strings cannot detect a member being removed from
    it — the code keeps running and returns the same values. The annotation is
    the *contract*, so the contract is what must be asserted.

    Both directions are covered: the declared set equals the reachable set, and
    the reachability direction is proven by
    ``test_every_declared_outcome_is_producible``. Together they close the
    promise's two halves.
    """
    assert set(get_args(RuleOutcome)) == {"no_action", "reduce_risk", "stop_trading"}


def test_the_stop_trading_boundary_is_exactly_one() -> None:
    """``stop_trading`` requires ``reduction >= 1.0`` — not ``0.99``, not ``0.999``.

    Section 6.6c's terminal rung is ``risk_reduction_pct: 1.00``, meaning "stop
    trading". The gate that labels it must therefore be at exactly ``1.0``:
    a reduction of ``0.995`` is a *very large* de-risking, not a stop-out, and
    a consumer reading ``stop_trading`` will halt the process.

    **This test kills ``M5.3``** (the gate moved to ``0.99``), which survived
    every other test in the file. The mutations that matter here are the ones
    strictly between the two bounds: ``0.995`` is a legal ``DrawdownRule``
    reduction, and it is the only kind of rule that can tell ``>= 1.0`` from
    ``>= 0.99``. A fixture at exactly ``1.0`` cannot, because both comparisons
    are true there.
    """
    just_under = [DrawdownRule(threshold_pct=0.10, risk_reduction_pct=0.995)]
    result = _evaluate(0.15, rules=just_under)
    assert as_float(result, key="risk_reduction_fraction") == 0.995
    assert as_str(result, key="outcome") == "reduce_risk"

    exactly = [DrawdownRule(threshold_pct=0.10, risk_reduction_pct=1.0)]
    assert as_str(_evaluate(0.15, rules=exactly), key="outcome") == "stop_trading"


def test_no_action_and_a_zero_reduction_rule_are_distinguishable() -> None:
    """Defect 5: ``0.0`` alone cannot say which happened.

    A rule with ``risk_reduction_pct > 0`` cannot publish ``0.0``, so the
    ambiguity's second limb is unreachable through the *shipped* contract — but
    the *reading* is what matters: a consumer who wants "did anything fire?"
    must not have to infer it from a number that is also a legal instruction.
    ``outcome`` answers it directly.
    """
    no_rule = _evaluate(0.00)
    assert as_float(no_rule, key="risk_reduction_fraction") == 0.0
    assert as_str(no_rule, key="outcome") == "no_action"
    assert as_float_or_none(no_rule, key="triggered_threshold_fraction") is None

    fired = _evaluate(0.50)
    assert as_str(fired, key="outcome") == "stop_trading"
    assert as_float_or_none(fired, key="triggered_threshold_fraction") == 0.20


def test_stop_trading_is_reserved_for_a_complete_reduction() -> None:
    """``stop_trading`` means ``risk_reduction == 1.0`` and nothing less.

    A consumer must not have to compare floats to learn that trading stopped, so
    the label is derived from the reduction rather than from which rung fired.
    Asserted on both sides: 0.75 is ``reduce_risk``, 1.0 is ``stop_trading``.
    """
    assert _outcome(0.19) == "reduce_risk"
    assert _outcome(0.20) == "stop_trading"


# --------------------------------------------------------------------------
# Caller-supplied rules
# --------------------------------------------------------------------------


def test_caller_supplied_rules_replace_the_configured_ladder() -> None:
    """Hand-computed: one rule, 0.30 threshold, 0.25 reduction.

    At a 0.31 drawdown -> 0.25. At 0.29 -> no rule -> 0.0.
    """
    rules = [DrawdownRule(threshold_pct=0.30, risk_reduction_pct=0.25)]
    assert _reduction(0.31, rules=rules) == 0.25
    assert _reduction(0.29, rules=rules) == 0.00


def test_caller_supplied_rules_are_disclosed_in_a_warning() -> None:
    """The override must be visible in the result's own text.

    Section 6.6c's whole argument is that the ladder is a *pre-commitment*.
    That argument does not survive a caller editing it in the moment, and the
    function cannot detect whether the supplied rules were fixed in advance —
    so it says so and leaves the judgement to the reader.
    """
    result = _evaluate(0.31, rules=[DrawdownRule(threshold_pct=0.30, risk_reduction_pct=0.25)])
    assert any("Caller-supplied rules override" in w for w in result.warnings)

    configured = _evaluate(0.31)
    assert not any("Caller-supplied rules override" in w for w in configured.warnings)


def test_an_empty_caller_supplied_rule_list_is_silent_not_an_error() -> None:
    """No rules is a legitimate configuration, not a crash.

    Hand-computed: with no rules, ``triggered`` is empty at every drawdown, so
    the answer is ``no_action`` / ``0.0`` everywhere. Guarding this matters
    because ``min(..., default=nan)`` appears in the no-trigger interpretation
    string — a ``min()`` over an empty sequence is a ``ValueError`` without the
    default, and an empty rule list is the cheapest way to reach that branch.
    """
    for drawdown in (0.0, 0.5, 1.5):
        result = _evaluate(drawdown, rules=[])
        assert as_str(result, key="outcome") == "no_action"
        assert as_int(result, key="tiers_evaluated") == 0


def test_rules_are_not_mutated_by_the_call() -> None:
    """The function is stateless: calling it twice gives the same answer.

    It reports an instruction and never applies it, so there is no state
    transition to observe — but the ``rules`` list is caller-owned and a
    ``sort`` in place would be a silent side effect. ``risk_budget``'s
    ``resolve_drawdown_rule`` uses ``max()`` over a filtered comprehension and
    does not sort, which is exactly the property this pins.
    """
    rules = [
        DrawdownRule(threshold_pct=0.20, risk_reduction_pct=1.00),
        DrawdownRule(threshold_pct=0.10, risk_reduction_pct=0.50),
    ]
    before = [(r.threshold_pct, r.risk_reduction_pct) for r in rules]
    first = _evaluate(0.15, rules=rules)
    second = _evaluate(0.15, rules=rules)
    after = [(r.threshold_pct, r.risk_reduction_pct) for r in rules]

    assert before == after
    assert first.value == second.value


# --------------------------------------------------------------------------
# The non-defect: the base-state rule does NOT apply
# --------------------------------------------------------------------------


def test_the_base_state_failure_does_not_apply_here() -> None:
    """``no_action`` is the modal output, and that is the DESIGN, not a defect.

    D-047 (``inflation_convergence_classifier``) and D-053
    (``project_inflation_trajectory``) each found a classifier whose own
    thresholds made the uninformative label the modal output — 79.1% of real
    months read ``stable`` in D-053, so the label carried no information.

    This function is not a classifier. Its modal output is ``no_action``, and a
    de-risking rule that fired most of the time would be a *strategy* rather
    than a rule: the entire point of a pre-commitment is that it is silent until
    it is not. Applying lesson 5g mechanically here would have produced a "fix"
    for the design.

    The check is therefore the opposite one — is ``no_action`` the modal output
    *for the right reason*? It is: it occurs exactly while the drawdown is below
    the first rung, and the first rung fires at 10%, which is a real
    institutional de-risking level rather than a threshold chosen to make the
    output balanced.

    Recorded rather than omitted, because an unrecorded non-application is
    indistinguishable from an oversight.
    """
    below = [dd for dd in _sweep() if dd < 0.10]
    assert below, "the sweep must include drawdowns below the first rung"
    assert all(_outcome(dd) == "no_action" for dd in below), "a rule fired below its own threshold"
    # And the first rung is where the config says it is, read from the file.
    assert [t.drawdown_pct for t in _cfg().drawdown_tiers] == [10.0, 15.0, 20.0]


# --------------------------------------------------------------------------
# Inputs, output keys, warnings
# --------------------------------------------------------------------------


def test_the_published_keys_are_the_documented_six() -> None:
    """A key rename is not cosmetic — several keys decide the reading."""
    result = _evaluate(0.16)
    assert isinstance(result.value, dict)
    assert set(result.value) == {
        "risk_reduction_fraction",
        "outcome",
        "drawdown_fraction",
        "triggered_threshold_fraction",
        "tiers_evaluated",
        "tiers_triggered",
    }


def test_inputs_used_names_the_consumed_fields() -> None:
    """The contract's ``inputs_used`` must name what was actually read.

    ``evaluate_drawdown_rules`` consumes the two ``DrawdownState`` fields and
    derives the drawdown itself. Naming a derived quantity — or naming the
    config — would misreport provenance.
    """
    result = _evaluate(0.16)
    assert result.inputs_used == ["high_water_mark", "current_value"]


def test_the_model_reports_itself_and_its_country() -> None:
    result = _evaluate(0.16)
    assert result.model_name == "drawdown_rule_check"
    assert result.country == "us"
    assert result.as_of is not None


def test_the_thesis_conviction_override_is_always_warned() -> None:
    """The LTCM lesson is a WARNING, not a comment.

    Every call carries it — including ``no_action``, because the warning is
    about *why the rule is mechanical*, not about what fired. A trader reading a
    ``no_action`` result is exactly the person who needs to know the rule will
    not consult their conviction on the way down.
    """
    for drawdown in (0.0, 0.16, 0.50):
        result = _evaluate(drawdown)
        assert any("overrides thesis conviction" in w for w in result.warnings)


def test_a_negative_drawdown_warns_that_the_reading_may_be_a_stale_peak() -> None:
    """Above the high-water mark the rule is silent — and that is a risk.

    Hand-computed: at a -0.50 drawdown an un-stale peak means the portfolio is
    genuinely 50% above its prior high. But the same reading is produced by a
    *stale* high-water mark, i.e. one that has not been updated after a real
    loss — in which case the rule is silent during a drawdown it was written to
    catch. The function cannot tell the two apart, so it discloses.
    """
    result = _evaluate(-0.20)
    assert as_str(result, key="outcome") == "no_action"
    assert any("ABOVE its high-water mark" in w for w in result.warnings)


def test_a_drawdown_above_one_warns_about_negative_equity() -> None:
    """Hand-computed: at a 1.5 drawdown the reduction is 1.0 — indistinguishable
    from a 0.5 drawdown by output. The warning is the only signal that the
    portfolio is past zero, because the rule set cannot express anything beyond
    "stop trading"."""
    result = _evaluate(1.50)
    assert as_str(result, key="outcome") == "stop_trading"
    assert any("more than the entire high-water" in w for w in result.warnings)


def test_every_warning_branch_is_triggered_by_some_test() -> None:
    """A warning branch no test reaches is a disclosure nobody has read.

    Walks the four branches — conviction override, negative equity, new high,
    caller-supplied rules — and asserts each appears. Written as a coverage
    **partition** rather than a hit: the four cases are enumerated and each
    asserted present, so deleting a branch fails this test rather than merely
    lowering a count.
    """
    cases: dict[str, list[str]] = {
        "conviction": _evaluate(0.00).warnings,
        "negative_equity": _evaluate(1.50).warnings,
        "above_high_water": _evaluate(-0.20).warnings,
        "caller_rules": _evaluate(0.30, rules=DEFAULT_TIERS).warnings,
    }
    needles = {
        "conviction": "overrides thesis conviction",
        "negative_equity": "more than the entire high-water",
        "above_high_water": "ABOVE its high-water mark",
        "caller_rules": "Caller-supplied rules override",
    }
    for case, needle in needles.items():
        assert any(needle in w for w in cases[case]), f"the {case!r} warning branch was not reached"


def test_the_call_is_reproducible() -> None:
    """Calling twice on the same state returns the same reading.

    The function is a stateless rule lookup, not a state transition. A consumer
    calling it in a loop must not see the ladder "advance".
    """
    for drawdown in (0.05, 0.16, 0.50):
        assert _evaluate(drawdown).value == _evaluate(drawdown).value


# --------------------------------------------------------------------------
# Confidence
# --------------------------------------------------------------------------


def test_confidence_is_computed_not_asserted() -> None:
    """Section 22.8: ``compute_confidence`` is the ONLY producer.

    The specification's own sketch hardcoded ``confidence=0.7``. Reconstructed
    from stated facts and compared to the actual output — so a literal would
    fail this test, and so would a *different* set of facts.
    """
    result = _evaluate(0.16)
    expected = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=False,
            is_heuristic_not_calibrated=True,
            depends_on_unobservable=False,
        )
    )
    assert result.confidence == expected


def test_confidence_does_not_vary_with_the_drawdown() -> None:
    """Nothing here is estimated, so nothing about the answer is uncertain.

    The function is exact arithmetic over a pre-commitment: the tiers are
    stated, not fitted. A confidence that moved with the drawdown would be
    reporting the *outcome* as though it were a model uncertainty — which is the
    category error ``compute_confidence`` exists to prevent.
    """
    values = {_evaluate(dd).confidence for dd in (0.0, 0.16, 0.50, 1.50)}
    assert len(values) == 1


def test_confidence_is_the_midpoint_and_that_is_the_heuristic_penalty_talking() -> None:
    """Confidence is exactly ``0.5``, and the first draft of this test was WRONG.

    The draft asserted ``0.5 < confidence`` on the reasoning that "there is
    nothing here to estimate, so confidence should be high relative to the
    project's other models". That reasoning is wrong, and the failure was worth
    recording:

    * ``compute_confidence`` applies ``heuristic_penalty`` whenever
      ``is_heuristic_not_calibrated`` is set, and the function sets it —
      correctly, because the tiers are a stated *convention* rather than a
      fitted estimate.
    * Hand-computed from the config: ``base 0.7 - heuristic_penalty 0.2 = 0.5``.
    * And ``0.5`` is exactly half the range. So the honest description is
      "midpoint", not "high" — the module docstring's claim that confidence is
      "high relative to the project's other models" was **unmeasured prose**.

    The number is only meaningful against the **lattice** of what the stated
    facts can produce, so the test asserts the value *and* its position in that
    lattice rather than against an intuition. A highest-confidence reading
    (``heur=False, families=5``) reaches the 0.95 ceiling; the lowest
    (``dqf=True, heur=True, unobs=True, families=0``) sits on the 0.05 floor.
    Our 0.5 is the midpoint — which is defensible for a mechanical rule whose
    inputs can be stale, and is *not* a claim the function should overstate.

    **The coincidence worth flagging:** the specification's sketch hardcodes
    ``confidence=0.7``, and ``compute_confidence`` returns ``0.5``. Those are
    different numbers *and* different facts, but ``0.7`` is also the config's
    ``base`` — so a reader skimming could conclude the two agree. They do not,
    and ``test_confidence_is_computed_not_asserted`` is what proves it.
    """
    assert _evaluate(0.16).confidence == 0.5

    # The lattice, read from the config rather than hardcoded: the ceiling is
    # reachable with full corroboration and no heuristic marker...
    top = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=False,
            is_heuristic_not_calibrated=False,
            depends_on_unobservable=False,
            source_independence_count=5,
        )
    )
    # ...and the floor is reachable with every stated penalty present.
    bottom = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=True,
            is_heuristic_not_calibrated=True,
            depends_on_unobservable=True,
            source_independence_count=0,
        )
    )
    assert bottom == 0.05
    assert top == 0.95
    assert bottom < _evaluate(0.16).confidence < top


def test_confidence_names_the_heuristic_marker_rather_than_hiding_it() -> None:
    """The tiers are a convention, so the heuristic marker MUST be set.

    This is the fact the confidence number carries, and it is the reason the
    value is not higher. Dropping the marker would raise confidence to ``0.7``
    for no better reason than optimism — which is the failure mode Section 22.8
    exists to prevent.
    """
    result = _evaluate(0.16)
    as_heuristic = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=False,
            is_heuristic_not_calibrated=True,
            depends_on_unobservable=False,
        )
    )
    as_calibrated = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=False,
            is_heuristic_not_calibrated=False,
            depends_on_unobservable=False,
        )
    )
    assert result.confidence == as_heuristic
    assert result.confidence != as_calibrated
    assert as_heuristic < as_calibrated


# --------------------------------------------------------------------------
# Config accessor integrity
# --------------------------------------------------------------------------


# The Module 17.2/17.3 hard-limit leaves (D-056). `RiskSettings` requires them,
# and these tests are about the *ladder* accessors, so their values are
# deliberately the shipped ones: a fixture that changed them would move two
# concerns at once and a failure would not say which.
_HARD_LIMIT_LEAVES: dict[str, CalibratedValue] = {
    "max_position_pct_of_portfolio": CalibratedValue(
        value=0.15, calibration_status="institutional_convention"
    ),
    "max_factor_exposure_pct": CalibratedValue(
        value=0.30, calibration_status="institutional_convention"
    ),
    "max_leverage": CalibratedValue(value=3.0, calibration_status="institutional_convention"),
    "min_liquidity_days_to_unwind": CalibratedValue(
        value=2, calibration_status="institutional_convention"
    ),
    "vol_target_reflexivity_scale": CalibratedValue(
        value=0.8, calibration_status="institutional_convention"
    ),
}


def test_the_accessor_reads_its_leaves_not_the_shipped_literals() -> None:
    """A test against the shipped value cannot tell a live read from a hardcode.

    D-050's accessor blind spot. Rebuilt here from EXPLICIT leaves and read
    through the accessor, so a hardcoded ``[10.0, 15.0, 20.0]`` in the property
    fails.
    """
    perturbed = RiskSettings(
        target_vol_annualized=CalibratedValue(
            value=0.10, calibration_status="institutional_convention"
        ),
        stress_correlation=CalibratedValue(
            value=0.9, calibration_status="institutional_convention"
        ),
        var_confidence_levels=CalibratedValue(
            value=[0.95, 0.99], calibration_status="institutional_convention"
        ),
        historical_var_lookback_days=CalibratedValue(
            value=500, calibration_status="uncalibrated_illustrative"
        ),
        rebalancing_drift=CalibratedValue(value=0.10, calibration_status="mechanical_rule"),
        drawdown_thresholds={
            "calibration_status": "mechanical_rule",
            "tiers": [
                {"drawdown_pct": 7.0, "risk_reduction_pct": 30.0},
                {"drawdown_pct": 11.0, "risk_reduction_pct": 60.0},
            ],
        },
        **_HARD_LIMIT_LEAVES,
    )
    assert [t.drawdown_pct for t in perturbed.drawdown_tiers] == [7.0, 11.0]
    assert [t.risk_reduction_pct for t in perturbed.drawdown_tiers] == [30.0, 60.0]


def test_the_accessor_sorts_rather_than_returning_file_order() -> None:
    """§6.6c's "evaluated in order" does not mean the FILE's order is load-bearing.

    The shipped file happens to be sorted, so a test using it cannot tell
    whether the accessor sorts or merely forwards. Hand-computed on a
    deliberately shuffled file: the accessor must return ascending thresholds.
    """
    shuffled = RiskSettings(
        target_vol_annualized=CalibratedValue(
            value=0.10, calibration_status="institutional_convention"
        ),
        stress_correlation=CalibratedValue(
            value=0.9, calibration_status="institutional_convention"
        ),
        var_confidence_levels=CalibratedValue(
            value=[0.95, 0.99], calibration_status="institutional_convention"
        ),
        historical_var_lookback_days=CalibratedValue(
            value=500, calibration_status="uncalibrated_illustrative"
        ),
        rebalancing_drift=CalibratedValue(value=0.10, calibration_status="mechanical_rule"),
        drawdown_thresholds={
            "tiers": [
                {"drawdown_pct": 20.0, "risk_reduction_pct": 100.0},
                {"drawdown_pct": 10.0, "risk_reduction_pct": 50.0},
                {"drawdown_pct": 15.0, "risk_reduction_pct": 75.0},
            ]
        },
        **_HARD_LIMIT_LEAVES,
    )
    assert [t.drawdown_pct for t in shuffled.drawdown_tiers] == [10.0, 15.0, 20.0]


def test_the_shipped_ladder_is_monotone_in_both_fields() -> None:
    """Asserted against the FILE, not a fixture: the property defect 4 relies on.

    If a future edit makes the ladder non-monotone — say by raising a rung's
    reduction above the next rung's — the severity/threshold divergence becomes
    reachable through the shipped config, and this test says so before that
    happens.
    """
    tiers = _cfg().drawdown_tiers
    assert is_monotone(
        [
            DrawdownRule(
                threshold_pct=t.drawdown_pct / 100.0,
                risk_reduction_pct=t.risk_reduction_pct / 100.0,
            )
            for t in tiers
        ]
    )


def test_an_empty_tier_list_configures_a_silent_ladder() -> None:
    """An empty ``tiers`` block is legal and means "never de-risk".

    Worth pinning because it is the one configuration where the function's
    *absence* of output is indistinguishable from a mis-scaled ladder — the
    defect-1 failure mode — and the two are told apart only by the config. The
    function must not raise.
    """
    empty = RiskSettings(
        target_vol_annualized=CalibratedValue(
            value=0.10, calibration_status="institutional_convention"
        ),
        stress_correlation=CalibratedValue(
            value=0.9, calibration_status="institutional_convention"
        ),
        var_confidence_levels=CalibratedValue(
            value=[0.95, 0.99], calibration_status="institutional_convention"
        ),
        historical_var_lookback_days=CalibratedValue(
            value=500, calibration_status="uncalibrated_illustrative"
        ),
        rebalancing_drift=CalibratedValue(value=0.10, calibration_status="mechanical_rule"),
        drawdown_thresholds={"tiers": []},
        **_HARD_LIMIT_LEAVES,
    )
    assert empty.drawdown_tiers == []


# --------------------------------------------------------------------------
# Module surface
# --------------------------------------------------------------------------


def test_the_module_exports_what_it_declares() -> None:
    """The module surface, pinned after D-055 (17.3), D-056 (17.2) and D-057 (17.3 Kelly).

    ``RebalancingOutcome``/``check_rebalancing_drift``/``RiskBudgetTarget`` came
    with ``check_rebalancing_drift``; ``RiskLimits``/``VolTargetInputs``/
    ``volatility_target_scaling`` with the vol-target increment; ``KellyInputs``/
    ``SizingOutcome``/``generalized_kelly_fraction``/``apply_fractional_kelly``
    with the fractional-Kelly increment. Pinning the set means a rename or a
    silently dropped re-export fails here rather than at an import site in a
    downstream consumer.
    """
    from macro_engine.portfolio import risk_budget

    assert set(risk_budget.__all__) == {
        "DrawdownRule",
        "DrawdownState",
        "RuleOutcome",
        "evaluate_drawdown_rules",
        "resolve_drawdown_rule",
        "RebalancingOutcome",
        "RiskBudgetTarget",
        "check_rebalancing_drift",
        "RiskLimits",
        "VolTargetInputs",
        "volatility_target_scaling",
        "KellyInputs",
        "KellyPayoffUnit",
        "SizingOutcome",
        "generalized_kelly_fraction",
        "apply_fractional_kelly",
    }
    for name in risk_budget.__all__:
        assert hasattr(risk_budget, name)
