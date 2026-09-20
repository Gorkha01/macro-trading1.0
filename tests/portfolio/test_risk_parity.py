"""Tests for Module 17.1 — risk-budgeted weight construction (Section 9.2).

``compute_risk_parity_weights`` chooses **capital** weights so that every
instrument CONTRIBUTES its target share of total portfolio risk. The weights and
the budget are therefore different objects, and the gap between them is the
function's whole economic content: a high-volatility leg takes a *smaller*
notional position for the same risk contribution.

**The defect this file exists to pin is an arithmetic one, and it is silent.**

The CCD update solves ``Sigma_ii w_i^2 + a_i w_i - b_i sigma_p^2 = 0``. The
right-hand side is the portfolio **variance**, because the unnormalised Euler
contributions sum to the variance and not to the volatility. Substituting
``sigma_p`` for ``sigma_p^2`` — an easy slip, since the same derivation is
phrased in terms of volatilities throughout — yields a step that is stable,
monotone, and deterministic, and that converges to the **wrong book**. Nothing
about the live output looks wrong: the weights sum to 1, the solver "runs", and
the risk contributions are ordered sanely.

``test_the_ccd_step_solves_the_two_asset_oracle_exactly`` is the test that
catches it. On two uncorrelated assets with vols 20% and 5% and a 50/50 budget,
the exact risk-parity weights are ``[0.2, 0.8]`` (``w_i`` proportional to
``1/sigma_i``), which is a fact about the *problem* rather than about this
implementation. The buggy form converges (slowly, and never to the tolerance) at
``[0.1214, 0.8786]`` with contributions ``[0.2339, 0.7661]`` — so the oracle is
the only assertion in the file that would have failed. Every other test here
passes under both forms.

**The second thing pinned here is that the optimiser is not the answer.** A
risk budget is an estimate of a covariance dressed as weights: the estimator is
the plain unshrunk sample covariance, the window is the caller's, and the
budget only holds at the correlations it was built from. Module 17.1's LTCM
lesson is that correlations rise toward 1 in a crisis — the diversification is
largest exactly when it is least available — so the **stressed re-solve** is
part of the result and its `max_weight_shift_under_stress` is the number a desk
should size against.

Every expected value below is computed **by hand** in a comment before the
assertion, per Section 21.2 Step 4.
"""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from macro_engine.config import CalibratedValue, RiskSettings, get_settings
from macro_engine.models.contracts import ModelResult
from macro_engine.models.risk import RealizedVolInputs, _quadratic_form, realized_vol_simple
from macro_engine.portfolio.risk_budget import (
    RiskBudgetInputs,
    _ccd_step,
    _solve_risk_parity,
    compute_risk_parity_weights,
    risk_contributions,
    sample_covariance,
    stress_correlations,
)
from tests.helpers import as_bool, as_dict, as_float, as_int

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def _constant_vol_panel(
    n_assets: int, n_observations: int, *, volatility: float, seed: int
) -> dict[str, list[float]]:
    """A panel of deterministic pseudo-returns with a known volatilities.

    Not a random draw: the returns are a fixed sine/cosine lattice so the panel
    is byte-identical across runs and machines. A Monte Carlo fixture would make
    the *tolerance* comparisons flaky in a way that has nothing to do with the
    solver, which is the thing under test.

    The construction is a two-frequency signal per asset so the covariance is
    genuinely non-diagonal — a diagonal fixture would let a wrong CCD step pass.
    """
    names = [f"asset_{i:02d}" for i in range(n_assets)]
    panel: dict[str, list[float]] = {}
    for i, name in enumerate(names):
        series: list[float] = []
        for t in range(n_observations):
            angle = 2.0 * math.pi * (t / 17.0 + i / max(n_assets, 2))
            slow = math.sin(angle) + 0.5 * math.cos(angle / 3.0 + i)
            series.append(volatility * slow)
        panel[name] = series
    return panel


