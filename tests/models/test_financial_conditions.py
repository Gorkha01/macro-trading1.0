"""Tests for Module 12 — ``compute_fci``.

Five things shape what is worth asserting (D-038):

1. **The Finding #7 correction is the whole point.** Section 22.7 exists because
   the earlier version weighted *raw mixed-unit deviations*. The property that
   distinguishes the two is **scale invariance**: a z-score is unchanged if a
   component's value, mean and standard deviation are all rescaled together,
   while a raw deviation would scale with them. That is asserted directly, and
   it is the test that fails if the division is removed.
2. **The equity sign is negated.** Section 22.7 writes ``- w_equity*z_equity``,
   and an inverted sign flips the index's entire interpretation while leaving
   every number plausible — the D-034 failure mode. Asserted against a series
   whose direction is known before the call.
3. **The NFCI cross-check is part of the contract.** Section 21.1 calls it
   mandatory, so the *absence* of a cross-check must be as loud as a divergence.
4. **The component set is a contract between config and model.** A component on
   one side only is silently dropped from, or added to, the composite.
5. **The config's stored averages were materially wrong and are gone.** The
   z-score denominators are supplied by the caller; nothing is frozen.

Every config-derived value is patched to a leaf the literal cannot produce.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from macro_engine.config import CalibratedValue, FCISettings, get_settings
from macro_engine.models.contracts import ConfidenceInputs, compute_confidence
from macro_engine.models.financial_conditions import (
    FCIComponent,
    FCIInputs,
    compute_fci,
)
from tests.helpers import as_bool, as_float, as_int


def _leaf(value: float | int) -> CalibratedValue:
    """A synthetic config leaf whose value this test chose."""
    return CalibratedValue(
        value=value,
        calibration_status="fitted_assumption",
        note="synthetic — chosen by this test to be distinct from every other leaf",
    )


def _settings() -> FCISettings:
    return get_settings().fci


def _c(value: float, mean: float, std: float) -> FCIComponent:
    return FCIComponent(value=value, mean=mean, std=std)


def _inputs(
    *,
    policy: tuple[float, float, float] = (5.0, 2.5, 1.0),
    credit: tuple[float, float, float] = (5.0, 4.0, 1.0),
    term: tuple[float, float, float] = (1.0, 0.5, 0.5),
    equity: tuple[float, float, float] = (10.0, 0.0, 10.0),
    usd: tuple[float, float, float] = (5.0, 0.0, 5.0),
    window: int = 3,
    nfci: float | None = None,
) -> FCIInputs:
    """Inputs whose z-scores are all round numbers.

    Defaults give z = (2.5, 1.0, 1.0, 1.0, 1.0), so the composite is
    0.25*2.5 + 0.25*1.0 + 0.20*1.0 - 0.20*1.0 + 0.10*1.0 = **0.975**.
    """
    return FCIInputs(
        policy_rate=_c(*policy),
        credit_spread_hy=_c(*credit),
        term_premium=_c(*term),
        equity_index=_c(*equity),
        usd_index=_c(*usd),
        standardization_window_years=window,
        nfci_value=nfci,
    )


# ---------------------------------------------------------------------------
# The composite arithmetic
# ---------------------------------------------------------------------------


def test_the_composite_matches_a_hand_computation() -> None:
    """0.25*2.5 + 0.25*1.0 + 0.20*1.0 - 0.20*1.0 + 0.10*1.0 = 0.975."""
    result = compute_fci(_inputs())
    assert as_float(result, key="fci") == pytest.approx(0.975)
    assert as_bool(result, key="tighter_than_average") is True


def test_the_composite_is_recomputable_from_its_published_contributions() -> None:
    """The cross-field identity (D-009): recompute the value from its components."""
    result = compute_fci(_inputs())
    value = result.value
    assert isinstance(value, dict)
    contributions = value["contributions"]
    assert isinstance(contributions, dict)
    assert as_float(result, key="fci") == pytest.approx(sum(contributions.values()), abs=1e-6)
    z_scores = value["z_scores"]
    weights = value["weights"]
    assert isinstance(z_scores, dict) and isinstance(weights, dict)
    # The presence half, and it is load-bearing: the loop below iterates this
    # dict, so an EMPTY dict made the whole test vacuous — which is exactly how
    # a mutation emptying it survived the first sweep (D-035's absence lesson).
    assert set(z_scores) == {
        "policy_rate",
        "credit_spread_hy",
        "term_premium",
        "equity_index",
        "usd_index",
    }, "every component's z-score must be published"
    # And each contribution must be weight x z, with equity negated.
    for name, z in z_scores.items():
        expected = -weights[name] * z if name == "equity_index" else weights[name] * z
        assert contributions[name] == pytest.approx(expected, abs=1e-6)


def test_a_negative_composite_reads_as_looser() -> None:
    result = compute_fci(_inputs(policy=(-5.0, 2.5, 1.0)))
    assert as_float(result, key="fci") < 0.0
    assert as_bool(result, key="tighter_than_average") is False
    assert "looser" in result.interpretation


def test_exactly_zero_is_not_tighter() -> None:
    """The comparison is strict: a composite of exactly zero is not 'tighter'.

    EVERY component sits exactly at its own mean, so all five z-scores are zero
    and the composite is exactly zero. The first version of this test moved only
    two components to their means and left the other three above theirs, which
    made the composite 1.075 — it was asserting a boundary it never reached.
    """
    result = compute_fci(
        _inputs(
            policy=(2.5, 2.5, 1.0),
            credit=(4.0, 4.0, 1.0),
            term=(0.5, 0.5, 1.0),
            equity=(0.0, 0.0, 1.0),
            usd=(0.0, 0.0, 1.0),
        )
    )
    assert as_float(result, key="fci") == pytest.approx(0.0)
    assert as_bool(result, key="tighter_than_average") is False


# ---------------------------------------------------------------------------
# Finding #7 — the property that distinguishes z-scored from raw
# ---------------------------------------------------------------------------


def test_a_z_score_is_invariant_to_rescaling_a_component() -> None:
    """THE Finding #7 test.

    A z-score is unchanged when a component's value, mean and standard
    deviation are all multiplied by the same factor — the units cancel. A RAW
    deviation does not have that property: it scales with the input. So this
    assertion passes only for a standardized composite, and fails the moment the
    division by ``std`` is removed, which is exactly the defect Section 22.7
    exists to correct.
    """
    base = compute_fci(_inputs())
    # Every component rescaled by 100, i.e. expressed in different units.
    rescaled = compute_fci(
        _inputs(
            policy=(500.0, 250.0, 100.0),
            credit=(500.0, 400.0, 100.0),
            term=(100.0, 50.0, 50.0),
            equity=(1000.0, 0.0, 1000.0),
            usd=(500.0, 0.0, 500.0),
        )
    )
    assert as_float(rescaled, key="fci") == pytest.approx(as_float(base, key="fci")), (
        "rescaling every component's units must not change the composite; if it "
        "does, the components are being combined as raw deviations (Section 22.7)"
    )


def test_each_component_is_divided_by_its_own_std() -> None:
    """A component's contribution must fall as its std rises, other things equal."""
    tight = compute_fci(_inputs(credit=(5.0, 4.0, 1.0)))
    loose = compute_fci(_inputs(credit=(5.0, 4.0, 10.0)))
    tight_credit = as_float(tight, key="fci")
    loose_credit = as_float(loose, key="fci")
    assert loose_credit < tight_credit, (
        "a wider distribution makes the same deviation less remarkable, so the "
        "contribution must shrink"
    )
    assert tight_credit - loose_credit == pytest.approx(0.25 * (1.0 - 0.1))


