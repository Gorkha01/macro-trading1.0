"""``thesis_layer/scenarios.py`` — the four sample defects, and the named test that was missing.

The module docstring lists four measured defects in Section 16.4's sample and
then says the direction-blindness "is pinned by
``test_the_distribution_is_direction_blind`` rather than left to be rediscovered".
MEASURED 2026-10-06: that test did not exist — nor did any test file for this
module (``F-SCN-001``). It is the **fourth** instance of this class in the
campaign, after ``F-SIG-003``, ``F-INV-002`` and ``F-NT-003``.

``F-SCN-002`` is the second finding: ``_PROBABILITY_LEAVES``' comment claims
"this cannot drift when a leaf is added", but the tuple is hardcoded, so a new
probability leaf would silently escape ``scenario_probabilities_are_calibrated``.

Every defect test below FAILS against the specification's sample.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from macro_engine.config import get_settings
from macro_engine.models.probability import ScenarioOutcome
from macro_engine.thesis_layer.scenarios import (
    _PROBABILITY_LEAVES,
    build_scenario_distribution,
    scenario_probabilities_are_calibrated,
)
from macro_engine.thesis_layer.schemas import ConvergenceClassification, MarketPricingGap

_DISTRIBUTABLE = (
    ConvergenceClassification.HIGH,
    ConvergenceClassification.MEDIUM,
    ConvergenceClassification.LOW,
)
_REFUSED = (ConvergenceClassification.CONFLICTED, ConvergenceClassification.NO_SIGNAL)


def _outcome() -> ScenarioOutcome:
    """A minimal valid ScenarioOutcome for constructing KellyInputs in a test."""
    return ScenarioOutcome(
        name="base",
        probability=0.5,
        payoff_estimate=100.0,
        unit="bp_pnl_proxy",
        description="",
    )


def _cal(value: float) -> dict[str, object]:
    """A minimal CalibratedValue payload for constructing config in a test."""
    return {"value": value, "calibration_status": "uncalibrated_illustrative"}


def _gap(
    raw_gap: float = -1.4,
    *,
    dispersion: float = 0.25,
    unit: str = "%",
    is_meaningful: bool = True,
) -> MarketPricingGap:
    return MarketPricingGap(
        model_implied_value=2.9,
        market_implied_value=2.9 - raw_gap,
        raw_gap=raw_gap,
        dispersion=dispersion,
        is_meaningful=is_meaningful,
        unit=unit,
        interpretation="test gap",
    )


# ---------------------------------------------------------------------------
# defect 1 — two branches for a five-member vocabulary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("verdict", _REFUSED)
def test_a_verdict_that_cannot_carry_a_thesis_gets_no_distribution(
    verdict: ConvergenceClassification,
) -> None:
    """The sample's ``else`` gave LOW's 0.30 to CONFLICTED and NO_SIGNAL alike.

    ``MacroThesis`` hard-blocks a live trade on CONFLICTED and NO_SIGNAL has no
    thesis to distribute over, so the producer was emitting a distribution its own
    consumer refuses.
    """
    assert build_scenario_distribution(_gap(), verdict) == []


@pytest.mark.parametrize("verdict", _DISTRIBUTABLE)
def test_a_distributable_verdict_gets_four_branches(verdict: ConvergenceClassification) -> None:
    branches = build_scenario_distribution(_gap(), verdict)
    assert len(branches) == 4
    assert sum(b.probability for b in branches) == pytest.approx(1.0)


def test_the_base_probability_tracks_the_verdict() -> None:
    settings = get_settings().scenario_distribution
    for verdict in _DISTRIBUTABLE:
        branches = build_scenario_distribution(_gap(), verdict)
        assert branches[0].probability == pytest.approx(settings.base_probabilities[verdict.value])


# ---------------------------------------------------------------------------
# defect 2 — `convergence: str` was a bare string
# ---------------------------------------------------------------------------


def test_a_bare_string_verdict_is_parsed_not_mistaken_for_a_member() -> None:
    """``"HIGH"`` has the same hash as the member and passes a membership test.

    The comment claims it would then die on ``.value``; measured, that is exactly
    what a bare str does. Parsing turns both spellings into one behaviour.
    """
    assert hash("HIGH") == hash(ConvergenceClassification.HIGH)
    assert "HIGH" in frozenset(_DISTRIBUTABLE)  # the trap the parse defuses
    with pytest.raises(AttributeError):
        _ = "HIGH".value  # type: ignore[attr-defined]  # a bare str has no .value

    by_member = build_scenario_distribution(_gap(), ConvergenceClassification.HIGH)
    by_string = build_scenario_distribution(_gap(), "HIGH")  # type: ignore[arg-type]
    assert by_member == by_string


def test_a_typo_in_the_verdict_raises() -> None:
    with pytest.raises(ValueError, match="high"):
        build_scenario_distribution(_gap(), "high")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# defect 3 — two incompatible ScenarioOutcome classes
# ---------------------------------------------------------------------------


def test_the_specification_samples_field_name_does_not_construct_the_shipped_class() -> None:
    """The sample writes ``ScenarioOutcome(scenario_name=...)``; the shipped field is ``name``.

    That is the collision D-064 closed (O-51): the producer named a field the
    consumer's class does not have, so the sample could not hand its own output
    to ``apply_fractional_kelly``.
    """
    with pytest.raises(ValidationError):  # pydantic refuses the unknown field
        ScenarioOutcome(scenario_name="base", probability=0.5, payoff_estimate=1.0)  # type: ignore[call-arg]
    ok = ScenarioOutcome(name="base", probability=0.5, payoff_estimate=1.0)
    assert ok.name == "base"


# ---------------------------------------------------------------------------
# defect 4 — `gap.unit` was never read
# ---------------------------------------------------------------------------


def test_an_unconvertible_unit_is_refused_rather_than_scaled() -> None:
    """The sample multiplies by 100 unconditionally — the silent 100x class."""
    with pytest.raises(ValueError, match="cannot convert to a"):
        build_scenario_distribution(_gap(unit="bp"), ConvergenceClassification.HIGH)


def test_the_configured_unit_is_accepted_and_converted_by_the_config_factor() -> None:
    settings = get_settings().scenario_distribution
    branches = build_scenario_distribution(_gap(-1.0), ConvergenceClassification.HIGH)
    assert branches[0].payoff_estimate == pytest.approx(1.0 * settings.bp_per_percent)


def test_a_non_meaningful_gap_is_refused() -> None:
    """Q6 routes it to no_trade_thesis BEFORE Q10; reaching here means Q6 was skipped."""
    with pytest.raises(ValueError, match="is_meaningful is False"):
        build_scenario_distribution(
            _gap(0.05, dispersion=0.25, is_meaningful=False), ConvergenceClassification.HIGH
        )


def test_an_exactly_zero_gap_is_refused() -> None:
    with pytest.raises(ValueError, match="exactly zero"):
        build_scenario_distribution(_gap(0.0, is_meaningful=True), ConvergenceClassification.HIGH)


# ---------------------------------------------------------------------------
# the payoff arithmetic, against the specification's own literals
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("index", "expected"),
    [(0, 100.0), (1, 40.0), (2, -60.0), (3, -150.0)],
)
def test_the_payoffs_match_the_specifications_arithmetic(index: int, expected: float) -> None:
    """Sample: ``abs(gap.raw_gap) * 100``, ``* 40``, ``-* 60``, ``-* 150``.

    The shipped form multiplies a positive magnitude by a configured multiple, so
    the two NEGATIVE branches depend on the config carrying the sign. Measured
    today: ``payoff_multiple_reversal = -0.6`` and ``payoff_multiple_tail =
    -1.5``, so the signs survive.
    """
    branches = build_scenario_distribution(_gap(-1.0), ConvergenceClassification.HIGH)
    assert branches[index].payoff_estimate == pytest.approx(expected)


def test_every_branch_name_is_a_key_the_config_actually_uses() -> None:
    """The ``_BASE``/``_PARTIAL``/... comment: a rename in one place fails loudly."""
    settings = get_settings().scenario_distribution
    branches = build_scenario_distribution(_gap(), ConvergenceClassification.HIGH)
    for branch in branches:
        assert branch.name in settings.payoff_multiples, branch.name
    for branch in branches[1:]:
        assert branch.name in settings.remaining_shares, branch.name


# ---------------------------------------------------------------------------
# (F-SCN-001) the direction-blindness the docstring says is pinned
# ---------------------------------------------------------------------------


def test_the_distribution_is_direction_blind() -> None:
    """(F-SCN-001) The test the module docstring NAMES — it did not exist.

    The magnitude is ``abs(gap.raw_gap)`` and ``gap.direction`` is never read, so
    a +1% and a -1% gap produce byte-identical payoffs AND identical
    probabilities: the whole distribution is a function of ``|raw_gap|`` and the
    verdict. That is a measured boundary (D-064), and a suite written entirely on
    one sign cannot see it — which is how it survived until D-064's live check.
    """
    positive = build_scenario_distribution(_gap(1.0), ConvergenceClassification.HIGH)
    negative = build_scenario_distribution(_gap(-1.0), ConvergenceClassification.HIGH)
    assert positive == negative
    assert [b.payoff_estimate for b in positive] == [100.0, 40.0, -60.0, -150.0]
    # ...and the sign really is available on the gap, for a consumer that needs it.
    assert _gap(1.0).direction == "model_above_market"
    assert _gap(-1.0).direction == "model_below_market"


# ---------------------------------------------------------------------------
# the calibration question (Section 25)
# ---------------------------------------------------------------------------


def test_the_shipped_probabilities_are_not_calibrated() -> None:
    """Measured today: False — so Section 25's sizing prohibition is in force."""
    assert scenario_probabilities_are_calibrated() is False
    assert get_settings().scenario_distribution.base_probability_high.is_trustworthy is False


