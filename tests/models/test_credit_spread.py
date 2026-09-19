"""Tests for Module 8.3 — ``credit_spread_attribution``.

Five findings shape what is worth asserting (D-037):

1. **The specification's `BOTH` branch was unreachable.** ``fundamental``
   requires the trend to be ``"rising"``; ``technical`` requires it not to be.
   The two are mutually exclusive, so the ``BOTH`` / ``elevated_concern``
   branch could never execute. The regression test enumerates the whole input
   space and asserts all five attributions are reachable.
2. **The specification attributes widening without checking for it.** Neither
   spread change appears in its logic, so a tightening week would still be
   attributed. ``NO_WIDENING`` covers that case.
3. **The two spread inputs are a diagnostic, not a predicate.** They must be
   published — the output would otherwise claim inputs it never used — and they
   must NOT change the verdict. Both halves are asserted.
4. **Two adjacent inputs need opposite unit conversions.** The spreads are in
   percent and reach basis points by multiplying by 100; VIX is a level and the
   input is a percent change. A test pins that the model does not convert.
5. **One input is MANUAL.** ``default_rate_trend`` decides half the verdict and
   is hand-entered, so the disclosure must be present and tested.

Every config-derived value is patched to a leaf the literal cannot produce, and
the synthetic leaves are all DISTINCT so an accessor swap cannot hide (D-035).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from macro_engine.config import (
    CalibratedValue,
    CreditSpreadBaseRates,
    CreditSpreadSettings,
    get_settings,
)
from macro_engine.models.contracts import ConfidenceInputs, compute_confidence
from macro_engine.models.credit_spread import (
    CreditSpreadInputs,
    credit_spread_attribution,
)
from tests.helpers import as_bool, as_float, as_int, as_str


def _leaf(value: float | int) -> CalibratedValue:
    """A synthetic config leaf whose value this test chose, distinct from every other."""
    return CalibratedValue(
        value=value,
        calibration_status="fitted_assumption",
        note="synthetic — chosen by this test to be distinct from every other leaf",
    )


def _settings() -> CreditSpreadSettings:
    return get_settings().credit_spread


def _inputs(
    *,
    hy_level: float = 300.0,
    hy_change: float = 30.0,
    ig_change: float = 10.0,
    vol: float = 5.0,
    trend: str = "stable",
) -> CreditSpreadInputs:
    """Inputs whose every branch is known by construction.

    Defaults are a widening week with no volatility spike and a stable default
    trend: HY +30bp against IG +10bp, so widening is observed and the two are
    20bp apart (differentiated), and the attribution is UNCLEAR.
    """
    return CreditSpreadInputs(
        hy_spread_bp=hy_level,
        hy_spread_change_bp=hy_change,
        ig_spread_change_bp=ig_change,
        equity_vol_change_pct=vol,
        default_rate_trend=trend,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# The branches
# ---------------------------------------------------------------------------


def test_fundamental_is_a_rising_default_trend_without_a_volatility_spike() -> None:
    result = credit_spread_attribution(_inputs(trend="rising", vol=5.0))
    assert as_str(result, key="attribution") == "FUNDAMENTAL"
    assert as_str(result, key="expected_durability") == "sticky_slow_to_reverse"
    assert as_bool(result, key="fundamental") is True
    assert as_bool(result, key="technical") is False


def test_technical_is_a_volatility_spike_without_a_rising_trend() -> None:
    result = credit_spread_attribution(_inputs(trend="stable", vol=30.0))
    assert as_str(result, key="attribution") == "TECHNICAL_RISK_AVERSION"
    assert as_str(result, key="expected_durability") == "can_snap_back_sharply"


def test_neither_predicate_is_unclear() -> None:
    result = credit_spread_attribution(_inputs(trend="stable", vol=5.0))
    assert as_str(result, key="attribution") == "UNCLEAR"
    assert as_str(result, key="expected_durability") == "investigate"


def test_the_both_branch_is_reachable() -> None:
    """D-037: the specification's ``BOTH`` branch was dead code. It is not now.

    The specification ANDs ``technical`` with ``default_rate_trend != "rising"``
    while ``fundamental`` requires it to BE ``"rising"``, so ``fundamental and
    technical`` was unsatisfiable and ``BOTH`` / ``elevated_concern`` could
    never be produced. This test enumerates the implementation over its whole
    declared input space — the same way the defect was found — so restoring the
    exclusion drops the reachable set to three and fails here.
    """
    reachable: set[str] = set()
    for trend in ("rising", "stable", "falling"):
        for vol in (0.0, 19.9, 20.0, 20.1, 100.0):
            for hy_change in (10.0, -10.0):
                result = credit_spread_attribution(
                    _inputs(trend=trend, vol=vol, hy_change=hy_change)
                )
                reachable.add(as_str(result, key="attribution"))

    assert "BOTH" in reachable, (
        "the BOTH attribution must be reachable. If it is not, the "
        "specification's 'and default_rate_trend != \"rising\"' exclusion has "
        f"been restored. Reachable: {sorted(reachable)}"
    )
    assert reachable == {
        "FUNDAMENTAL",
        "TECHNICAL_RISK_AVERSION",
        "BOTH",
        "UNCLEAR",
        "NO_WIDENING",
    }, f"every attribution must be reachable; got {sorted(reachable)}"


def test_both_is_elevated_concern() -> None:
    """The state the specification could not produce, and what it means."""
    result = credit_spread_attribution(_inputs(trend="rising", vol=30.0))
    assert as_str(result, key="attribution") == "BOTH"
    assert as_str(result, key="expected_durability") == "elevated_concern"
    assert as_bool(result, key="fundamental") is True
    assert as_bool(result, key="technical") is True


# ---------------------------------------------------------------------------
# The widening check the specification omits
# ---------------------------------------------------------------------------


def test_a_tightening_week_is_not_attributed_to_a_cause() -> None:
    """The model attributes WIDENING, so it must check that widening happened.

    The specification never reads either spread change, so as written it would
    return FUNDAMENTAL for a week in which spreads tightened — attributing a
    move that did not occur. Refusing is the Section 21.0-rule-4 behaviour:
    report that there is nothing to attribute rather than substitute a cause.
    """
    result = credit_spread_attribution(_inputs(hy_change=-30.0, ig_change=-10.0, trend="rising"))
    assert as_str(result, key="attribution") == "NO_WIDENING"
    assert as_str(result, key="expected_durability") == "not_applicable"
    assert as_bool(result, key="widening_observed") is False
    matches = [w for w in result.warnings if "did not widen" in w]
    assert len(matches) == 1, "the no-widening case must be disclosed in prose"


def test_an_unchanged_spread_is_not_widening() -> None:
    """The comparison is strict: exactly zero is not widening."""
    result = credit_spread_attribution(_inputs(hy_change=0.0))
    assert as_bool(result, key="widening_observed") is False
    assert as_str(result, key="attribution") == "NO_WIDENING"


# ---------------------------------------------------------------------------
# The thresholds come from config, and the boundaries are strict
# ---------------------------------------------------------------------------


def test_the_volatility_threshold_comes_from_config_and_is_strict() -> None:
    """Exactly at the threshold is not a spike.

    Patched to 5.0, which the shipped 20.0 cannot produce, so a literal in the
    model fails here. The boundary is built so the strictness is observable:
    at exactly 5.0 the comparison ``5.0 > 5.0`` is False.
    """
    patched = _settings().model_copy(update={"equity_vol_spike_threshold_pct_value": _leaf(5.0)})
    with patch("macro_engine.models.credit_spread._credit_spread_settings", return_value=patched):
        at_boundary = credit_spread_attribution(_inputs(vol=5.0))
        above = credit_spread_attribution(_inputs(vol=5.1))
    assert as_bool(at_boundary, key="technical") is False, (
        "exactly at the threshold must not count as a spike — the comparison is strict"
    )
    assert as_bool(above, key="technical") is True


def test_the_volatility_threshold_is_not_the_shipped_literal() -> None:
    """A second direction: the shipped 20.0 must still apply when unpatched."""
    assert as_bool(credit_spread_attribution(_inputs(vol=19.9)), key="technical") is False
    assert as_bool(credit_spread_attribution(_inputs(vol=20.1)), key="technical") is True


def test_the_change_window_is_published_from_config() -> None:
    """The window is unspecified in the specification, so it must be visible.

    Every numeric input is a change over some window, and Section 20.8 names
    none. A reader cannot interpret a 20% volatility move without knowing the
    period it happened over, so the window travels with the output.
    """
    patched = _settings().model_copy(update={"change_window_days_value": _leaf(21)})
    with patch("macro_engine.models.credit_spread._credit_spread_settings", return_value=patched):
        result = credit_spread_attribution(_inputs())
    assert as_int(result, key="change_window_days") == 21
    assert _settings().change_window_days != 21, (
        "the fixture must differ from the shipped window or the patch proves nothing"
    )


# ---------------------------------------------------------------------------
# The diagnostic must be published AND must not decide anything
# ---------------------------------------------------------------------------


def test_the_differentiation_is_published_as_a_diagnostic() -> None:
    """The two spread inputs must reach the output.

    Section 20.8 lists both in ``inputs_used`` but never reads them, so as
    written the output claims inputs it did not use. Publishing the
    differentiation is what makes that claim true.
    """
    result = credit_spread_attribution(_inputs(hy_change=30.0, ig_change=10.0))
    assert as_float(result, key="hy_minus_ig_change_bp") == pytest.approx(20.0)
    assert as_bool(result, key="widenings_are_parallel") is False


def test_the_differentiation_threshold_cannot_change_the_attribution() -> None:
    """The diagnostic threshold must not decide the verdict.

    Patched to a value that would flip ``widenings_are_parallel`` in the other
    direction, and the attribution is asserted UNCHANGED. This is the test that
    enforces the 2026-09-17 decision: the differentiation is reported, never
    decisive. If a later change wires it into the verdict, this fails.
    """
    shipped = credit_spread_attribution(_inputs(hy_change=30.0, ig_change=10.0))
    patched = _settings().model_copy(update={"differentiation_threshold_bp_value": _leaf(1.0)})
    with patch("macro_engine.models.credit_spread._credit_spread_settings", return_value=patched):
        tightened = credit_spread_attribution(_inputs(hy_change=30.0, ig_change=10.0))

    assert as_bool(shipped, key="widenings_are_parallel") is False
    assert as_bool(tightened, key="widenings_are_parallel") is False
    assert as_str(tightened, key="attribution") == as_str(shipped, key="attribution"), (
        "changing the diagnostic threshold must not move the attribution"
    )

    # And the flag itself must still be able to change, or the test above is vacuous.
    loose = _settings().model_copy(update={"differentiation_threshold_bp_value": _leaf(50.0)})
    with patch("macro_engine.models.credit_spread._credit_spread_settings", return_value=loose):
        widened_band = credit_spread_attribution(_inputs(hy_change=30.0, ig_change=10.0))
    assert as_bool(widened_band, key="widenings_are_parallel") is True, (
        "a 50bp band must contain a 20bp difference — otherwise the flag is stuck"
    )
    assert as_str(widened_band, key="attribution") == as_str(shipped, key="attribution")


def test_the_parallel_band_boundary_is_inclusive() -> None:
    """A difference EXACTLY at the threshold counts as parallel.

    The band is ``abs(diff) <= threshold``, and this is the only test that lands
    on the boundary: the other diagnostic tests patch the threshold to 1.0 and
    50.0 against a 20bp difference, so a mutation making the comparison strict
    changed nothing they asserted. That mutation survived the first sweep.

    Built by ADDITION rather than subtraction — the threshold is patched to
    exactly 20.0 and the difference is made exactly 20.0 from two round inputs
    (30.0 - 10.0), so neither side carries a floating-point fuzz that could
    move the point off the boundary it claims to test.
    """
    patched = _settings().model_copy(update={"differentiation_threshold_bp_value": _leaf(20.0)})
    with patch("macro_engine.models.credit_spread._credit_spread_settings", return_value=patched):
        at_boundary = credit_spread_attribution(_inputs(hy_change=30.0, ig_change=10.0))
        just_outside = credit_spread_attribution(_inputs(hy_change=30.1, ig_change=10.0))

    assert as_float(at_boundary, key="hy_minus_ig_change_bp") == pytest.approx(20.0)
    assert as_bool(at_boundary, key="widenings_are_parallel") is True, (
        "a difference exactly equal to the threshold is INSIDE the band — the "
        "comparison is inclusive"
    )
    assert as_bool(just_outside, key="widenings_are_parallel") is False


def test_the_parallel_widening_rate_is_published_from_config() -> None:
    """The parallel rate must be observable, like the other two base rates.

    A config leaf that no code path reads is one a mutation can change with no
    consequence, which is what the first sweep found: swapping
    ``parallel_widening_rate`` to read the widening rate changed nothing,
    because the model never published it. A reader told "these moved together"
    needs to know how often that happens.
    """
    patched = _settings().model_copy(
        update={
            "base_rates": CreditSpreadBaseRates(
                observations_measured_value=_leaf(999),
                equity_vol_spike_rate_value=_leaf(0.1),
                widening_rate_value=_leaf(0.2),
                parallel_widening_rate_value=_leaf(0.7777),
            )
        }
    )
    with patch("macro_engine.models.credit_spread._credit_spread_settings", return_value=patched):
        result = credit_spread_attribution(_inputs())
    assert as_float(result, key="parallel_widening_rate") == pytest.approx(0.7777), (
        "the parallel-widening base rate must be published from config"
    )
    assert _settings().base_rates.parallel_widening_rate != 0.7777, (
        "the fixture must differ from the shipped record or the patch proves nothing"
    )


def test_the_diagnostic_is_declared_not_to_be_a_predicate() -> None:
    """A consumer must be told the differentiation is not part of the verdict."""
    result = credit_spread_attribution(_inputs())
    matches = [w for w in result.warnings if "DIAGNOSTIC, not part of the attribution" in w]
    assert len(matches) == 1, (
        f"the diagnostic disclaimer must appear exactly once; found {len(matches)}"
    )


# ---------------------------------------------------------------------------
# The cross-field identity (D-009)
# ---------------------------------------------------------------------------


def test_the_attribution_is_recomputable_from_its_published_components() -> None:
    """The attribution must equal what the published predicates imply.

    Recomputing the reported value from its reported components is what catches
    a reordered or mis-ordered branch.
    """
    cases = [
        (30.0, 10.0, 5.0, "rising"),
        (30.0, 10.0, 30.0, "stable"),
        (30.0, 10.0, 30.0, "rising"),
        (30.0, 10.0, 5.0, "stable"),
        (-30.0, -10.0, 30.0, "rising"),
        (30.0, 10.0, 20.0, "falling"),
    ]
    for hy_change, ig_change, vol, trend in cases:
        result = credit_spread_attribution(
            _inputs(hy_change=hy_change, ig_change=ig_change, vol=vol, trend=trend)
        )
        fundamental = as_bool(result, key="fundamental")
        technical = as_bool(result, key="technical")
        widening = as_bool(result, key="widening_observed")
        expected = (
            "NO_WIDENING"
            if not widening
            else "BOTH"
            if fundamental and technical
            else "FUNDAMENTAL"
            if fundamental
            else "TECHNICAL_RISK_AVERSION"
            if technical
            else "UNCLEAR"
        )
        assert as_str(result, key="attribution") == expected, (
            f"trend={trend} vol={vol} hy={hy_change}: the published attribution "
            f"disagrees with its own published predicates "
            f"(fundamental={fundamental}, technical={technical}, widening={widening})"
        )


def test_every_raw_input_is_republished() -> None:
    """Including the manual one, which cannot be re-derived from anything."""
    result = credit_spread_attribution(
        _inputs(hy_level=287.5, hy_change=31.25, ig_change=9.5, vol=17.75, trend="falling")
    )
    assert as_float(result, key="hy_spread_bp") == pytest.approx(287.5)
    assert as_float(result, key="hy_spread_change_bp") == pytest.approx(31.25)
    assert as_float(result, key="ig_spread_change_bp") == pytest.approx(9.5)
    assert as_float(result, key="equity_vol_change_pct") == pytest.approx(17.75)
    assert as_str(result, key="default_rate_trend") == "falling"


def test_the_model_does_not_convert_units() -> None:
    """The inputs arrive in bp and percent-change, and are used verbatim.

    The model must NOT apply a conversion: the two adjacent inputs need
    OPPOSITE ones (spreads percent->bp is x100; VIX is a level whose change is
    already a percent), and a model that guessed would be wrong on one of them.
    Conversion is the live check's job, and a 100x error there is a plausible
    attribution of the wrong kind (D-035). This pins that the model is a pure
    consumer of the units its field names declare.
    """
    result = credit_spread_attribution(_inputs(hy_change=250.0, ig_change=100.0, vol=15.0))
    assert as_float(result, key="hy_spread_change_bp") == pytest.approx(250.0), (
        "a 250bp change must stay 250, not become 2.5 or 25000"
    )
    assert as_float(result, key="equity_vol_change_pct") == pytest.approx(15.0)


# ---------------------------------------------------------------------------
# The disclosures
# ---------------------------------------------------------------------------


def test_the_caller_supplied_trend_is_published_and_warned() -> None:
    """Half the verdict rests on a hand-entered judgement, and that must be said.

    Two halves: a machine consumer needs the flag in ``value``, a human reader
    needs the sentence, and the sentence must name the field.
    """
    result = credit_spread_attribution(_inputs())
    assert as_bool(result, key="default_rate_trend_is_caller_supplied") is True
    # D-043 established a free derivation route (FRED `DRALACBS`), so the
    # manual route is no longer the ONLY one. This key is what tells a machine
    # consumer that; without an assertion on it the key could be deleted or
    # flipped with the whole suite green (the D-045 rule — a disclosure no test
    # can break is one that can be removed without consequence).
    assert as_bool(result, key="default_rate_trend_derived_route_available") is True, (
        "the derived route must be advertised, or a caller cannot know that the "
        "manual entry is optional"
    )
    matches = [w for w in result.warnings if "CALLER INPUT" in w]
    assert len(matches) == 1, (
        f"the manual-entry disclosure must appear exactly once; found {len(matches)}"
    )
    assert "default_rate_trend" in matches[0], (
        "the warning must name the field that was hand-entered"
    )


def test_both_flags_travel_with_their_measured_base_rate() -> None:
    """D-029: a flag from a threshold comparison must carry its own frequency.

    The rates are patched to DISTINCT values so neither a swap nor a literal
    can satisfy the assertion.
    """
    base = _settings().base_rates
    patched = _settings().model_copy(
        update={
            "base_rates": CreditSpreadBaseRates(
                observations_measured_value=_leaf(4321),
                equity_vol_spike_rate_value=_leaf(0.1111),
                widening_rate_value=_leaf(0.2222),
                parallel_widening_rate_value=_leaf(0.3333),
            )
        }
    )
    with patch("macro_engine.models.credit_spread._credit_spread_settings", return_value=patched):
        result = credit_spread_attribution(_inputs())

    assert as_int(result, key="observations_measured") == 4321
    assert as_float(result, key="equity_vol_spike_rate") == pytest.approx(0.1111)
    assert as_float(result, key="widening_rate") == pytest.approx(0.2222)
    assert base.observations_measured != 4321, (
        "the fixture must differ from the shipped record or the patch proves nothing"
    )
    assert any("11.1%" in w for w in result.warnings), "the spike rate must reach the prose"
    assert any("22.2%" in w for w in result.warnings), "the widening rate must reach the prose"


def test_the_parallel_widening_case_is_disclosed() -> None:
    """Parallel widening is informative and must be named when it happens."""
    result = credit_spread_attribution(_inputs(hy_change=30.0, ig_change=28.0))
    assert as_bool(result, key="widenings_are_parallel") is True
    assert any("broad risk-aversion move" in w for w in result.warnings)


def test_the_parallel_disclosure_is_absent_when_the_move_is_differentiated() -> None:
    """The absence half — the disclosure must not fire unconditionally."""
    result = credit_spread_attribution(_inputs(hy_change=30.0, ig_change=10.0))
    assert as_bool(result, key="widenings_are_parallel") is False
    assert not any("broad risk-aversion move" in w for w in result.warnings)


def test_the_context_states_the_opposite_implications() -> None:
    """The reason the module exists must survive in the output."""
    result = credit_spread_attribution(_inputs())
    assert "OPPOSITE" in result.context
    assert "LTCM" in result.context


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------


def test_confidence_is_computed_not_asserted() -> None:
    """Section 22.8: confidence comes from stated factors."""
    result = credit_spread_attribution(_inputs())
    expected = compute_confidence(
        ConfidenceInputs(
            is_heuristic_not_calibrated=not _thresholds_calibrated_today(),
            source_independence_count=0,
        )
    )
    assert result.confidence == pytest.approx(expected)


def test_the_heuristic_penalty_applies_while_the_thresholds_are_placeholders() -> None:
    """An uncalibrated threshold must lower confidence automatically."""
    result = credit_spread_attribution(_inputs())
    base = get_settings().confidence.values["base"]
    assert _thresholds_calibrated_today() is False, (
        "this test assumes the thresholds are still illustrative; if a phase "
        "calibrates them, replace this test rather than deleting it"
    )
    assert result.confidence < base


def test_confidence_rises_when_the_thresholds_are_calibrated() -> None:
    """The penalty is wired to the calibration status, not hardcoded."""
    with patch("macro_engine.models.credit_spread._thresholds_calibrated", return_value=True):
        calibrated = credit_spread_attribution(_inputs())
    illustrative = credit_spread_attribution(_inputs())
    assert calibrated.confidence > illustrative.confidence, (
        "calibrating the thresholds must raise confidence; a hardcoded factor "
        "would leave the two equal"
    )


def _thresholds_calibrated_today() -> bool:
    """The shipped calibration status of Module 8.3's two decision thresholds."""
    from macro_engine.models.credit_spread import _thresholds_calibrated

    return _thresholds_calibrated()


