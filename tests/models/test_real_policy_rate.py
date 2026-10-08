"""Hand-computed verification tests for models/real_policy_rate.py (Module 3.6).

r_real = i - pi  (ex-post Fisher decomposition, both terms observed).
Confidence is compute_confidence() with NO penalty flags -> equals the configured
base (0.70). Verified by hand from contracts.compute_confidence and
config.confidence.values.base.
"""

from __future__ import annotations

import pytest

from macro_engine.config import get_settings
from macro_engine.models.real_policy_rate import (
    RealPolicyRateInputs,
    real_policy_rate,
)


def test_positive_real_rate() -> None:
    res = real_policy_rate(RealPolicyRateInputs(nominal_policy_rate=5.0, inflation_rate=2.0))
    # 5.0 - 2.0 = 3.0, rounded to 3 dp.
    assert res.value == pytest.approx(3.0)
    assert "real policy rate is +3.00%" in res.interpretation
    # No penalty flags set -> confidence == configured base.
    assert res.confidence == pytest.approx(0.70)
    assert res.inputs_used == ["nominal_policy_rate", "inflation_rate"]


def test_negative_real_rate() -> None:
    res = real_policy_rate(RealPolicyRateInputs(nominal_policy_rate=1.0, inflation_rate=3.0))
    # 1.0 - 3.0 = -2.0.
    assert res.value == pytest.approx(-2.0)
    assert "real policy rate is -2.00%" in res.interpretation
    assert res.confidence == pytest.approx(0.70)


def test_zero_real_rate_and_confidence_is_base() -> None:
    settings = get_settings()
    base = settings.confidence.values["base"]
    res = real_policy_rate(RealPolicyRateInputs(nominal_policy_rate=4.0, inflation_rate=4.0))
    assert res.value == pytest.approx(0.0)
    # +0.00% formatting.
    assert "real policy rate is +0.00%" in res.interpretation
    assert res.confidence == pytest.approx(round(base, 3))


def test_pi_target_appears_in_warning() -> None:
    pi_target = get_settings().policy.pi_target_value
    res = real_policy_rate(RealPolicyRateInputs(nominal_policy_rate=2.0, inflation_rate=2.0))
    assert any(f"{pi_target:.1f}" in w for w in res.warnings)


def test_pi_target_is_described_as_pce_specific_and_as_a_target_not_a_forecast() -> None:
    """F-RPR-001: the caveat used to name the 2% objective in a sentence about
    EXPECTED inflation — three mismatches in one clause.

    (a) measure: `policy.pi_target` is declared `institutional_fact` with the
        note "FOMC's longer-run inflation objective, 2% on PCE", while this
        function accepts ANY year-over-year measure. A CPI-based run was
        therefore citing a PCE-specific fact.
    (b) concept: the sentence is about EXPECTED inflation and then quotes the
        TARGET — the exact conflation it disclaims.
    (c) role: a target is deliberately not a forecast, so it cannot stand in
        for the omitted expectations term.

    The fixed text must (1) keep naming the target so the reader can find it,
    (2) say PCE, and (3) say "target, not a forecast".
    """
    res = real_policy_rate(RealPolicyRateInputs(nominal_policy_rate=5.25, inflation_rate=3.0))
    quoted = [w for w in res.warnings if "2.0%" in w]
    assert quoted, "the target should still be named so a reader can locate it"
    for w in quoted:
        assert "PCE" in w, "the target's measure (PCE) must be stated"
        assert "TARGET" in w.upper(), "its role as a target, not a forecast, must be stated"


def test_the_measure_independence_caveat_is_present_and_names_the_alternative_measures() -> None:
    """The function cannot constrain the measure, so it must SAY so.

    PCE and CPI are independent production processes in this project's own
    registry (BEA_PCE vs BLS_CPI), so the two answers genuinely differ.
    """
    res = real_policy_rate(RealPolicyRateInputs(nominal_policy_rate=4.33, inflation_rate=3.4))
    w = " ".join(res.warnings)
    assert "CPI" in w and "PCE" in w
    assert "record" in w.lower(), "the caveat must ask for the measure to be recorded"


def test_two_measures_give_two_different_answers_from_one_nominal_rate() -> None:
    """The consequence, measured: same policy rate, different measure, different
    real rate. 4.33 - 2.6 (PCE) = 1.73 vs 4.33 - 3.4 (CPI) = 0.93.
    """
    pce = real_policy_rate(RealPolicyRateInputs(nominal_policy_rate=4.33, inflation_rate=2.6))
    cpi = real_policy_rate(RealPolicyRateInputs(nominal_policy_rate=4.33, inflation_rate=3.4))
    assert pce.value == 1.73
    assert cpi.value == 0.93
    assert pce.value != cpi.value