# ---------------------------------------------------------------------------
# The orientation, which is the D-034 failure mode
# ---------------------------------------------------------------------------


def test_a_rising_equity_market_loosens_conditions() -> None:
    """Section 22.7 negates the equity term; an inversion flips the whole index.

    The direction is known before the call: a rising equity market is LOOSER
    financial conditions, so the composite must FALL. Every other component is
    pinned at its own mean, so the equity term is the only thing moving.
    """
    result = compute_fci(
        _inputs(
            policy=(2.5, 2.5, 1.0),
            credit=(4.0, 4.0, 1.0),
            term=(0.5, 0.5, 1.0),
            equity=(10.0, 0.0, 10.0),
            usd=(0.0, 0.0, 1.0),
        )
    )
    assert as_float(result, key="fci") == pytest.approx(-0.2), (
        "a rising equity market must push the index NEGATIVE (looser); a positive "
        "value here means the equity sign has been inverted"
    )
    value = result.value
    assert isinstance(value, dict)
    assert value["negated_components"] == ["equity_index"], (
        "the orientation must be published so a reader can audit it"
    )


def test_the_other_four_components_tighten_when_above_their_means() -> None:
    """The complement of the equity case: these four are ADDED, not subtracted."""
    at_means = {
        "policy_rate": _c(2.5, 2.5, 1.0),
        "credit_spread_hy": _c(4.0, 4.0, 1.0),
        "term_premium": _c(0.5, 0.5, 1.0),
        "equity_index": _c(0.0, 0.0, 1.0),
        "usd_index": _c(0.0, 0.0, 1.0),
    }
    raised = {
        "policy_rate": _c(5.0, 2.5, 1.0),
        "credit_spread_hy": _c(5.0, 4.0, 1.0),
        "term_premium": _c(1.5, 0.5, 1.0),
        "usd_index": _c(5.0, 0.0, 5.0),
    }
    for name, component in raised.items():
        components = dict(at_means)
        components[name] = component
        result = compute_fci(
            FCIInputs(
                policy_rate=components["policy_rate"],
                credit_spread_hy=components["credit_spread_hy"],
                term_premium=components["term_premium"],
                equity_index=components["equity_index"],
                usd_index=components["usd_index"],
                standardization_window_years=3,
            )
        )
        assert as_float(result, key="fci") > 0.0, (
            f"{name} above its mean must TIGHTEN conditions (push the index up)"
        )


