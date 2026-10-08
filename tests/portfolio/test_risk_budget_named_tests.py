"""``portfolio/risk_budget.py`` — the four tests the module NAMES, and one more script.

MEASURED 2026-10-06: this module cites **four test functions by name** and none of
them existed anywhere in ``tests/``:

* ``test_an_empty_tier_list_configures_a_silent_ladder`` — cited in
  ``evaluate_drawdown_rules`` as the justification for the empty-ladder branch;
* ``test_the_consumer_vocabulary_is_derived_from_the_producers`` — cited as the
  ONLY enforcement of the ``KellyPayoffUnit``/``PayoffUnit`` equality;
* ``test_the_diagonal_matches_realized_vol_simple`` — cited as the enforcement of
  the ``ddof = 1`` agreement between this module and ``models/risk.py``;
* ``test_the_ccd_step_solves_the_two_asset_oracle_exactly`` — cited as the pin on
  ``_ccd_step``'s variance-vs-volatility right-hand side.

Each is written here, at the name the module uses, so the claims become true. This
is the **eighth through eleventh** instance of the named-artifact class in the
campaign (F-SIG-003, F-INV-002, F-NT-003, F-SCN-001, F-BLD-002, F-CAT-003,
F-QRY-002) — and the first module to carry four of them at once.
"""

from __future__ import annotations

import math
from typing import get_args

import pytest

from macro_engine.models.contracts import ModelResult
from macro_engine.models.probability import PayoffUnit
from macro_engine.models.risk import RealizedVolInputs, realized_vol_simple
from macro_engine.portfolio.risk_budget import (
    DrawdownState,
    KellyInputs,
    KellyPayoffUnit,
    _ccd_step,
    evaluate_drawdown_rules,
    risk_contributions,
    sample_covariance,
)

# ---------------------------------------------------------------------------
# the named test #1 — the empty ladder
# ---------------------------------------------------------------------------


def test_an_empty_tier_list_configures_a_silent_ladder() -> None:
    """An EMPTY ladder is a legal configuration meaning "never de-risk".

    The module cites this name as the reason the no-threshold branch is
    distinguished from "below the least severe threshold": reporting the latter
    for the former would name a threshold that does not exist, and the previous
    form did exactly that (``min(..., default=nan)`` printed "the least severe
    configured threshold is nan%", D-078).
    """
    state = DrawdownState(high_water_mark=100.0, current_value=10.0)  # a 90% drawdown
    result = evaluate_drawdown_rules(state, rules=[])
    value = result.value
    assert isinstance(value, dict), "the drawdown rule publishes a dict value"

    assert value["outcome"] == "no_action"
    assert value["risk_reduction_fraction"] == 0.0
    assert value["tiers_evaluated"] == 0
    assert value["tiers_triggered"] == 0
    assert value["triggered_threshold_fraction"] is None
    # The message must NOT name a threshold that does not exist.
    assert "NO TIERS ARE CONFIGURED" in result.interpretation
    assert "nan" not in result.interpretation.lower()
    assert "least severe" not in result.interpretation


def test_a_non_empty_ladder_at_the_same_drawdown_does_fire() -> None:
    """Non-vacuity: the empty ladder is silent because it is empty, not because of the drawdown."""
    from macro_engine.portfolio.risk_budget import DrawdownRule

    state = DrawdownState(high_water_mark=100.0, current_value=10.0)
    result = evaluate_drawdown_rules(
        state, rules=[DrawdownRule(threshold_pct=0.10, risk_reduction_pct=0.5)]
    )
    value = result.value
    assert isinstance(value, dict), "the drawdown rule publishes a dict value"
    assert value["outcome"] == "reduce_risk"
    assert value["risk_reduction_fraction"] == 0.5


# ---------------------------------------------------------------------------
# the named test #2 — the vocabulary mirror
# ---------------------------------------------------------------------------