def test_every_probability_mass_leaf_is_covered_by_the_check() -> None:
    """(F-SCN-002) The comment claims "this cannot drift when a leaf is added".

    The tuple is hardcoded, so it can: a new ``base_probability_*`` or
    ``remaining_share_*`` leaf would silently escape
    ``scenario_probabilities_are_calibrated``, letting a placeholder leaf coexist
    with a True answer and lifting Section 25's prohibition. This binds the tuple
    to the config block's actual probability-mass fields.
    """
    block = get_settings().scenario_distribution
    derived = tuple(
        name
        for name in type(block).model_fields
        if name.startswith(("base_probability_", "remaining_share_"))
    )
    assert derived, "the prefix filter found nothing — the check below would be vacuous"
    assert set(_PROBABILITY_LEAVES) == set(derived), (
        f"declared {sorted(_PROBABILITY_LEAVES)} vs present {sorted(derived)} — a "
        f"probability leaf is not covered by scenario_probabilities_are_calibrated()."
    )
    assert len(_PROBABILITY_LEAVES) == 6


# ---------------------------------------------------------------------------
# The six killing tests (2026-10-09)
# ---------------------------------------------------------------------------
# `mutation_scenario_distribution` reported SIX mutations surviving with no
# proof. They were not false survivors: the test file the sweep originally named
# (`test_scenario_distribution.py`) was DELETED by the `bd96d5c` re-init, and the
# coverage it carried was never replaced. Each test below is aimed at exactly one
# mutant, so the sweep can certify.