# ---------------------------------------------------------------------------
# The config surface
# ---------------------------------------------------------------------------


def test_the_weights_come_from_config() -> None:
    """Patched to a set the shipped config does not hold, all else pinned at the mean."""
    patched = _settings().model_copy(
        update={
            "weights": {
                "calibration_status": "fitted_assumption",
                "components": {
                    "policy_rate": 1.0,
                    "credit_spread_hy": 0.0,
                    "term_premium": 0.0,
                    "equity_index": 0.0,
                    "usd_index": 0.0,
                },
            }
        }
    )
    with patch("macro_engine.models.financial_conditions._fci_settings", return_value=patched):
        result = compute_fci(_inputs())
    # With all weight on policy_rate (z = 2.5) the composite is exactly 2.5.
    assert as_float(result, key="fci") == pytest.approx(2.5)
    assert _settings().component_weights["policy_rate"] != 1.0


def test_a_weight_set_that_does_not_sum_to_one_is_refused_at_load() -> None:
    """A non-summing set silently rescales the composite, so it is refused.

    Caught at construction rather than at use: there is no correct fallback,
    because the output would still look exactly like an FCI.
    """
    with pytest.raises(Exception, match="sums to"):
        FCISettings(
            weights={
                "components": {
                    "policy_rate": 0.5,
                    "credit_spread_hy": 0.25,
                    "term_premium": 0.2,
                    "equity_index": 0.2,
                    "usd_index": 0.1,
                }
            },
            standardization_window_years_value=_leaf(3),
            nfci_divergence_threshold_value=_leaf(1.0),
        )


def test_a_component_set_mismatch_is_refused() -> None:
    """Config and model must carry the same components.

    A component on one side only is silently dropped from, or added to, the
    composite while still carrying weight — invisible in the output.
    """
    patched = _settings().model_copy(
        update={
            "weights": {
                "calibration_status": "fitted_assumption",
                "components": {
                    "policy_rate": 0.4,
                    "credit_spread_hy": 0.3,
                    "term_premium": 0.3,
                },
            }
        }
    )
    with (
        patch("macro_engine.models.financial_conditions._fci_settings", return_value=patched),
        pytest.raises(Exception, match="must be the same set"),
    ):
        compute_fci(_inputs())


