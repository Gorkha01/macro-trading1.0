"""Tests for Module 12.3/12.4 — ``bayesian_update`` and ``expected_value``.

Section 11.1 mandates three of these **by name**:

* ``test_bayesian_update_matches_hand_calculation`` — prior 0.40, P(B|A) 0.70,
  P(B|¬A) 0.20 must return posterior **0.70**
* ``test_bayesian_update_lr_near_one_warns`` — the uninformative-evidence warning
  must fire
* ``test_expected_value_rejects_bad_probabilities`` — probabilities not summing
  to 1.0 must raise

Four findings shape the rest (D-042):

1. **The confidences were hardcoded** (0.8 and 0.6) and, for the Bayesian case,
   claimed something the inputs do not support.
2. **The likelihood-ratio band was asymmetric by accident** — Section 20.11's
   ``0.8 < lr < 1.25`` treats two equally-uninformative ratios as different
   distances from 1.0.
3. **Neither function validated its inputs.** A prior of 1.5 was accepted, and a
   **negative probability** passed the sum-to-one check whenever another scenario
   exceeded one.
4. **The tail threshold and the sum tolerance were inline literals.**

Every config-derived value is patched to a leaf the literal cannot produce, and
synthetic leaves are DISTINCT so an accessor swap cannot hide (D-035).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pydantic import ValidationError

from macro_engine.config import CalibratedValue, ProbabilitySettings, get_settings
from macro_engine.models.contracts import ConfidenceInputs, compute_confidence
from macro_engine.models.probability import (
    BayesInputs,
    ScenarioOutcome,
    bayesian_update,
    expected_value,
)
from tests.helpers import as_bool, as_float, as_int, as_str


def _prob_leaf(value: float | int) -> CalibratedValue:
    """A synthetic config leaf whose value this test chose."""
    return CalibratedValue(
        value=value,
        calibration_status="fitted_assumption",
        note="synthetic — chosen by this test to be distinct from every other leaf",
    )


def _prob_settings() -> ProbabilitySettings:
    return get_settings().probability


def _bayes(*, prior: float = 0.40, lrt: float = 0.70, lrf: float = 0.20) -> BayesInputs:
    return BayesInputs(prior=prior, likelihood_given_true=lrt, likelihood_given_false=lrf)


def _scenario(name: str, probability: float, payoff: float) -> ScenarioOutcome:
    return ScenarioOutcome(name=name, probability=probability, payoff_estimate=payoff)


# ---------------------------------------------------------------------------
# Section 11.1's three mandated tests, by name
# ---------------------------------------------------------------------------


def test_bayesian_update_matches_hand_calculation() -> None:
    """Section 11.1's mandated value, reproduced exactly.

    Hand computation:
        P(B)      = 0.70 * 0.40 + 0.20 * 0.60 = 0.28 + 0.12 = 0.40
        P(A|B)    = 0.28 / 0.40 = 0.70

    The posterior is compared against the PUBLISHED value, which the model
    rounds to four places — floating-point division of the same inputs can land
    a bit either side of 0.7, and the published figure is what a consumer reads.
    """
    result = bayesian_update(_bayes(prior=0.40, lrt=0.70, lrf=0.20))
    assert as_float(result, key="posterior") == 0.7
    assert as_float(result, key="p_evidence") == pytest.approx(0.40)
    assert as_float(result, key="likelihood_ratio") == pytest.approx(3.5)
    assert as_float(result, key="shift_pp") == pytest.approx(30.0)


def test_bayesian_update_lr_near_one_warns() -> None:
    """Section 11.1's mandated warning.

    An LR of exactly 1.0 means the evidence is equally likely under both
    hypotheses — it carries no information at all, and the posterior cannot
    move. That must be said rather than left for the reader to notice.
    """
    result = bayesian_update(_bayes(prior=0.40, lrt=0.50, lrf=0.50))
    assert as_float(result, key="likelihood_ratio") == pytest.approx(1.0)
    assert as_bool(result, key="evidence_informative") is False
    matches = [w for w in result.warnings if "barely" in w]
    assert len(matches) == 1, "the uninformative-evidence warning must fire exactly once"
    assert "noise" in matches[0], "the warning must say what the shift is not"


def test_expected_value_rejects_bad_probabilities() -> None:
    """Section 11.1's mandated refusal."""
    with pytest.raises(Exception, match="sum to"):
        expected_value(
            [
                _scenario("a", 0.50, 10.0),
                _scenario("b", 0.20, -5.0),
            ]
        )