# ---------------------------------------------------------------------------
# The input contract
# ---------------------------------------------------------------------------


def test_the_input_contract_forbids_extra_fields() -> None:
    """``extra="forbid"``, with a complete payload plus one unknown field.

    Supplying every valid field AND an extra has no ambiguity: the only thing
    that can make it raise is the forbid itself. (Matching an error message
    against a plausible misspelling is ambiguous, because the "field required"
    message for the correct spelling also matches — the D-036 M6a lesson.)
    """
    with pytest.raises(Exception, match="hy_spread_change"):
        CreditSpreadInputs(  # type: ignore[call-arg]
            hy_spread_bp=300.0,
            hy_spread_change_bp=30.0,
            ig_spread_change_bp=10.0,
            equity_vol_change_pct=5.0,
            default_rate_trend="stable",
            hy_spread_change=30.0,
        )


def test_an_unknown_default_rate_trend_is_refused() -> None:
    """The trend is a ``Literal``, so a typo fails rather than selecting ``else``.

    D-029's failure mode: a bare ``str`` accepts ``"Rising"`` (capitalised) or
    ``"riseing"``, both of which silently fall through to the ``else`` branch
    and report UNCLEAR — a wrong answer shaped exactly like a considered one.
    """
    for bad in ("Rising", "riseing", "up", ""):
        with pytest.raises(Exception, match="default_rate_trend"):
            CreditSpreadInputs(
                hy_spread_bp=300.0,
                hy_spread_change_bp=30.0,
                ig_spread_change_bp=10.0,
                equity_vol_change_pct=5.0,
                default_rate_trend=bad,  # type: ignore[arg-type]
            )


def test_a_non_positive_spread_level_is_refused() -> None:
    """A spread level is a positive quantity; a zero or negative one is a bug."""
    with pytest.raises(Exception, match="hy_spread_bp"):
        _inputs(hy_level=0.0)
    with pytest.raises(Exception, match="hy_spread_bp"):
        _inputs(hy_level=-1.0)


def test_every_input_used_is_declared() -> None:
    """All five, including the two the specification declares but never reads."""
    result = credit_spread_attribution(_inputs())
    assert set(result.inputs_used) == {
        "hy_spread_bp",
        "hy_spread_change_bp",
        "ig_spread_change_bp",
        "equity_vol_change_pct",
        "default_rate_trend",
    }