def test_the_standardization_window_is_published_from_config() -> None:
    """The window makes the z-scores interpretable, so it must reach the output."""
    result = compute_fci(_inputs(window=3))
    assert as_int(result, key="standardization_window_years") == 3
    assert _settings().standardization_window_years == 3, (
        "the fixture must match the shipped window or the mismatch warning is what is tested"
    )


def test_a_window_mismatch_with_config_is_warned_about() -> None:
    """The model cannot verify which window was used, so it flags a disagreement."""
    result = compute_fci(_inputs(window=10))
    assert as_int(result, key="standardization_window_years") == 10
    matches = [w for w in result.warnings if "declared standardization window" in w]
    assert len(matches) == 1, "a window that disagrees with config must be disclosed"


# ---------------------------------------------------------------------------
# The mandatory NFCI cross-check
# ---------------------------------------------------------------------------


def test_an_absent_cross_check_is_disclosed_as_loudly_as_a_divergence() -> None:
    """Silence must not read as corroboration (Section 21.1 calls it mandatory)."""
    result = compute_fci(_inputs(nfci=None))
    assert as_bool(result, key="nfci_cross_checked") is False
    assert result.value is not None
    assert isinstance(result.value, dict)
    assert result.value["nfci_divergence"] is None
    matches = [w for w in result.warnings if "NOT PERFORMED" in w]
    assert len(matches) == 1, (
        f"the absent cross-check must be disclosed exactly once; found {len(matches)}"
    )
    assert "uncorroborated" in matches[0]


def test_a_cross_check_within_the_bar_does_not_warn() -> None:
    """The absence half: a small divergence must not raise the alarm."""
    result = compute_fci(_inputs(nfci=0.975))
    assert as_bool(result, key="nfci_cross_checked") is True
    assert as_float(result, key="nfci_divergence") == pytest.approx(0.0)
    assert not any("diverges from NFCI" in w for w in result.warnings), (
        "an exact match must not warn"
    )


def test_a_divergence_beyond_the_bar_warns() -> None:
    """Beyond the configured bar the two disagree, and that is reported."""
    result = compute_fci(_inputs(nfci=-1.5))
    assert as_float(result, key="nfci_divergence") == pytest.approx(2.475)
    matches = [w for w in result.warnings if "diverges from NFCI" in w]
    assert len(matches) == 1
    assert "2.475" in matches[0] or "+2.475" in matches[0], (
        "the warning must state the divergence it is complaining about"
    )


def test_the_divergence_threshold_comes_from_config() -> None:
    """Patched beyond any plausible gap, so nothing can warn."""
    patched = _settings().model_copy(update={"nfci_divergence_threshold_value": _leaf(99.0)})
    with patch("macro_engine.models.financial_conditions._fci_settings", return_value=patched):
        result = compute_fci(_inputs(nfci=-1.5))
    assert not any("diverges from NFCI" in w for w in result.warnings), (
        "a 2.475 gap is inside a 99.0 bar and must not warn"
    )


def test_the_illustrative_weights_caveat_is_stated() -> None:
    """The weights are uncalibrated, and the output must say so.

    A mutation removing this warning survived the first sweep because no test
    asserted it: the window, mismatch and cross-check warnings were all covered
    and this one was not.
    """
    result = compute_fci(_inputs())
    matches = [w for w in result.warnings if "illustrative defaults" in w]
    assert len(matches) == 1, (
        f"the illustrative-weights caveat must appear exactly once; found {len(matches)}"
    )
    assert "not calibrated" in matches[0]


def test_the_window_caveat_is_stated() -> None:
    """The window is bounded by data availability, and that must be visible.

    A reader who assumes the standardisation window was chosen would misread a
    three-year z-score as a ten-year one.
    """
    result = compute_fci(_inputs())
    matches = [w for w in result.warnings if "bounded by data availability" in w]
    assert len(matches) == 1, f"the window caveat must appear exactly once; found {len(matches)}"
    assert "3-year" in matches[0], "the caveat must state the window it is about"