def _two_asset_uncorrelated(vol_a: float, vol_b: float, n: int = 400) -> dict[str, list[float]]:
    """Two assets whose sample covariance is **exactly diagonal**.

    Asset A alternates ``+vol_a, -vol_a`` (mean zero) and asset B cycles on a
    period of four, which is orthogonal to A over the sample, so the
    cross-covariance is exactly ``0.0`` — verified, not assumed. That exactness
    is what lets the oracle below be a closed-form answer rather than an
    approximate one.

    **Note that the annualised volatilities are NOT the arguments.** The sample
    variance of an alternating ``±v`` series is ``v^2 * n / (n - 1)``, and the
    ``sqrt(252)`` scaling of a *daily* number recovers an annual figure only for
    a specific construction. The tests that need an exact volatility therefore
    build the **covariance directly** (``_oracle_covariance``) and assert against
    it, so the oracle tests the SOLVER and not the estimator. This fixture is for
    the tests that only need a well-conditioned, non-diagonal-or-not panel.
    """
    a = [vol_a if t % 2 == 0 else -vol_a for t in range(n)]
    cycle = [vol_b, 0.0, -vol_b, 0.0]
    b = [cycle[t % 4] for t in range(n)]
    return {"A": a, "B": b}


def _oracle_covariance(vol_a: float, vol_b: float, correlation: float = 0.0) -> list[list[float]]:
    """A 2x2 covariance with **exactly** the stated vols and correlation.

    Built from the definition (``Sigma_ij = rho_ij sigma_i sigma_j``) rather than
    estimated from a series, because the oracle tests are assertions about the
    *solver*: a hand-computed answer is only checkable if the inputs are the
    numbers written down. Estimating a covariance first would fold the
    estimator's finite-sample error into an exactness claim.
    """
    return [
        [vol_a * vol_a, correlation * vol_a * vol_b],
        [correlation * vol_a * vol_b, vol_b * vol_b],
    ]


# --------------------------------------------------------------------------
# 1. The oracle — the test that catches the arithmetic defect
# --------------------------------------------------------------------------


def test_the_ccd_step_solves_the_two_asset_oracle_exactly() -> None:
    """The exact 2-asset risk-parity solution, by hand, against the solver.

    **Hand calculation.** For two *uncorrelated* assets the Euler contribution
    of asset ``i`` is ``RC_i = w_i^2 sigma_i^2 / sigma_p^2``. A 50/50 risk
    budget therefore requires

        w_A^2 sigma_A^2 = w_B^2 sigma_B^2   =>   w_A sigma_A = w_B sigma_B
        =>  w_i  proportional to  1 / sigma_i.

    With ``sigma_A = 0.20`` and ``sigma_B = 0.05``:

        w_A = (1/0.20) / (1/0.20 + 1/0.05)
            = 5 / (5 + 20)
            = 5 / 25
            = 0.2
        w_B = 1 - 0.2 = 0.8

    and the contributions are 0.5 each by construction.

    The covariance is **constructed** rather than estimated (see
    ``_oracle_covariance``) so the hand-computed answer is exact: this asserts
    the SOLVER, and an estimated covariance would fold the estimator's
    finite-sample error into an exactness claim.

    This is a fact about the risk-budgeting problem, not about this module, which
    is why it is the assertion that has to exist: it is the only test in the file
    that distinguishes ``sigma_p`` from ``sigma_p^2`` on the right-hand side of
    the CCD step.
    """
    covariance = _oracle_covariance(0.20, 0.05)
    weights, converged, _ = _solve_risk_parity(covariance, [0.5, 0.5], 2, 1e-14, 10_000)
    contributions = risk_contributions(weights, covariance)

    assert weights[0] == pytest.approx(0.2, abs=1e-10)
    assert weights[1] == pytest.approx(0.8, abs=1e-10)
    assert contributions[0] == pytest.approx(0.5, abs=1e-10)
    assert contributions[1] == pytest.approx(0.5, abs=1e-10)

    # The buggy step stalls far above the tolerance and never reports convergence.
    assert converged is True, (
        "The two-asset oracle must converge. A non-converged solve here is the "
        "signature of the sigma_p-for-sigma_p^2 slip (measured: it stalls at "
        "w=[0.1214, 0.8786] with contributions [0.2339, 0.7661])."
    )