def test_the_consumer_vocabulary_is_derived_from_the_producers() -> None:
    """``KellyPayoffUnit`` is a RETYPED ``Literal``; this equality is its only enforcement.

    The module explains why it is not ``Literal[*get_args(PayoffUnit)]`` (mypy
    rejects a computed alias), and says this test is what fails loudly the day the
    producer's vocabulary moves. Until 2026-10-06 it did not exist, so the two
    literals agreed only by transcription.
    """
    assert set(get_args(KellyPayoffUnit)) == set(get_args(PayoffUnit))
    assert set(get_args(PayoffUnit)) == {"bp_pnl_proxy", "fraction_of_capital"}


# ---------------------------------------------------------------------------
# the named test #3 — the ddof agreement
# ---------------------------------------------------------------------------


def test_the_diagonal_matches_realized_vol_simple() -> None:
    """Both use ``ddof = 1``, or a book's risk budget and its vol target disagree.

    ``sample_covariance``'s diagonal is an annualised VARIANCE, so it must equal
    ``realized_vol_simple``'s annualised volatility SQUARED — on the same
    observations and the same annualisation.
    """
    returns = [
        0.01,
        -0.02,
        0.015,
        0.0,
        -0.005,
        0.02,
        -0.01,
        0.005,
        0.012,
        -0.003,
        0.008,
        -0.011,
        0.004,
        0.006,
        -0.007,
        0.009,
        -0.001,
        0.003,
        0.011,
        -0.004,
    ]
    instruments, covariance = sample_covariance({"x": returns}, annualization_periods=252)
    assert instruments == ["x"]

    vol = realized_vol_simple(RealizedVolInputs(returns=returns, window=len(returns)))
    assert isinstance(vol.value, float), "realized_vol_simple publishes a scalar"
    # `realized_vol_simple` publishes the annualised volatility in PERCENT
    # (`round(vol_annualized * 100, 4)`), while the covariance diagonal is an
    # annualised VARIANCE in fraction-squared units — so the agreement is
    # `(percent / 100) ** 2`, and the tolerance accommodates the model's 4-dp
    # rounding of the percent figure.
    assert (vol.value / 100.0) ** 2 == pytest.approx(covariance[0][0], rel=1e-4)


# ---------------------------------------------------------------------------
# the named test #4 — the two-asset oracle
# ---------------------------------------------------------------------------


def test_the_ccd_step_solves_the_two_asset_oracle_exactly() -> None:
    """The docstring's oracle: uncorrelated, vols 20% / 5%, a 50/50 budget.

    The exact risk-parity solution is ``w = [0.2, 0.8]`` with contributions
    ``[0.5, 0.5]`` — weights proportional to ``1/sigma``. ``_ccd_step``'s
    right-hand side is ``b_i * sigma_p^2`` (the VARIANCE); substituting
    ``sigma_p`` — the natural-looking slip — converges smoothly to
    ``[0.1214, 0.8786]`` instead, which is why this is an oracle and not a
    live-data check.
    """
    covariance = [[0.04, 0.0], [0.0, 0.0025]]
    targets = [0.5, 0.5]
    solution = [0.2, 0.8]

    # (a) The solution is a FIXED POINT of the step, exactly.
    assert risk_contributions(solution, covariance) == pytest.approx([0.5, 0.5], abs=1e-15)
    assert _ccd_step(solution, covariance, targets, 0) == pytest.approx(0.2, abs=1e-15)
    assert _ccd_step(solution, covariance, targets, 1) == pytest.approx(0.8, abs=1e-15)

    # (b) Iterating from equal weights converges to it.
    current = [0.5, 0.5]
    for _ in range(200):
        updated = list(current)
        for index in range(2):
            updated[index] = _ccd_step(current, covariance, targets, index)
        total = sum(updated)
        current = [value / total for value in updated]
    assert current == pytest.approx(solution, abs=1e-9)
    assert risk_contributions(current, covariance) == pytest.approx([0.5, 0.5], abs=1e-9)

    # (c) ...and the wrong (volatility) variant is NOT the fixed point, which is
    #     the property that makes the oracle discriminating rather than decorative.
    sigma_p = math.sqrt(
        sum(solution[i] * sum(covariance[i][j] * solution[j] for j in range(2)) for i in range(2))
    )
    wrong = (-0.0 + math.sqrt(0.0 + 4.0 * covariance[0][0] * targets[0] * sigma_p)) / (
        2.0 * covariance[0][0]
    )
    assert wrong != pytest.approx(0.2, abs=1e-6)