# ---------------------------------------------------------------------------
# bayesian_update — the arithmetic and its bounds
# ---------------------------------------------------------------------------


def test_the_posterior_is_recomputable_from_its_published_components() -> None:
    """The cross-field identity (D-009)."""
    for prior, lrt, lrf in ((0.4, 0.7, 0.2), (0.5, 0.5, 0.5), (0.9, 0.6, 0.5), (0.1, 0.9, 0.1)):
        result = bayesian_update(_bayes(prior=prior, lrt=lrt, lrf=lrf))
        p_b = as_float(result, key="p_evidence")
        expected = (lrt * prior) / p_b
        assert as_float(result, key="posterior") == pytest.approx(expected, abs=1e-4)
        assert as_float(result, key="p_evidence") == pytest.approx(lrt * prior + lrf * (1 - prior))
        assert as_float(result, key="shift_pp") == pytest.approx((expected - prior) * 100, abs=1e-3)


def test_a_strong_prior_resists_weak_evidence() -> None:
    """The module's stated purpose: this is arithmetic, not a disposition.

    The same weak evidence (LR 1.2) moves a 50% prior much further than a 90%
    one — which is why a confident thesis requires a high likelihood ratio to
    change, and why the LR is published alongside the shift.
    """
    weak = _bayes(prior=0.50, lrt=0.60, lrf=0.50)
    confident = _bayes(prior=0.90, lrt=0.60, lrf=0.50)
    weak_shift = abs(as_float(bayesian_update(weak), key="shift_pp"))
    confident_shift = abs(as_float(bayesian_update(confident), key="shift_pp"))
    assert confident_shift < weak_shift, (
        "the same likelihood ratio must move a confident prior LESS, or the "
        "model is not doing Bayes"
    )


def test_a_decisive_evidence_reports_an_unbounded_ratio() -> None:
    """P(B|~A) = 0 makes the ratio infinite, and it is reported as None.

    `inf` does not survive serialisation and reads as a number in a report, so
    the absence is explicit rather than an infinity.
    """
    result = bayesian_update(_bayes(prior=0.4, lrt=0.7, lrf=0.0))
    value = result.value
    assert isinstance(value, dict)
    assert value["likelihood_ratio"] is None
    assert as_bool(result, key="evidence_informative") is True
    assert "unbounded" in result.interpretation


def test_impossible_evidence_under_both_hypotheses_is_refused() -> None:
    """P(B) = 0 means the observation cannot occur, so no posterior exists."""
    with pytest.raises(Exception, match="impossible under both"):
        bayesian_update(_bayes(prior=0.4, lrt=0.0, lrf=0.0))


def test_a_certain_prior_cannot_be_moved_and_says_so() -> None:
    """A prior of exactly 0 or 1 is a claim no observation could revise."""
    for certain in (0.0, 1.0):
        result = bayesian_update(_bayes(prior=certain, lrt=0.7, lrf=0.2))
        assert as_float(result, key="posterior") == pytest.approx(certain)
        assert any("no evidence can move" in w for w in result.warnings), (
            f"a prior of exactly {certain} must be disclosed as unfalsifiable"
        )


def test_every_probability_input_is_bounded() -> None:
    """Section 20.11 applies no bounds; a posterior that is not a probability
    would flow out silently."""
    for kwargs in (
        {"prior": 1.5},
        {"prior": -0.1},
        {"lrt": 1.2},
        {"lrt": -0.2},
        {"lrf": 2.0},
        {"lrf": -0.5},
    ):
        base = {"prior": 0.4, "lrt": 0.7, "lrf": 0.2}
        base.update(kwargs)
        with pytest.raises(ValidationError):
            BayesInputs(
                prior=base["prior"],
                likelihood_given_true=base["lrt"],
                likelihood_given_false=base["lrf"],
            )