def test_the_ccd_step_reproduces_the_oracle_in_one_step_from_the_answer() -> None:
    """At the exact solution the CCD step must be a **fixed point**.

    This is the local form of the oracle and it localises a failure: if the
    integrated test above fails, this one says whether the *step* is wrong or the
    *iteration/stopping* around it is. At ``w = [0.2, 0.8]`` the step for A must
    return 0.2 exactly.

    **Hand calculation** with ``sigma_A^2 = 0.04``, ``sigma_B^2 = 0.0025`` and a
    diagonal covariance: ``a_A = Sigma_AB w_B = 0``,
    ``sigma_p^2 = 0.2^2*0.04 + 0.8^2*0.0025 = 0.0016 + 0.0016 = 0.0032``, so

        w_A = (-0 + sqrt(0 + 4 * 0.04 * 0.5 * 0.0032)) / (2 * 0.04)
            = sqrt(0.000256) / 0.08
            = 0.016 / 0.08
            = 0.2

    which is the starting value: a fixed point. Substituting ``sigma_p`` for
    ``sigma_p^2`` gives ``sqrt(2 * 0.04 * 0.5 * 0.0566)/0.08 = 0.1883``, which is
    not a fixed point — so this test also catches the slip, in isolation.
    """
    covariance = _oracle_covariance(0.20, 0.05)
    weights = [0.2, 0.8]
    targets = [0.5, 0.5]

    # The premise the hand calculation rests on, asserted rather than assumed.
    assert _quadratic_form(weights, covariance) == pytest.approx(0.0032, abs=1e-15)

    updated = _ccd_step(weights, covariance, targets, 0)
    assert updated == pytest.approx(0.2, abs=1e-12)


# --------------------------------------------------------------------------
# 2. The economics — weights are not the budget
# --------------------------------------------------------------------------


def test_a_high_volatility_leg_gets_a_smaller_notional_weight() -> None:
    """Risk parity's defining property, stated as an inequality.

    With an equal budget, the lower-volatility asset must receive the **larger**
    notional weight. If this ever reversed, the function would be maximising
    risk rather than budgeting it — and no convergence test would notice, because
    an inverted step still converges.
    """
    panel = _two_asset_uncorrelated(0.20, 0.05)
    inputs = RiskBudgetInputs(
        instrument_returns=panel,
        target_risk_contribution={"A": 0.5, "B": 0.5},
    )
    weights = as_dict(compute_risk_parity_weights(inputs), key="weights")

    # 20% vol vs 5% vol — the volatile leg must be the smaller position.
    assert weights["B"] > weights["A"]


def test_the_published_weight_and_contribution_vectors_are_different_objects() -> None:
    """The notional-vs-risk gap must be non-trivial, and consistent by identity.

    The gap is defined as ``weights[i] - risk_contributions[i]``, so the
    assertion is that **identity** on the published numbers — not a hardcoded
    value from the oracle, because this fixture's covariance is *estimated* and
    the estimated weights are not the oracle's exact 0.2/0.8. Pinning an exact
    figure here would make the test a statement about the estimator rather than
    about the function.

    What matters economically is that the gap is not identically zero: a
    function that returned the budget as the weights would produce a zero gap
    and pass a convergence test.
    """
    panel = _two_asset_uncorrelated(0.20, 0.05)
    inputs = RiskBudgetInputs(
        instrument_returns=panel,
        target_risk_contribution={"A": 0.5, "B": 0.5},
    )
    result = compute_risk_parity_weights(inputs)
    weights = as_dict(result, key="weights")
    contributions = as_dict(result, key="risk_contributions")
    gap = as_dict(result, key="notional_vs_risk_gap")

    for name in ("A", "B"):
        expected = weights[name] - contributions[name]
        assert gap[name] == pytest.approx(expected, abs=1e-9)

    # The volatile leg's notional share is materially below its risk share.
    assert gap["A"] < -0.1
    assert gap["B"] > 0.1


def test_an_unequal_budget_is_honoured() -> None:
    """A 75/25 budget with IDENTICAL assets must produce 75/25 weights.

    Two identical legs make the answer independent of the optimiser: if both
    assets have the same covariance structure, the weights must equal the
    budget exactly. This isolates the *budget plumbing* from the *solver* — a
    solver bug would show up as a deviation from 0.75/0.25 here even though both
    assets are interchangeable.
    """
    base = _constant_vol_panel(1, 200, volatility=0.10, seed=1)["asset_00"]
    panel = {"A": list(base), "B": list(base)}
    inputs = RiskBudgetInputs(
        instrument_returns=panel,
        target_risk_contribution={"A": 0.75, "B": 0.25},
    )
    weights = as_dict(compute_risk_parity_weights(inputs), key="weights")

    assert weights["A"] == pytest.approx(0.75, abs=1e-7)
    assert weights["B"] == pytest.approx(0.25, abs=1e-7)


# --------------------------------------------------------------------------
# 3. The estimate is disclosed — covariance, window, observations
# --------------------------------------------------------------------------