# ---------------------------------------------------------------------------
# (F-RB-003) the module's two bare asserts
# ---------------------------------------------------------------------------


def test_no_bare_assert_remains_in_the_module() -> None:
    """(F-RB-003) Two bare ``assert``s stood among this module's typed raises.

    ``_ccd_step``, ``risk_contributions``, ``sample_covariance``,
    ``_solve_risk_parity`` and ``_as_translation_outcome`` all raise a typed error
    with a message; the two shape guards on the Kelly values did not. An ``assert``
    is stripped under ``python -O``, so the guard would vanish and the next line
    would report an unhelpful TypeError instead of naming the shape change.
    """
    import inspect
    from pathlib import Path

    import macro_engine.portfolio.risk_budget as rb

    source = Path(inspect.getfile(rb)).read_text(encoding="utf-8")
    offenders = [line.strip() for line in source.splitlines() if line.strip().startswith("assert ")]
    assert offenders == [], f"bare assert(s) found: {offenders}"


def test_a_non_dict_kelly_value_raises_a_typed_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(F-RB-003) The guard is a TypeError naming the shape, not an assert."""
    import macro_engine.portfolio.risk_budget as rb

    monkeypatch.setattr(rb, "generalized_kelly_fraction", lambda scenarios: _fake("not a dict"))
    with pytest.raises(TypeError, match="returned a str for value"):
        rb.apply_fractional_kelly(_kelly_inputs())


def _fake(value: str) -> ModelResult:
    from macro_engine.models.contracts import utc_now

    return ModelResult(
        model_name="fake",
        country="us",
        as_of=utc_now(),
        value=value,
        confidence=0.5,
        interpretation="i",
        context="c",
        inputs_used=["x"],
    )


def _kelly_inputs() -> KellyInputs:
    from macro_engine.models.probability import ScenarioOutcome
    from macro_engine.portfolio.risk_budget import RiskLimits

    return KellyInputs(
        scenarios=[
            ScenarioOutcome(
                name="base", probability=0.6, payoff_estimate=0.02, unit="fraction_of_capital"
            ),
            ScenarioOutcome(
                name="tail", probability=0.4, payoff_estimate=-0.01, unit="fraction_of_capital"
            ),
        ],
        payoff_unit="fraction_of_capital",
        limits=RiskLimits.from_settings(),
    )


# ---------------------------------------------------------------------------
# (F-RB-004) the tolerance mirror
# ---------------------------------------------------------------------------


def test_the_tolerance_mirror_matches_the_leaf() -> None:
    """(F-RB-004) The constant is a MIRROR of ``risk.risk_parity_tolerance``.

    Its note said it was kept "because other modules and tests import it by
    name" — MEASURED, nothing imports it (only its own definition, its ``__all__``
    entry, and a comment). The note also required that "the constant and the YAML
    must move together", which nothing enforced. This test is what makes the
    mirror safe to keep rather than a second copy of one number.
    """
    from macro_engine.config import get_settings
    from macro_engine.portfolio.risk_budget import DEFAULT_RISK_PARITY_TOLERANCE

    assert get_settings().risk.risk_parity_tolerance == DEFAULT_RISK_PARITY_TOLERANCE


def test_the_stress_note_does_not_claim_a_condition_number() -> None:
    """(F-RB-005) The note said the condition number "is reported"; nothing reports it.

    MEASURED 2026-10-06: the word "condition" appeared in the module ONLY inside
    that sentence, and ``compute_risk_parity_weights``' value dict carries no such
    key — so a reader was told a diagnostic existed that does not.
    """
    import inspect
    from pathlib import Path

    import macro_engine.portfolio.risk_budget as rb

    source = Path(inspect.getfile(rb)).read_text(encoding="utf-8")
    assert "The condition number is\n    reported" not in source
    assert "number is computed anywhere in this module" in source


# ---------------------------------------------------------------------------
# (F-RB-002) declared-vs-PRODUCED, the enforcement the docstring names
# ---------------------------------------------------------------------------


def test_every_declared_translation_outcome_is_actually_produced() -> None:
    """(F-RB-002) DECLARED vs PRODUCED — not declared vs a hardcoded set.

    ``ProposedPosition``'s class docstring states that the six members are
    "exhaustive over the refusal and sizing paths", that "'Exhaustive' is a claim
    this file has now had to repair twice", and that the check that catches a
    member the code never emits is "the shipped live check" recounting "the
    members against the outcomes the code actually produces" in
    ``scripts/live_thesis_position_check.py`` section 5.

    MEASURED 2026-10-06: that script does not exist anywhere in the tree, and the
    only enforcement that did exist — ``test_every_literal_member_is_accepted`` —
    compares the declared set against a *hardcoded* expected set: declared vs
    declared. So the one check that would catch a declared-but-never-produced
    member (the project's most-found defect class, D-045/D-046/D-048/O-53) was
    the missing script.

    This test does the comparison the docstring promises, from the AST of
    ``translate_thesis_to_position`` — the module under review — rather than from
    a second hand-written set:

    * every ``_refuse(..., outcome="...")`` literal in the function body;
    * the Kelly outcomes the function propagates through ``_as_translation_outcome``
      (the two ``SizingOutcome`` members ``apply_fractional_kelly`` can return
      once ``no_edge`` is handled by its own early refusal).

    Set equality in BOTH directions is the claim: a declared member the body
    never emits would show up as ``declared - produced`` and must not exist, and a
    produced literal absent from the ``Literal`` would be a Type error at the
    narrowing call. The union is asserted equal to the declared members, so this
    fails on drift in either direction.
    """
    import ast
    import inspect
    from pathlib import Path

    import macro_engine.portfolio.risk_budget as rb
    from macro_engine.portfolio.risk_budget import (
        _TRANSLATION_OUTCOMES,
        PositionTranslationOutcome,
        SizingOutcome,
    )

    declared = set(get_args(PositionTranslationOutcome))
    assert declared == set(_TRANSLATION_OUTCOMES), (
        "the runtime mirror and the Literal must agree (D-045a)"
    )

    tree = ast.parse(Path(inspect.getfile(rb)).read_text(encoding="utf-8"))
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "translate_thesis_to_position"
    )

    produced: set[str] = set()
    for node in ast.walk(function):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id == "_refuse":
            for keyword in node.keywords:
                if keyword.arg == "outcome" and isinstance(keyword.value, ast.Constant):
                    produced.add(str(keyword.value.value))

    # The two Kelly verdicts actually propagated. ``no_edge`` returns early
    # (its own ``_refuse`` above), so the call site can only see these two, and
    # each is one of the two non-refusal members of the declared set. The set is
    # read from ``SizingOutcome``'s own annotation so it cannot drift from the
    # producer.
    kelly_outcomes = set(get_args(SizingOutcome.model_fields["outcome"].annotation)) - {"no_edge"}
    produced |= kelly_outcomes

    assert produced <= declared, (
        f"the code produces outcome(s) not declared in the Literal: {sorted(produced - declared)}"
    )
    assert declared - produced == set(), (
        "declared but never produced by `translate_thesis_to_position`: "
        f"{sorted(declared - produced)} — a member for a path that cannot run is the "
        "declared-consumed-unreachable class (D-045/D-046/D-048, O-53)"
    )
    assert produced == declared