def test_the_scenario_outcome_re_export_is_importable_from_the_thesis_layer() -> None:
    """M3.1 — `thesis_layer.schemas` must re-export the producer's class.

    The thesis layer is the schema contract's second home; removing the re-export
    makes `ScenarioOutcome` importable from one layer and not the other. Asserting
    the identity (not merely the import) is what makes the removal observable.
    """
    from macro_engine.models import probability
    from macro_engine.thesis_layer import schemas

    assert schemas.ScenarioOutcome is probability.ScenarioOutcome


def test_high_convergence_carries_the_high_base_probability_not_the_low_one() -> None:
    """M6.1 — reading HIGH's base case from the LOW leaf reverses the ordering.

    The distribution is only meaningful if the highest-convergence verdict carries
    the highest base probability. The assertion is the ORDER, which is what the
    mutation breaks.
    """
    probs = get_settings().scenario_distribution.base_probabilities
    assert probs["HIGH"] > probs["LOW"]


def test_remaining_shares_that_do_not_sum_to_one_are_refused() -> None:
    """M6.3 — the sum-to-one constraint on the remaining shares.

    They are the split of (1 - base_probability) across the three non-base
    branches, so their sum IS the total probability of the non-base case. With the
    guard removed the four published probabilities do not sum to 1 and NO single
    leaf shows why (O-41's shape).
    """
    from macro_engine.config import ScenarioDistributionSettings

    live = get_settings().scenario_distribution
    assert sum(live.remaining_shares.values()) == pytest.approx(1.0)

    # A config whose shares sum to 1.5 must not load. The payload starts from the
    # LIVE settings (so every required leaf is present and valid) and overrides
    # only the shares — isolating the sum guard as the thing that refuses.
    payload = live.model_dump()
    payload["remaining_share_partial_close"] = _cal(0.5)
    payload["remaining_share_reversal"] = _cal(0.5)
    payload["remaining_share_tail"] = _cal(0.5)  # 1.5, not 1.0
    with pytest.raises((ValueError, ValidationError), match=r"sum|1\.0"):
        ScenarioDistributionSettings(**payload)