def test_the_diagonal_matches_realized_vol_simple_over_the_same_window() -> None:
    """The covariance's diagonal must agree with ``realized_vol_simple``.

    Two functions reading one book must not disagree about an instrument's
    volatility, or a risk budget and a vol target would be computed on two
    different clocks and the drift between them would look like signal.

    **Both the series AND the window must be matched, and that is the point of
    the test.** ``realized_vol_simple`` is a *rolling* estimator: it reports the
    vol of the trailing ``window`` observations (default 21). ``sample_covariance``
    uses the whole panel it is handed. Feeding both the same *series* and then
    comparing would compare a 21-point vol to a 300-point vol — a comparison that
    fails for a correct implementation, and that would be *made* to pass by
    loosening the tolerance, destroying the test.

    So the panel handed to ``sample_covariance`` is exactly ``window`` long, which
    makes the two estimators operate on the identical set of points. This is the
    same discipline the module's own callers must follow.

    Both use ``ddof = 1`` and the same annualisation, and
    ``realized_vol_simple`` publishes a **percent** rounded to 4 dp, so the
    comparison is against ``sqrt(variance) * 100`` with a tolerance set by that
    published rounding.
    """
    window = 21
    periods_per_year = 252
    # A panel whose length IS the window, so the two estimators see one dataset.
    panel = _constant_vol_panel(3, window, volatility=0.12, seed=7)
    names, covariance = sample_covariance(panel, annualization_periods=periods_per_year)

    for i, name in enumerate(names):
        vol_from_risk = realized_vol_simple(
            RealizedVolInputs(
                returns=panel[name],
                window=window,
                periods_per_year=periods_per_year,
            )
        ).value
        assert isinstance(vol_from_risk, float)
        assert math.sqrt(covariance[i][i]) * 100.0 == pytest.approx(vol_from_risk, abs=1e-3)


def test_the_annualization_convention_matches_the_vol_target_block() -> None:
    """The risk budget and the vol target must annualise on the SAME clock."""
    settings = get_settings()
    panel = _constant_vol_panel(2, 100, volatility=0.10, seed=3)
    _, covariance = sample_covariance(
        panel, annualization_periods=settings.risk.risk_parity_annualization_periods
    )
    result = compute_risk_parity_weights(
        RiskBudgetInputs(
            instrument_returns=panel,
            target_risk_contribution={"asset_00": 0.5, "asset_01": 0.5},
        )
    )
    assert as_int(result, key="annualization_periods") == (
        settings.risk.risk_parity_annualization_periods
    )
    # A covariance that was never annualised would give a vol ~sqrt(252) too low.
    assert math.sqrt(covariance[0][0]) > 0.01


def test_the_observation_count_is_published() -> None:
    """Returns alone do not determine a covariance; the window does."""
    panel = _constant_vol_panel(2, 137, volatility=0.10, seed=5)
    result = compute_risk_parity_weights(
        RiskBudgetInputs(
            instrument_returns=panel,
            target_risk_contribution={"asset_00": 0.5, "asset_01": 0.5},
        )
    )
    assert as_int(result, key="observations") == 137


# --------------------------------------------------------------------------
# 4. Input validation — refusals, not defaults
# --------------------------------------------------------------------------


def test_a_ragged_panel_is_refused() -> None:
    """A panel whose columns differ in length has no covariance.

    The alternative — truncating to the shortest column — is the silent series
    substitution Section 21 prohibits: it would produce a number from a panel the
    caller did not supply.
    """
    with pytest.raises(ValidationError):
        RiskBudgetInputs(
            instrument_returns={"A": [0.01, 0.02, 0.03], "B": [0.01, 0.02]},
            target_risk_contribution={"A": 0.5, "B": 0.5},
        )


def test_a_single_observation_is_refused() -> None:
    """One observation has no sample covariance (``ddof = 1`` divides by zero)."""
    with pytest.raises(ValidationError):
        RiskBudgetInputs(
            instrument_returns={"A": [0.01], "B": [0.02]},
            target_risk_contribution={"A": 0.5, "B": 0.5},
        )


def test_a_budget_that_does_not_sum_to_one_is_refused() -> None:
    """A risk budget is a **partition** of risk; it must be exhaustive.

    A budget summing to 0.9 describes a book that leaves 10% of its risk
    unaccounted for, which is not a budget — it is an incomplete statement.
    """
    with pytest.raises(ValidationError):
        RiskBudgetInputs(
            instrument_returns={"A": [0.01, 0.02], "B": [0.01, 0.02]},
            target_risk_contribution={"A": 0.5, "B": 0.4},
        )


def test_a_non_positive_budget_share_is_refused() -> None:
    """A zero or negative share is not a budget for that instrument."""
    with pytest.raises(ValidationError):
        RiskBudgetInputs(
            instrument_returns={"A": [0.01, 0.02], "B": [0.01, 0.02]},
            target_risk_contribution={"A": 1.0, "B": 0.0},
        )