def test_the_component_model_forbids_extra_fields() -> None:
    """``extra="forbid"`` on the COMPONENT, not only on the outer input model.

    The first version of this test passed an unknown field to ``FCIInputs``, so
    removing the forbid from ``FCIComponent`` changed nothing it asserted. Each
    model carries its own forbid and each needs its own test.
    """
    with pytest.raises(Exception, match="median"):
        FCIComponent(  # type: ignore[call-arg]
            value=5.0,
            mean=2.5,
            std=1.0,
            median=2.5,
        )


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------


def test_confidence_is_computed_not_asserted() -> None:
    """Section 22.8: confidence comes from stated factors."""
    result = compute_fci(_inputs())
    expected = compute_confidence(
        ConfidenceInputs(
            is_heuristic_not_calibrated=not _weights_calibrated_today(),
            source_independence_count=0,
        )
    )
    assert result.confidence == pytest.approx(expected)


def test_the_heuristic_penalty_applies_while_the_weights_are_placeholders() -> None:
    result = compute_fci(_inputs())
    base = get_settings().confidence.values["base"]
    assert _weights_calibrated_today() is False, (
        "this test assumes the weights are still illustrative; if a phase "
        "calibrates them, replace this test rather than deleting it"
    )
    assert result.confidence < base


def test_confidence_rises_when_the_weights_are_calibrated() -> None:
    with patch("macro_engine.models.financial_conditions._weights_calibrated", return_value=True):
        calibrated = compute_fci(_inputs())
    illustrative = compute_fci(_inputs())
    assert calibrated.confidence > illustrative.confidence, (
        "calibrating the weights must raise confidence; a hardcoded factor would "
        "leave the two equal"
    )


def _weights_calibrated_today() -> bool:
    from macro_engine.models.financial_conditions import _weights_calibrated

    return _weights_calibrated()


# ---------------------------------------------------------------------------
# The input contract
# ---------------------------------------------------------------------------


def test_a_zero_or_negative_std_is_refused() -> None:
    """The std is the z-score divisor, so it must be strictly positive.

    A zero would be a ZeroDivisionError at best; a tiny value would produce a
    z-score of thousands that reads as a once-in-history event.
    """
    for bad in (0.0, -1.0):
        with pytest.raises(Exception, match="std"):
            _c(5.0, 2.5, bad)


def test_a_non_positive_window_is_refused() -> None:
    with pytest.raises(Exception, match="standardization_window_years"):
        _inputs(window=0)


def test_the_input_contract_forbids_extra_fields() -> None:
    """A complete payload plus one unknown field — no ambiguity about the cause."""
    with pytest.raises(Exception, match="policy"):
        FCIInputs(  # type: ignore[call-arg]
            policy_rate=_c(5.0, 2.5, 1.0),
            credit_spread_hy=_c(5.0, 4.0, 1.0),
            term_premium=_c(1.0, 0.5, 0.5),
            equity_index=_c(10.0, 0.0, 10.0),
            usd_index=_c(5.0, 0.0, 5.0),
            standardization_window_years=3,
            policy=-1.0,
        )


def test_every_input_used_is_declared() -> None:
    result = compute_fci(_inputs())
    assert set(result.inputs_used) == {
        "policy_rate",
        "credit_spread_hy",
        "term_premium",
        "equity_index",
        "usd_index",
    }


def test_the_removed_averages_block_is_gone() -> None:
    """D-038: the frozen denominators were removed, not corrected.

    The block held trailing means for three of five components and no standard
    deviations, and `credit_spread_hy_avg` was 4.0 against a measured 3.12 — an
    error of more than two standard deviations. Freezing a denominator is what
    let it drift, so the surface is gone and the statistics are supplied.
    """
    assert not hasattr(_settings(), "averages"), (
        "fci.averages must not exist; the z-score denominators are supplied by "
        "the caller over a documented window (D-038)"
    )
    assert not hasattr(_settings(), "average_for"), (
        "average_for raised KeyError for two of the five components and went with the block it read"
    )


def test_the_result_names_itself_and_cites_the_finding() -> None:
    """A reader must be able to see which correction this output implements."""
    result = compute_fci(_inputs())
    assert result.model_name == "compute_fci"
    assert "Finding #7" in result.context or "22.7" in result.context, (
        "the context must cite the correction, so the output cannot be read as a "
        "raw-deviation composite"
    )