def test_the_uninformative_band_comes_from_config() -> None:
    """Patched to a band the shipped 0.25 cannot produce."""
    patched = _prob_settings().model_copy(update={"uninformative_lr_band_value": _prob_leaf(0.001)})
    with patch("macro_engine.models.probability._probability_settings", return_value=patched):
        result = bayesian_update(_bayes(prior=0.4, lrt=0.70, lrf=0.20))
    assert as_bool(result, key="evidence_informative") is True, (
        "with a 0.001 band an LR of 3.5 is clearly informative"
    )
    assert not any("barely" in w for w in result.warnings)
    assert _prob_settings().uninformative_lr_band != 0.001


def test_the_band_is_symmetric() -> None:
    """Section 20.11's `0.8 < lr < 1.25` is asymmetric by accident.

    An LR of 1/1.25 = 0.8 and an LR of 1.25 are the same distance from
    uninformative in log-space, and the model now treats them identically.
    """
    band = _prob_settings().uninformative_lr_band
    # The ratio is what matters, and both likelihoods are bounded to [0, 1] --
    # so an LR of 1.24 comes from 0.62/0.50, not from a likelihood of 1.24. The
    # first version of this test passed 1.24 directly and was refused by the
    # bound, which is the bound working.
    base_likelihood = 0.5
    low = bayesian_update(
        _bayes(prior=0.5, lrt=(1.0 - band + 0.01) * base_likelihood, lrf=base_likelihood)
    )
    high = bayesian_update(
        _bayes(prior=0.5, lrt=(1.0 + band - 0.01) * base_likelihood, lrf=base_likelihood)
    )
    assert as_float(low, key="likelihood_ratio") == pytest.approx(1.0 - band + 0.01, abs=1e-4)
    assert as_float(high, key="likelihood_ratio") == pytest.approx(1.0 + band - 0.01, abs=1e-4)
    assert as_bool(low, key="evidence_informative") is False
    assert as_bool(high, key="evidence_informative") is False, (
        "the band must be symmetric around 1.0"
    )


def test_the_band_boundary_is_strict() -> None:
    """An LR EXACTLY at the band is informative — the comparison is strict.

    The other band tests sit just inside and just outside; none lands ON the
    boundary, so a mutation making the comparison non-strict changed nothing they
    asserted and survived. Built as an exact ratio (0.625 / 0.5 = 1.25) so the
    point under test is on the boundary rather than near it.
    """
    band = _prob_settings().uninformative_lr_band
    base = 0.5
    at = bayesian_update(_bayes(prior=0.5, lrt=(1.0 + band) * base, lrf=base))
    assert as_float(at, key="likelihood_ratio") == pytest.approx(1.0 + band)
    assert as_bool(at, key="evidence_informative") is True, (
        "an LR exactly at the band is NOT within it — the comparison is strict"
    )
    inside = bayesian_update(_bayes(prior=0.5, lrt=(1.0 + band - 1e-9) * base, lrf=base))
    assert as_bool(inside, key="evidence_informative") is False


def test_the_likelihoods_caveat_is_stated() -> None:
    """The posterior is only as good as the two likelihoods.

    A mutation removing this survived the first sweep because no test asserted
    it — the uninformative and certain-prior warnings were covered and this one
    was not.
    """
    result = bayesian_update(_bayes())
    matches = [w for w in result.warnings if "least defensible numbers" in w]
    assert len(matches) == 1, (
        f"the likelihoods caveat must appear exactly once; found {len(matches)}"
    )