def test_a_name_mismatch_is_refused_in_both_directions() -> None:
    """A budget key with no panel column (and vice versa) is a caller error.

    Both directions are checked because only one of them is caught naturally by
    a dict lookup — the other would silently drop an instrument from the budget
    and produce a book that does not match the stated one.
    """
    # A budget names an instrument the panel does not have.
    with pytest.raises(ValidationError):
        RiskBudgetInputs(
            instrument_returns={"A": [0.01, 0.02], "B": [0.01, 0.02]},
            target_risk_contribution={"A": 0.5, "C": 0.5},
        )
    # The panel has an instrument the budget does not name.
    with pytest.raises(ValidationError):
        RiskBudgetInputs(
            instrument_returns={"A": [0.01, 0.02], "B": [0.01, 0.02]},
            target_risk_contribution={"A": 1.0},
        )


def test_instruments_are_sorted_not_insertion_ordered() -> None:
    """The instrument order must be stated, not inherited from dict order.

    A caller who reads ``risk_contributions`` by position must get the same
    order a previous run produced; dict insertion order is a property of the
    caller, not of the problem.
    """
    inputs = RiskBudgetInputs(
        instrument_returns={"zeta": [0.01, 0.02], "alpha": [0.01, 0.02]},
        target_risk_contribution={"zeta": 0.5, "alpha": 0.5},
    )
    assert inputs.instruments == ["alpha", "zeta"]


# --------------------------------------------------------------------------
# 5. The correlation stress — Module 17.1's LTCM lesson
# --------------------------------------------------------------------------


def test_stress_correlations_preserves_variances() -> None:
    """Only the correlations move; the vols are untouched.

    That is what makes the stressed re-solve a *stress test* rather than a
    second estimate: the two books differ **only** because of the correlation
    assumption, so the reported shift is attributable.
    """
    covariance = [
        [0.04, 0.006, 0.0],
        [0.006, 0.01, 0.0],
        [0.0, 0.0, 0.0025],
    ]
    stressed = stress_correlations(covariance, 0.9)
    for i in range(3):
        assert stressed[i][i] == pytest.approx(covariance[i][i], rel=1e-15)


def test_stress_correlations_raises_only_correlations_below_the_stress() -> None:
    """A genuine hedge is NOT turned into a source of contagion.

    ``only_correlations_that_rise`` defaults to ``True``, and the choice is
    substantive: "correlations converge toward 1" is a claim about the upper
    tail. Forcing an already-negative correlation (long bonds against equities)
    up to +0.9 would model flight-to-quality as contagion — the opposite of what
    that asset does in the scenario being stressed.
    """
    # rho_AB = -0.5 exactly; rho_AC = +0.1.
    covariance = [
        [0.04, -0.01, 0.002],
        [-0.01, 0.01, 0.0],
        [0.002, 0.0, 0.04],
    ]
    stressed = stress_correlations(covariance, 0.9)
    # Correlations, recovered from the stressed matrix.
    sigma = [math.sqrt(stressed[i][i]) for i in range(3)]
    rho_ab = stressed[0][1] / (sigma[0] * sigma[1])
    rho_ac = stressed[0][2] / (sigma[0] * sigma[2])

    assert rho_ab == pytest.approx(-0.5, abs=1e-12), "a hedge must survive the stress"
    assert rho_ac == pytest.approx(0.9, abs=1e-12), "a low positive correlation must rise"


def test_stress_correlations_can_force_every_off_diagonal_when_asked() -> None:
    """The both-modes claim: with the flag off, even a hedge is overwritten."""
    covariance = [
        [0.04, -0.01, 0.0],
        [-0.01, 0.01, 0.0],
        [0.0, 0.0, 0.04],
    ]
    stressed = stress_correlations(covariance, 0.9, only_correlations_that_rise=False)
    sigma = [math.sqrt(stressed[i][i]) for i in range(3)]
    assert stressed[0][1] / (sigma[0] * sigma[1]) == pytest.approx(0.9, abs=1e-12)


def test_a_stressed_correlation_above_one_is_refused() -> None:
    """A correlation above 1 is not a correlation."""
    with pytest.raises(ValueError, match="stressed_correlation"):
        stress_correlations([[0.04, 0.0], [0.0, 0.01]], 1.5)