def test_non_finite_inputs_rejected() -> None:
    with pytest.raises(ValueError):
        RealPolicyRateInputs(nominal_policy_rate=float("nan"), inflation_rate=2.0)
    with pytest.raises(ValueError):
        RealPolicyRateInputs(nominal_policy_rate=2.0, inflation_rate=float("inf"))


# --------------------------------------------------------------------------
# Added by the D-139-series review pass: arithmetic pinned as literals rather
# than pytest.approx, the plus-zero contract, and the 3dp-vs-2dp split.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("nominal", "inflation", "expected"),
    [
        (5.25, 3.00, 2.25),
        (5.25, 5.25, 0.00),
        (0.00, 3.00, -3.00),
        (5.00, -2.00, 7.00),
        (5.25, 7.00, -1.75),
    ],
)
def test_arithmetic_exact_as_literals(nominal: float, inflation: float, expected: float) -> None:
    """Exact equality, not approx: the operation is one subtraction of two
    doubles and the result is rounded to 3dp, so there is no floating slack
    that `approx` needs to absorb. `approx` here would hide a real regression
    in the rounding.
    """
    res = real_policy_rate(
        RealPolicyRateInputs(nominal_policy_rate=nominal, inflation_rate=inflation)
    )
    assert res.value == expected


def test_zero_is_positive_zero_never_negative_zero() -> None:
    """i == pi must publish +0.0 and print "+0.00%", not "-0.00%".

    `i - pi` on two equal doubles is +0.0, but a refactor to `-(pi - i)` gives
    -0.0 and renders "-0.00%". The same negative-zero shape was a real defect in
    equity_macro (F-EM-002), so the contract is pinned here before a refactor
    can introduce it.
    """
    res = real_policy_rate(RealPolicyRateInputs(nominal_policy_rate=3.0, inflation_rate=3.0))
    assert repr(res.value) == "0.0"
    assert "-0.00%" not in res.interpretation
    assert "+0.00%" in res.interpretation


def test_value_keeps_three_dp_while_the_prose_shows_two() -> None:
    """The published value and the display string are allowed to differ.

    Hand: 5.2525 - 3.1234 = 2.1291 -> value round(...,3) = 2.129, while the
    interpretation formats to 2dp (+2.13%). Pinning both makes the split
    explicit, so a change to either is visible rather than assumed harmless.
    """
    res = real_policy_rate(RealPolicyRateInputs(nominal_policy_rate=5.2525, inflation_rate=3.1234))
    assert res.value == 2.129
    assert "+2.13%" in res.interpretation


def test_confidence_is_untouched_by_the_input_values() -> None:
    """No input can move confidence: no flag is keyed on any threshold.

    If this fails, a graded threshold was introduced, which would make the
    arithmetic a heuristic and require the penalty this module declines.
    """
    seen = set()
    for nominal, inflation in [(5.25, 3.0), (0.0, 0.0), (-5.0, 20.0), (99.0, -1.0)]:
        res = real_policy_rate(
            RealPolicyRateInputs(nominal_policy_rate=nominal, inflation_rate=inflation)
        )
        seen.add(res.confidence)
    assert seen == {0.70}


def test_confidence_does_not_carry_the_heuristic_penalty() -> None:
    """Distinguish "no flags" from "the heuristic flag only".

    Both penalties are 0.20, so asserting the NUMBER 0.70 alone would not catch
    a refactor that swapped `depends_on_unobservable=False` for
    `is_heuristic_not_calibrated=True`. Assert the number is the unpenalised
    base and is not the heuristic result.
    """
    from macro_engine.models.contracts import ConfidenceInputs, compute_confidence

    assert compute_confidence(ConfidenceInputs()) == 0.70
    assert compute_confidence(ConfidenceInputs(is_heuristic_not_calibrated=True)) == 0.50
    res = real_policy_rate(RealPolicyRateInputs(nominal_policy_rate=5.25, inflation_rate=3.0))
    assert res.confidence == 0.70
    assert res.confidence != 0.50


def test_ex_post_caveat_is_unconditional() -> None:
    """It is a property of the FORM, asserted for every input including the
    neutral one — the module does not gate it on the level of the result.
    """
    for nominal, inflation in [(5.25, 3.0), (5.0, 5.0), (0.0, 0.0), (-1.0, 9.0)]:
        res = real_policy_rate(
            RealPolicyRateInputs(nominal_policy_rate=nominal, inflation_rate=inflation)
        )
        assert any("Ex-post, not ex-ante" in w for w in res.warnings)


def test_inputs_are_required_and_extra_fields_are_forbidden() -> None:
    """A default on either term would be a second source of truth that silently
    wins when a caller omits it (the same rule phillips.beta is subject to).
    """
    with pytest.raises(ValueError):
        RealPolicyRateInputs(inflation_rate=3.0)  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        RealPolicyRateInputs(nominal_policy_rate=5.0)  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        RealPolicyRateInputs(nominal_policy_rate=5.0, inflation_rate=3.0, unexpected=1.0)  # type: ignore[call-arg]