def test_bayesian_confidence_is_computed_not_asserted() -> None:
    """Section 22.8 — the specification hardcodes 0.8."""
    result = bayesian_update(_bayes())
    expected = compute_confidence(
        ConfidenceInputs(is_heuristic_not_calibrated=True, source_independence_count=0)
    )
    assert result.confidence == pytest.approx(expected)


# ---------------------------------------------------------------------------
# expected_value — the arithmetic, the tail, and the bounds
# ---------------------------------------------------------------------------


def test_the_expected_value_matches_a_hand_calculation() -> None:
    """0.7 * 10 + 0.3 * (-100) = 7 - 30 = -23."""
    result = expected_value([_scenario("base", 0.7, 10.0), _scenario("tail", 0.3, -100.0)])
    assert as_float(result, key="ev") == pytest.approx(-23.0)
    assert as_float(result, key="worst_case_payoff") == pytest.approx(-100.0)
    assert as_str(result, key="worst_case_name") == "tail"
    assert as_int(result, key="n_scenarios") == 2


def test_the_ev_is_recomputable_from_its_published_contributions() -> None:
    """The cross-field identity (D-009)."""
    scenarios = [
        _scenario("a", 0.5, 12.0),
        _scenario("b", 0.3, -4.0),
        _scenario("c", 0.2, 30.0),
    ]
    result = expected_value(scenarios)
    value = result.value
    assert isinstance(value, dict)
    contributions = value["contributions"]
    assert isinstance(contributions, dict)
    # The presence half: iterating an empty dict would make this test vacuous.
    assert set(contributions) == {"a", "b", "c"}, "every scenario must be published"
    assert as_float(result, key="ev") == pytest.approx(sum(contributions.values()), abs=1e-4)


def test_a_positive_ev_with_a_dominant_tail_warns() -> None:
    """The LTCM lesson, which is the reason this function reports the worst case.

    0.95 * 10 + 0.05 * (-100) = 9.5 - 5 = +4.5, and the tail (-100) is far more
    than twice the average — so the mean is positive and the position is still
    unsurvivable.
    """
    result = expected_value([_scenario("base", 0.95, 10.0), _scenario("crash", 0.05, -100.0)])
    assert as_float(result, key="ev") == pytest.approx(4.5)
    assert as_bool(result, key="tail_dominates") is True
    matches = [w for w in result.warnings if "SURVIVAL" in w]
    assert len(matches) == 1, "the tail warning must fire exactly once"
    assert "LTCM" in matches[0]


def test_a_small_tail_does_not_warn() -> None:
    """The absence half: an ordinary downside must not raise the alarm."""
    result = expected_value([_scenario("base", 0.8, 10.0), _scenario("mild", 0.2, -2.0)])
    assert as_float(result, key="ev") == pytest.approx(7.6)
    assert as_bool(result, key="tail_dominates") is False
    assert not any("SURVIVAL" in w for w in result.warnings)


def test_a_non_positive_ev_is_disclosed_as_unrescuable() -> None:
    result = expected_value([_scenario("base", 0.7, 10.0), _scenario("tail", 0.3, -100.0)])
    assert as_float(result, key="ev") < 0
    assert any("no sizing rule rescues it" in w for w in result.warnings)


def test_the_average_is_not_a_path_warning_is_stated() -> None:
    """Every EV carries the reminder that an average describes no single path.

    A mutation removing it survived the first sweep — the tail and non-positive
    warnings were asserted and this one was not.
    """
    result = expected_value([_scenario("a", 0.5, 10.0), _scenario("b", 0.5, -4.0)])
    matches = [w for w in result.warnings if "average over branches" in w]
    assert len(matches) == 1, (
        f"the average-is-not-a-path warning must appear exactly once; found {len(matches)}"
    )
    assert "worst case" in matches[0], "it must state the worst case it is contrasting"