def test_the_ltcm_warning_is_always_present() -> None:
    """Module 17.1's mandated caveat is reported on EVERY run, not only on a shift.

    A warning that appears only when triggered trains a reader to treat its
    absence as reassurance. Correlation estimation risk is always present, so the
    warning is unconditional.
    """
    panel = _two_asset_uncorrelated(0.20, 0.05)
    result = compute_risk_parity_weights(
        RiskBudgetInputs(
            instrument_returns=panel,
            target_risk_contribution={"A": 0.5, "B": 0.5},
        )
    )
    text = " ".join(result.warnings)
    assert "LTCM" in text
    assert "stressed" in text.lower()


def test_identical_assets_are_unshifted_by_the_correlation_stress() -> None:
    """Perfectly redundant legs cannot be re-ordered by a correlation change.

    Two identical columns have ``rho = 1`` already, so raising correlations to
    0.9 changes nothing and the reported shift is 0. A non-zero shift here would
    mean the stressed solve is not a pure correlation change.
    """
    base = _constant_vol_panel(1, 200, volatility=0.10, seed=11)["asset_00"]
    panel = {"A": list(base), "B": list(base)}
    result = compute_risk_parity_weights(
        RiskBudgetInputs(
            instrument_returns=panel,
            target_risk_contribution={"A": 0.5, "B": 0.5},
        )
    )
    assert as_float(result, key="max_weight_shift_under_stress") == pytest.approx(0.0, abs=1e-9)


# --------------------------------------------------------------------------
# 6. The result contract — ModelResult, confidence, provenance
# --------------------------------------------------------------------------


def _small_result() -> ModelResult:
    panel = _constant_vol_panel(3, 250, volatility=0.10, seed=2)
    names = sorted(panel)
    return compute_risk_parity_weights(
        RiskBudgetInputs(
            instrument_returns=panel,
            target_risk_contribution=dict.fromkeys(names, 1.0 / 3.0),
        )
    )


def test_the_result_carries_a_computed_confidence_not_a_literal() -> None:
    """Section 22.8: confidence is COMPUTED from stated facts.

    The half-way value ``0.5`` is what a hardcoded literal would most likely
    look like, so a bare ``!= 0.5`` is a weak test; the point is that the value
    moves when the *facts* move. A sample covariance is an uncalibrated estimate,
    which is disclosed here — so the confidence must be strictly below the
    top-of-scale a fully-calibrated model would earn.
    """
    result = _small_result()
    assert 0.0 < result.confidence < 1.0, "confidence must be a computed score, not a boundary"
    assert result.data_quality_flags_present is False


def test_the_no_orders_guarantee_is_in_the_published_context() -> None:
    """This function reports weights and NEVER places an order (Section 1.1)."""
    result = _small_result()
    assert "NEVER places an order" in result.context


def test_the_weight_and_contribution_dicts_are_keyed_by_instrument() -> None:
    """A caller must not have to remember a vector's order."""
    result = _small_result()
    for key in ("weights", "risk_contributions", "notional_vs_risk_gap", "stressed_weights"):
        assert set(as_dict(result, key=key)) == {"asset_00", "asset_01", "asset_02"}


def test_weights_sum_to_one_and_are_positive() -> None:
    """The two constraints the caller re-imposes after every CCD sweep."""
    result = _small_result()
    weights = as_dict(result, key="weights")
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-12)
    assert all(w > 0.0 for w in weights.values())


def test_risk_contributions_sum_to_one() -> None:
    """The published contributions must sum to 1 within their **published precision**.

    The function rounds every published number to 10 decimal places (so a desk
    reconciling two runs sees stable digits), which means the summed shares can
    miss 1.0 by up to ``n * 5e-11`` in the last digit. Asserting the *unrounded*
    tolerance here would be asserting a precision the function deliberately does
    not publish — so the tolerance is scaled to the rounding, with the
    instrument count making it explicit rather than a magic constant.
    """
    result = _small_result()
    contributions = as_dict(result, key="risk_contributions")
    n = len(contributions)
    assert sum(contributions.values()) == pytest.approx(1.0, abs=n * 1e-10)


