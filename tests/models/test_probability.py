"""Hand-computed verification tests for models/probability.py (Module 12.3/12.4).

bayesian_update: P(A|B) = P(B|A)P(A) / [P(B|A)P(A) + P(B|~A)P(~A)]
  uninformative band |lr - 1| < 0.25 (config).
  confidence = compute_confidence(is_heuristic_not_calibrated=True) = 0.50.

expected_value: ev = sum(p_i * payoff_i); tail_dominates when ev>0 and
  worst_payoff < -tail_loss_multiple(2.0) * |ev|. confidence = 0.50.

scenario_distribution_status: empty -> empty_no_trade; else calibrated flag decides.

All expectations derived by hand from the formulas and config/settings.yaml.
"""

from __future__ import annotations

import pytest

from macro_engine.models.probability import (
    BayesInputs,
    ScenarioDistributionStatus,
    ScenarioOutcome,
    bayesian_update,
    expected_value,
    scenario_distribution_status,
)


# ---- bayesian_update --------------------------------------------------------
def test_bayesian_posterior_hand_computed():
    res = bayesian_update(BayesInputs(prior=0.5, likelihood_given_true=0.8, likelihood_given_false=0.4))
    # p_b = 0.8*0.5 + 0.4*0.5 = 0.6 ; posterior = 0.4/0.6 = 0.6667
    assert res.value["posterior"] == pytest.approx(2.0 / 3.0, abs=1e-4)
    assert res.value["p_evidence"] == pytest.approx(0.6)
    assert res.value["likelihood_ratio"] == pytest.approx(2.0)
    assert res.value["evidence_informative"] is True  # |2.0-1| = 1.0 > 0.25 band
    assert res.value["shift_pp"] == pytest.approx(100.0 * (2.0 / 3.0 - 0.5), abs=1e-3)
    assert res.confidence == 0.50


def test_bayesian_uninformative_band():
    res = bayesian_update(BayesInputs(prior=0.5, likelihood_given_true=0.5, likelihood_given_false=0.5))
    # lr = 1.0 -> |1-1| = 0 < 0.25 band -> uninformative
    assert res.value["likelihood_ratio"] == pytest.approx(1.0)
    assert res.value["evidence_informative"] is False
    assert res.value["posterior"] == pytest.approx(0.5)  # no move
    assert res.value["shift_pp"] == pytest.approx(0.0)


def test_bayesian_decisive_likelihood_ratio_unbounded():
    res = bayesian_update(BayesInputs(prior=0.5, likelihood_given_true=0.8, likelihood_given_false=0.0))
    # P(B|~A)=0 -> posterior = 0.4 / 0.4 = 1.0, ratio unbounded (None)
    assert res.value["posterior"] == pytest.approx(1.0)
    assert res.value["likelihood_ratio"] is None


def test_bayesian_zero_evidence_raises():
    with pytest.raises(ValueError):
        bayesian_update(BayesInputs(prior=0.5, likelihood_given_true=0.0, likelihood_given_false=0.0))


# ---- expected_value ----------------------------------------------------------
def test_expected_value_hand_computed():
    scenarios = [
        ScenarioOutcome(name="up", probability=0.5, payoff_estimate=10.0),
        ScenarioOutcome(name="down", probability=0.5, payoff_estimate=-2.0),
    ]
    res = expected_value(scenarios)
    assert res.value["ev"] == pytest.approx(4.0)  # 5.0 - 1.0
    assert res.value["contributions"]["up"] == pytest.approx(5.0)
    assert res.value["contributions"]["down"] == pytest.approx(-1.0)
    assert res.value["worst_case_payoff"] == pytest.approx(-2.0)
    assert res.value["total_probability"] == pytest.approx(1.0)
    assert res.value["tail_dominates"] is False
    assert res.confidence == 0.50


def test_expected_value_tail_dominates_warns():
    # ev = 0.99*1000 + 0.01*(-4000) = 990 - 40 = 950 > 0
    # worst -4000 < -2.0*950 = -1900 -> tail dominates
    scenarios = [
        ScenarioOutcome(name="up", probability=0.99, payoff_estimate=1000.0),
        ScenarioOutcome(name="tail", probability=0.01, payoff_estimate=-4000.0),
    ]
    res = expected_value(scenarios)
    assert res.value["ev"] == pytest.approx(950.0)
    assert res.value["tail_dominates"] is True
    assert any("tail" in w.lower() for w in res.warnings)


def test_expected_value_sum_must_be_one():
    scenarios = [
        ScenarioOutcome(name="a", probability=0.5, payoff_estimate=1.0),
        ScenarioOutcome(name="b", probability=0.6, payoff_estimate=1.0),  # sum 1.1
    ]
    with pytest.raises(ValueError):
        expected_value(scenarios)


def test_expected_value_empty_raises():
    with pytest.raises(ValueError):
        expected_value([])


def test_negative_ev_warns():
    scenarios = [
        ScenarioOutcome(name="a", probability=0.5, payoff_estimate=-10.0),
        ScenarioOutcome(name="b", probability=0.5, payoff_estimate=-2.0),
    ]
    res = expected_value(scenarios)
    assert res.value["ev"] == pytest.approx(-6.0)
    assert res.value["tail_dominates"] is False  # ev <= 0 short-circuits
    assert any("non-positive" in w for w in res.warnings)


# ---- scenario_distribution_status -------------------------------------------
def test_status_empty():
    assert scenario_distribution_status([], probabilities_are_calibrated=True) == "empty_no_trade"


def test_status_calibrated():
    sc = [ScenarioOutcome(name="a", probability=1.0, payoff_estimate=1.0)]
    assert scenario_distribution_status(sc, probabilities_are_calibrated=True) == "calibrated"


def test_status_unavailable_when_uncalibrated():
    sc = [ScenarioOutcome(name="a", probability=1.0, payoff_estimate=1.0)]
    assert (
        scenario_distribution_status(sc, probabilities_are_calibrated=False)
        == "SCENARIO_DISTRIBUTION_UNAVAILABLE"
    )


def test_negative_probability_rejected():
    with pytest.raises(Exception):
        ScenarioOutcome(name="a", probability=-0.5, payoff_estimate=1.0)