def test_the_tail_boundary_is_strict() -> None:
    """A tail EXACTLY at the configured multiple does not dominate.

    The fixture is DERIVED from the multiple so it lands on the boundary for any
    configured value: with p = 0.5 and a tail of -W the EV is (P - W)/2, and
    W = multiple * |EV| solves to P = W * (1 + 2/multiple).
    """
    multiple = _prob_settings().tail_loss_multiple
    tail_loss = 10.0
    base_gain = tail_loss * (1.0 + 2.0 / multiple)
    at = expected_value(
        [
            _scenario("base", 0.5, base_gain),
            _scenario("tail", 0.5, -tail_loss),
        ]
    )
    ev = as_float(at, key="ev")
    assert ev > 0.0, "the boundary case needs a positive EV or tail_dominates is unreachable"
    assert abs(tail_loss - multiple * abs(ev)) < 1e-9, "the fixture is not on the boundary"
    assert as_bool(at, key="tail_dominates") is False, (
        "a tail exactly at the multiple is not BEYOND it — the comparison is strict"
    )
    past = expected_value(
        [
            _scenario("base", 0.5, base_gain),
            _scenario("tail", 0.5, -tail_loss - 0.01),
        ]
    )
    assert as_bool(past, key="tail_dominates") is True


def test_the_tail_multiple_comes_from_config() -> None:
    """Patched beyond any plausible tail, so nothing can dominate."""
    patched = _prob_settings().model_copy(update={"tail_loss_multiple_value": _prob_leaf(999.0)})
    with patch("macro_engine.models.probability._probability_settings", return_value=patched):
        result = expected_value([_scenario("base", 0.95, 10.0), _scenario("crash", 0.05, -100.0)])
    assert as_bool(result, key="tail_dominates") is False
    assert not any("SURVIVAL" in w for w in result.warnings)
    assert _prob_settings().tail_loss_multiple != 999.0


def test_the_sum_tolerance_comes_from_config() -> None:
    """Patched to a wide tolerance so a mis-summed set is accepted."""
    shipped = expected_value([_scenario("a", 0.5, 1.0), _scenario("b", 0.5, 1.0)])
    assert as_float(shipped, key="total_probability") == pytest.approx(1.0)

    patched = _prob_settings().model_copy(
        update={"probability_sum_tolerance_value": _prob_leaf(0.5)}
    )
    with patch("macro_engine.models.probability._probability_settings", return_value=patched):
        result = expected_value([_scenario("a", 0.5, 1.0), _scenario("b", 0.2, 1.0)])
    assert as_float(result, key="total_probability") == pytest.approx(0.7), (
        "a 0.5 tolerance must accept a set summing to 0.7"
    )
    assert _prob_settings().probability_sum_tolerance != 0.5


def test_a_negative_probability_is_refused_per_value() -> None:
    """The gap the sum-to-one check cannot close.

    `1.5 + (-0.5) = 1.0`, so a set containing an impossible probability passes
    the sum test. Only a per-value bound catches it.
    """
    with pytest.raises(Exception, match="probability"):
        _scenario("impossible", -0.5, 1.0)
    with pytest.raises(Exception, match="probability"):
        _scenario("over_certain", 1.5, 1.0)


def test_an_empty_scenario_set_is_refused_for_the_right_reason() -> None:
    """The error must be about emptiness, not about a sum of zero."""
    with pytest.raises(Exception, match="no scenarios"):
        expected_value([])


def test_a_nameless_scenario_is_refused() -> None:
    """The worst case must be nameable in the output."""
    with pytest.raises(Exception, match="name"):
        _scenario("", 0.5, 1.0)


def test_the_input_contract_forbids_extra_fields() -> None:
    with pytest.raises(Exception, match="payoff"):
        ScenarioOutcome(  # type: ignore[call-arg]
            name="a",
            probability=0.5,
            payoff_estimate=1.0,
            payoff=1.0,
        )


def test_expected_value_confidence_is_computed_not_asserted() -> None:
    """Section 22.8 — the specification hardcodes 0.6."""
    result = expected_value([_scenario("a", 1.0, 1.0)])
    expected = compute_confidence(
        ConfidenceInputs(is_heuristic_not_calibrated=True, source_independence_count=0)
    )
    assert result.confidence == pytest.approx(expected)