def test_risk_contributions_match_the_hand_computed_euler_split() -> None:
    """``RC_i = w_i (Sigma w)_i / sigma_p^2``, computed independently here.

    The implementation's ``risk_contributions`` is re-derived from the published
    weights and the published covariance so the assertion does not merely call
    the same function twice.
    """
    panel = {"A": [0.02, -0.01, 0.03, -0.02], "B": [0.01, 0.01, -0.01, -0.01]}
    _, covariance = sample_covariance(panel, annualization_periods=252)
    weights = [0.3, 0.7]
    marginal = [sum(covariance[i][j] * weights[j] for j in range(2)) for i in range(2)]
    variance = sum(weights[i] * marginal[i] for i in range(2))
    expected = [weights[i] * marginal[i] / variance for i in range(2)]

    assert risk_contributions(weights, covariance)[0] == pytest.approx(expected[0], rel=1e-12)
    assert risk_contributions(weights, covariance)[1] == pytest.approx(expected[1], rel=1e-12)


# --------------------------------------------------------------------------
# 7. The iteration budget and non-convergence
# --------------------------------------------------------------------------


def test_a_starved_iteration_budget_does_not_raise_but_reports() -> None:
    """Non-convergence is a *result* to report, not an exception to raise.

    Raising would let a caller's ``except`` discard the very weights and the
    worst-error figure the warning is required to quote. The alternative — a
    silent best-iterate dressed as a solution — is worse. So the function
    publishes ``converged=False`` plus the achieved error, and says the weights
    are NOT a solution.
    """
    panel = _constant_vol_panel(4, 300, volatility=0.10, seed=13)
    names = sorted(panel)
    result = compute_risk_parity_weights(
        RiskBudgetInputs(
            instrument_returns=panel,
            target_risk_contribution=dict.fromkeys(names, 0.25),
        ),
        max_iterations=1,
    )
    assert as_bool(result, key="converged") is False
    assert result.data_quality_flags_present is True
    assert as_float(result, key="worst_target_error") > 0.0
    text = " ".join(result.warnings)
    assert "did NOT converge" in text
    assert "NOT a solution" in text


def test_the_solver_converges_well_within_the_default_budget() -> None:
    """The shipped tolerance is reachable on a realistic panel without heroics.

    Together with the starved-budget test this bounds the behaviour from both
    sides: the default must actually converge, and a starved budget must report.
    """
    panel = _constant_vol_panel(5, 500, volatility=0.10, seed=17)
    names = sorted(panel)
    result = compute_risk_parity_weights(
        RiskBudgetInputs(
            instrument_returns=panel,
            target_risk_contribution=dict.fromkeys(names, 0.2),
        )
    )
    assert as_bool(result, key="converged") is True
    assert as_float(result, key="worst_target_error") < 1e-9


def test_a_zero_variance_instrument_is_refused() -> None:
    """A constant series has no risk, so it has no finite risk-parity weight."""
    flat = [0.0] * 50
    panel = {"A": flat, "B": [0.01 if t % 2 == 0 else -0.01 for t in range(50)]}
    with pytest.raises(ValueError, match="non-positive"):
        compute_risk_parity_weights(
            RiskBudgetInputs(
                instrument_returns=panel,
                target_risk_contribution={"A": 0.5, "B": 0.5},
            )
        )


# --------------------------------------------------------------------------
# 8. The config accessors read their leaves, not the shipped literals
# --------------------------------------------------------------------------


def _risk_settings(**overrides: object) -> RiskSettings:
    """A ``RiskSettings`` built from explicit leaves, with the shipped values.

    D-050's accessor blind spot: a test against the *shipped* settings cannot
    tell a live config read from a hardcoded literal, because the two agree.
    This builder exists so a perturbed case can be constructed without copying
    every required leaf — the risk-parity leaves under test are supplied by the
    caller and everything else is the shipped envelope.
    """
    leaves: dict[str, object] = {
        "target_vol_annualized": CalibratedValue(
            value=0.10, calibration_status="institutional_convention"
        ),
        "stress_correlation": CalibratedValue(
            value=0.9, calibration_status="institutional_convention"
        ),
        "var_confidence_levels": CalibratedValue(
            value=[0.95, 0.99], calibration_status="institutional_convention"
        ),
        "historical_var_lookback_days": CalibratedValue(
            value=500, calibration_status="uncalibrated_illustrative"
        ),
        "drawdown_thresholds": {"tiers": []},
        "rebalancing_drift": CalibratedValue(value=0.10, calibration_status="mechanical_rule"),
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
        "risk_parity_annualization_periods_value": CalibratedValue(
            value=252, calibration_status="mechanical_rule"
        ),
        "risk_parity_tolerance_value": CalibratedValue(
            value=1e-10, calibration_status="mechanical_rule"
        ),
        "risk_parity_stress_shift_threshold_value": CalibratedValue(
            value=0.025, calibration_status="uncalibrated_illustrative"
        ),
        # Section 17.4's near-zero bound (D-073). `RiskSettings` has
        # `extra="forbid"` and every leaf is required, so a new leaf must be
        # added to each explicit construction of it.
        "thesis_demotion_fraction_value": CalibratedValue(
            value=0.03, calibration_status="uncalibrated_illustrative"
        ),
    }
    leaves.update(overrides)
    return RiskSettings.model_validate(leaves)