def test_the_published_payoff_unit_is_the_bp_proxy_not_the_kelly_unit() -> None:
    """M7.3 — the scenario distribution publishes a bp P&L proxy.

    Publishing `fraction_of_capital` instead would let a bp distribution be read
    as if its payoffs were fractions of capital — the unit confusion the named
    refusal exists to prevent.
    """
    gap = _gap()
    conv = ConvergenceClassification.HIGH
    outcomes = build_scenario_distribution(gap, conv)
    assert outcomes, "a HIGH-convergence gap must produce a distribution"
    assert {o.unit for o in outcomes} == {"bp_pnl_proxy"}


def test_a_kelly_input_without_a_payoff_unit_is_refused() -> None:
    """M9.1 — `payoff_unit` must stay REQUIRED.

    A default re-introduces exactly the failure the field was added to fix: a bp
    or dollar payoff silently sized by fraction-of-capital arithmetic, returning a
    plausible number.
    """
    from macro_engine.portfolio.risk_budget import KellyInputs, RiskLimits

    with pytest.raises(ValidationError, match=r"payoff_unit"):
        KellyInputs(  # type: ignore[call-arg]
            scenarios=[_outcome()],
            limits=RiskLimits.from_settings(),
        )


def test_a_non_fraction_payoff_unit_is_refused_by_name() -> None:
    """M9.3 — the named refusal, not a silent mis-sizing.

    `KellyPayoffUnit` admits two members; the validator refuses the one the Kelly
    arithmetic cannot consume, so a declared bp distribution is rejected rather
    than sized as if its payoffs were fractions of capital.
    """
    from macro_engine.portfolio.risk_budget import KellyInputs, RiskLimits

    # ⚠️ **This test passed for the WRONG reason and the mutant SURVIVED it —
    # measured 2026-10-09.** It originally passed `scenarios=[]`, which is invalid
    # on its own, and matched on the bare word `payoff_unit`, which appears in
    # pydantic's field listing regardless. So removing the refusal changed
    # nothing the test looked at. The payload must now be VALID apart from the
    # unit, and the match is the refusal's OWN phrase.
    with pytest.raises(ValidationError, match=r"Kelly arithmetic"):
        KellyInputs(
            scenarios=[_outcome()],
            limits=RiskLimits.from_settings(),
            payoff_unit="bp_pnl_proxy",
        )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