def test_the_risk_parity_accessors_read_their_leaves() -> None:
    """Perturbed leaves must move the accessors (D-050).

    Each accessor is read off a settings object built from *different* numbers,
    so a hardcoded literal — ``return 252``, ``return 1e-10``, ``return 0.025`` —
    fails here even though it would pass against the shipped file.
    """
    perturbed = _risk_settings(
        risk_parity_annualization_periods_value=CalibratedValue(
            value=260, calibration_status="mechanical_rule"
        ),
        risk_parity_tolerance_value=CalibratedValue(
            value=1e-6, calibration_status="mechanical_rule"
        ),
        risk_parity_stress_shift_threshold_value=CalibratedValue(
            value=0.02, calibration_status="uncalibrated_illustrative"
        ),
    )
    assert perturbed.risk_parity_annualization_periods == 260
    assert perturbed.risk_parity_tolerance == pytest.approx(1e-6)
    assert perturbed.risk_parity_stress_shift_threshold == pytest.approx(0.02)


def test_the_shipped_risk_parity_leaves_are_the_documented_values() -> None:
    """The shipped file, pinned, so a silent edit is a failing test.

    252 matches the vol-target block's calendar convention, and the comment in
    ``settings.yaml`` ties the tolerance to the double-precision floor rather
    than to a preference. Pinning the *shipped* values is the complement of the
    perturbed test above: one proves the accessor reads, this proves the file
    says what the notes claim it says.
    """
    risk = get_settings().risk
    assert risk.risk_parity_annualization_periods == 252
    assert risk.risk_parity_tolerance == pytest.approx(1e-10)
    assert risk.risk_parity_stress_shift_threshold == pytest.approx(0.025)


def test_the_annualisation_matches_the_risk_models_calendar_convention() -> None:
    """One book, one calendar: the risk budget must annualise like the risk models.

    The risk-budget block and ``realized_vol_simple`` are the two places a book's
    volatility is annualised, and they must not disagree — otherwise the same
    instrument carries two volatilities and the drift between them reads as
    signal. ``realized_vol_simple``'s convention is a **caller-supplied**
    ``periods_per_year`` whose default is the project's 252-day year (it is a
    field precisely so a monthly caller cannot inherit the daily convention by
    accident; see ``RealizedVolInputs``), and ``volatility_target_scaling``
    likewise takes annualised inputs rather than annualising them.

    So the assertion is that the configured risk-parity calendar **matches the
    default those models are constructed with** — read from the model's own field
    default rather than restated as a literal here, because a second literal is
    exactly how the two would drift apart.
    """
    risk = get_settings().risk
    default_periods = RealizedVolInputs.model_fields["periods_per_year"].default
    assert risk.risk_parity_annualization_periods == default_periods


def test_the_stress_shift_threshold_is_a_live_branch_not_a_round_number() -> None:
    """The threshold must be reachable, not merely plausible.

    The first value written for this leaf was ``0.05`` and the live check showed
    it was **dead code**: the largest single-leg shift under the stressed
    correlation ranges 1.40%..5.75% on the real 5-ETF book (lookbacks 126..1260
    sessions, median 5.22%), so a 5% threshold sat above the median and never
    fired on the configuration most likely to be used.

    Two bounds are therefore asserted, and both are measurements rather than
    preferences. The threshold must be **below** the range's upper end, so the
    escalation branch is reachable at all; and **inside** the position limit, so a
    shift that trips it is material relative to the largest position the hard
    limits permit. A threshold at or above the position limit would make the
    escalation vacuous, and one at 1.0 would be a percent written into a fraction
    field (the D-054 pattern).
    """
    risk = get_settings().risk
    threshold = risk.risk_parity_stress_shift_threshold
    # The measured upper end of the live stress shift — the number that made 0.05
    # dead code and the number a future edit must stay below. Re-derived by
    # `scripts/live_risk_parity_check.py`.
    measured_shift_max = 0.0575
    assert 0.0 < threshold < risk.max_position_fraction
    assert threshold < measured_shift_max, (
        "the escalation branch is dead code: the threshold sits above every shift "
        "the live book produces"
    )
