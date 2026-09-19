"""Phase 2 model tests — Module 7.1 GDP/GDI divergence (AGENTS.md Section 20.7).

Every expected value below was computed independently before the test was run,
per Section 21.2 Step 4. The arithmetic is shown inline so a reader can check
the assertion rather than trusting it.

Why this function needs more tests than its four lines of arithmetic
--------------------------------------------------------------------
Section 20.7's version is three lines long and returns a hardcoded confidence.
It is wrong in four separate ways, and each one is a *silent* wrong answer
rather than an error:

1. ``confidence=0.4 if significant else 0.7`` is a model asserting its own
   confidence, which Section 22.8 forbids and which Finding #8 exists to
   eliminate. Now ``compute_confidence()``.
2. ``abs(diff) > 1.0`` is a literal. Now ``gdp_gdi.significance_threshold_pp``.
3. The spec's warning tells the reader the divergence indicates "one dataset is
   capturing something the other misses", inviting a directional reading. The
   measurement (D-031) shows the sign is a coin flip — GDP leads 47.8% of the
   time. A test asserts the model never characterises the direction.
4. ``average`` is presented as simply "the better read". True for growth rates,
   false for levels, where the wedge averages -0.459% and is persistently
   negative. A test asserts the key is named for its unit and that the level
   wedge travels with the output.

The base rate is also asserted to be *reported*, per D-029's disclosure rule.
"""

from __future__ import annotations

import math

import pytest

from macro_engine.models.contracts import ConfidenceInputs, compute_confidence
from macro_engine.models.gdp_nowcast import GdpGdiInputs, gdp_gdi_divergence
from tests.helpers import as_bool, as_float

# ---------------------------------------------------------------------------
# Step 4 — the arithmetic, against hand-computed values
# ---------------------------------------------------------------------------


def test_divergence_matches_hand_computed_value() -> None:
    """GDP 6.562, GDI 6.614 -> diff -0.052pp, average +6.588%.

    These are the real 2026-Q2 values from FRED ``GDP`` and ``GDI`` as observed
    on 2026-09-17, so this doubles as a regression pin on the live reading.

        diff    = 6.562 - 6.614 = -0.052
        average = (6.562 + 6.614) / 2 = 13.176 / 2 = 6.588
    """
    result = gdp_gdi_divergence(GdpGdiInputs(gdp_growth_pct=6.562, gdi_growth_pct=6.614))

    assert as_float(result, key="gdp_growth_pct") == 6.562
    assert as_float(result, key="gdi_growth_pct") == 6.614
    assert as_float(result, key="divergence_pp") == pytest.approx(-0.052)
    assert as_float(result, key="average_growth_pct") == pytest.approx(6.588)
    assert as_bool(result, key="significant") is False


def test_a_large_divergence_is_flagged() -> None:
    """GDP 3.0, GDI 5.0 -> diff -2.0pp, |diff| > 1.0 -> significant.

    diff    = 3.0 - 5.0 = -2.0
    average = (3.0 + 5.0) / 2 = 4.0
    """
    result = gdp_gdi_divergence(GdpGdiInputs(gdp_growth_pct=3.0, gdi_growth_pct=5.0))

    assert as_float(result, key="divergence_pp") == pytest.approx(-2.0)
    assert as_float(result, key="average_growth_pct") == pytest.approx(4.0)
    assert as_bool(result, key="significant") is True


def test_the_sign_convention_is_gdp_minus_gdi() -> None:
    """A positive divergence means GDP grew faster — asserted, not assumed.

    The sign convention is the one thing a reader will silently get wrong if
    the model flips it, and both orders here are individually plausible.
    """
    gdp_leads = gdp_gdi_divergence(GdpGdiInputs(gdp_growth_pct=4.0, gdi_growth_pct=2.0))
    gdi_leads = gdp_gdi_divergence(GdpGdiInputs(gdp_growth_pct=2.0, gdi_growth_pct=4.0))

    assert as_float(gdp_leads, key="divergence_pp") == pytest.approx(2.0)
    assert as_float(gdi_leads, key="divergence_pp") == pytest.approx(-2.0)


def test_identical_inputs_are_a_zero_divergence() -> None:
    """The theory says GDP and GDI are equal; the model must agree at equality."""
    result = gdp_gdi_divergence(GdpGdiInputs(gdp_growth_pct=2.5, gdi_growth_pct=2.5))

    assert as_float(result, key="divergence_pp") == pytest.approx(0.0)
    assert as_float(result, key="average_growth_pct") == pytest.approx(2.5)
    assert as_bool(result, key="significant") is False


# ---------------------------------------------------------------------------
# Correction 1 — confidence is computed, never asserted
# ---------------------------------------------------------------------------


def test_confidence_comes_from_compute_confidence_not_a_literal() -> None:
    """Section 22.8 / Finding #8: no model may assert its own confidence.

    The specification's version returns 0.4 or 0.7 depending on the flag. The
    corrected version returns whatever ``compute_confidence`` yields for the
    stated facts, which must be independent of the magnitude of the inputs.
    """
    expected = compute_confidence(
        ConfidenceInputs(
            is_heuristic_not_calibrated=True,
            depends_on_unobservable=True,
            source_independence_count=0,
        )
    )

    for gdp, gdi in ((6.562, 6.614), (3.0, 5.0), (0.0, 0.0), (-1.0, 4.0)):
        result = gdp_gdi_divergence(GdpGdiInputs(gdp_growth_pct=gdp, gdi_growth_pct=gdi))
        assert result.confidence == expected, (
            f"confidence varied with the inputs for gdp={gdp}, gdi={gdi}; "
            "a computed confidence depends on stated facts, not on magnitude"
        )


def test_confidence_reflects_both_stated_penalties() -> None:
    """The declared ``ConfidenceInputs`` facts must be the ones actually claimed.

    This test deliberately does NOT recompute the expectation from the same
    argument list the model uses — that would move in lockstep with the model
    and pass even if the model dropped a penalty. It instead asserts the
    *structure*: the returned value must sit strictly below what either penalty
    alone would give, which is only true when both are claimed.

    Measured, with the current config: both penalties -> 0.3, either alone ->
    0.5, neither -> 0.7. So the model's value must be < the single-penalty
    value. A mutation that drops ``depends_on_unobservable`` returns 0.5 and
    fails this assertion.
    """
    both = compute_confidence(
        ConfidenceInputs(
            is_heuristic_not_calibrated=True,
            depends_on_unobservable=True,
            source_independence_count=0,
        )
    )
    single = compute_confidence(
        ConfidenceInputs(
            is_heuristic_not_calibrated=True,
            depends_on_unobservable=False,
            source_independence_count=0,
        )
    )
    assert both < single, (
        "precondition: the two penalties must be separable on the current config, "
        "otherwise this test cannot distinguish them"
    )

    result = gdp_gdi_divergence(GdpGdiInputs(gdp_growth_pct=4.0, gdi_growth_pct=2.0))
    assert result.confidence == pytest.approx(both)
    assert result.confidence < single, (
        "confidence equals the single-penalty value, so at least one declared "
        "penalty is not actually being claimed"
    )


def test_confidence_is_not_the_specifications_hardcoded_values() -> None:
    """Guard against a regression that reinstates 0.4 / 0.7."""
    for gdp, gdi in ((6.562, 6.614), (3.0, 5.0)):
        result = gdp_gdi_divergence(GdpGdiInputs(gdp_growth_pct=gdp, gdi_growth_pct=gdi))
        assert result.confidence not in (0.4, 0.7)


# ---------------------------------------------------------------------------
# Correction 2 — the threshold lives in config
# ---------------------------------------------------------------------------


def test_threshold_is_read_from_config() -> None:
    """The flag boundary must move when the config moves.

    Section 20.7 hardcodes 1.0. Here the boundary is read, so the flagged set
    is defined by configuration rather than by a literal in the model.
    """
    from macro_engine.config import get_settings

    threshold = get_settings().gdp_gdi.significance_threshold
    assert threshold > 0

    # Just inside: not flagged. Just outside: flagged. Built by ADDITION from
    # zero rather than by subtracting from the threshold, because
    # `threshold - threshold` is not reliably zero in binary floating point and
    # a fixture that is off by 1e-16 straddles the boundary it is testing.
    inside = gdp_gdi_divergence(
        GdpGdiInputs(gdp_growth_pct=0.0, gdi_growth_pct=0.0 + threshold * 0.5)
    )
    outside = gdp_gdi_divergence(
        GdpGdiInputs(gdp_growth_pct=0.0, gdi_growth_pct=0.0 + threshold * 2.0)
    )

    assert as_bool(inside, key="significant") is False
    assert as_bool(outside, key="significant") is True


def test_the_boundary_is_strict_not_inclusive() -> None:
    """``>`` not ``>=``. Exactly at the threshold is not significant.

    The fixture is built by ADDITION from zero so the input is exactly the
    threshold rather than the floating-point residue of a subtraction.
    """
    from macro_engine.config import get_settings

    threshold = get_settings().gdp_gdi.significance_threshold
    result = gdp_gdi_divergence(GdpGdiInputs(gdp_growth_pct=0.0, gdi_growth_pct=0.0 + threshold))
    assert as_bool(result, key="significant") is False


def test_the_model_reads_the_threshold_from_config_and_not_a_literal() -> None:
    """A literal that happens to equal the config value must still be caught.

    The other threshold tests read the boundary *from config*, exactly as the
    model does — so replacing the config read with a hardcoded ``1.0`` would
    move both sides together and pass. This test breaks that symmetry by
    asserting a value the model could only produce if it consumed the config:
    the flag boundary must move when the config is patched.

    The config object is patched through ``get_settings``' cached instance
    rather than by editing the file, so the check is an in-process property
    assertion with no filesystem side effects.
    """
    from macro_engine.config import GdpGdiSettings, get_settings

    settings = get_settings()
    original = settings.gdp_gdi

    # A threshold deliberately far from the shipped 1.0, so a literal read
    # cannot coincide with it.
    patched_settings = original.model_copy(
        update={
            "significance_threshold_pp": original.significance_threshold_pp.model_copy(
                update={"value": 0.25}
            )
        }
    )
    assert isinstance(patched_settings, GdpGdiSettings)
    assert patched_settings.significance_threshold == pytest.approx(0.25)

    settings.gdp_gdi = patched_settings
    try:
        # 0.4pp: outside 0.25, inside the shipped 1.0. Only a config read flags it.
        result = gdp_gdi_divergence(GdpGdiInputs(gdp_growth_pct=3.0, gdi_growth_pct=2.6))
        assert as_bool(result, key="significant") is True, (
            "the model did not honour the patched threshold, so it is not reading "
            "the threshold from config"
        )
    finally:
        settings.gdp_gdi = original


def test_the_threshold_used_in_warnings_matches_the_config() -> None:
    """The number printed in the warning must be the configured threshold."""
    from macro_engine.config import get_settings

    threshold = get_settings().gdp_gdi.significance_threshold
    result = gdp_gdi_divergence(GdpGdiInputs(gdp_growth_pct=0.0, gdi_growth_pct=5.0))

    assert any(f"{threshold:.2f}pp" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Correction 3 — the sign must never be interpreted
# ---------------------------------------------------------------------------


def test_no_warning_characterises_the_direction_of_the_divergence() -> None:
    """D-031: the sign is a coin flip, so no warning may read it as a finding.

    The specification's warning says the divergence means "one dataset is
    capturing something the other misses", which invites the reader to decide
    which one. The measurement says GDP leads 47.8% of the time. This asserts
    the warning text does not attribute the discrepancy to a side.
    """
    result = gdp_gdi_divergence(GdpGdiInputs(gdp_growth_pct=9.0, gdi_growth_pct=1.0))
    joined = " ".join(result.warnings).lower()

    for forbidden in ("gdp is overstating", "gdi is understating", "gdp is right", "gdi is right"):
        assert forbidden not in joined

    # And the model must actively warn against a directional reading.
    assert any("sign" in w.lower() for w in result.warnings)
    assert any("coin flip" in w.lower() for w in result.warnings)


def test_the_sign_warning_quotes_the_measured_led_frequency() -> None:
    """The warning's rhetorical claim must rest on the actual number.

    A warning can say "coin flip" while printing a rate that is not a coin
    flip, which would be worse than saying nothing — the text would assert
    neutrality while the digits imply a direction. This pins both sides: the
    configured GDP-led rate must appear, and its complement must appear, and
    the two must sum to 100%.
    """
    from macro_engine.config import get_settings

    rate = get_settings().gdp_gdi.divergence_base_rate.gdp_above_gdi_rate
    gdi_led = 1 - rate

    result = gdp_gdi_divergence(GdpGdiInputs(gdp_growth_pct=9.0, gdi_growth_pct=1.0))
    joined = " ".join(result.warnings)

    assert f"{rate * 100:.1f}%" in joined, (
        f"the measured GDP-led rate {rate * 100:.1f}% must be quoted verbatim"
    )
    assert f"{gdi_led * 100:.1f}%" in joined, (
        f"the complementary GDI-led rate {gdi_led * 100:.1f}% must be quoted verbatim"
    )
    assert abs(rate - 0.5) < 0.1, (
        "precondition: the led-rate must actually be near a coin flip for the "
        "warning's claim to be the measured one"
    )


def test_a_positive_and_a_negative_divergence_of_equal_magnitude_agree_on_significance() -> None:
    """Symmetry: the flag depends on magnitude only, never on direction.

    If the flag were sensitive to sign, this would be the test that catches it.
    """
    positive = gdp_gdi_divergence(GdpGdiInputs(gdp_growth_pct=4.0, gdi_growth_pct=1.5))
    negative = gdp_gdi_divergence(GdpGdiInputs(gdp_growth_pct=1.5, gdi_growth_pct=4.0))

    assert as_bool(positive, key="significant") == as_bool(negative, key="significant")
    assert as_float(positive, key="divergence_pp") == pytest.approx(
        -as_float(negative, key="divergence_pp")
    )
    assert abs(as_float(positive, key="divergence_pp")) == pytest.approx(
        abs(as_float(negative, key="divergence_pp"))
    )


# ---------------------------------------------------------------------------
# Correction 4 — the average must be labelled for its unit
# ---------------------------------------------------------------------------


def test_the_output_names_the_average_as_a_growth_average() -> None:
    """Section 20.7 calls it ``average``; that name invites a level reading.

    The level wedge is systematically negative, so averaging levels is biased.
    The key must say which quantity it is.
    """
    result = gdp_gdi_divergence(GdpGdiInputs(gdp_growth_pct=4.0, gdi_growth_pct=2.0))

    assert isinstance(result.value, dict), "the value must be a dict of named outputs"
    assert "average_growth_pct" in result.value
    assert "average" not in result.value, (
        "the bare key 'average' must not exist; it invites a reader to average "
        "levels, where the wedge is not mean-zero"
    )


def test_the_level_wedge_is_reported_alongside_the_growth_divergence() -> None:
    """The two quantities must be distinguishable in the output."""
    result = gdp_gdi_divergence(GdpGdiInputs(gdp_growth_pct=4.0, gdi_growth_pct=2.0))

    assert isinstance(result.value, dict)
    assert "level_wedge_mean_pct" in result.value
    assert as_float(result, key="level_wedge_mean_pct") < 0, (
        "the measured level wedge is negative; a positive value means the "
        "sign convention was flipped somewhere"
    )
    # And the warning must tell the reader not to average levels.
    assert any("not the mean of the two levels" in w.lower() for w in result.warnings)


# ---------------------------------------------------------------------------
# D-029 — a boolean must travel with its base rate
# ---------------------------------------------------------------------------


def test_the_base_rate_is_reported_with_the_flag() -> None:
    """D-029's disclosure rule, applied to this module's boolean."""
    result = gdp_gdi_divergence(GdpGdiInputs(gdp_growth_pct=4.0, gdi_growth_pct=2.0))

    rate = as_float(result, key="divergence_base_rate")
    assert isinstance(rate, float)
    assert 0.0 < rate < 1.0
    assert rate != pytest.approx(0.5), "a coin-flip base rate is not a usable flag"


def test_the_reported_base_rate_matches_the_config() -> None:
    """The reported number must be the configured one, not a copy."""
    from macro_engine.config import get_settings

    configured = get_settings().gdp_gdi.divergence_base_rate.significant_rate
    result = gdp_gdi_divergence(GdpGdiInputs(gdp_growth_pct=4.0, gdi_growth_pct=2.0))

    assert as_float(result, key="divergence_base_rate") == pytest.approx(configured)


def test_the_warning_states_the_base_rate_as_a_frequency() -> None:
    """The reader must be told the frequency, not just handed the flag.

    A bare "significant" with no base rate reads as an anomaly; the whole point
    of D-029 is that a one-in-five event is not one.
    """
    result = gdp_gdi_divergence(GdpGdiInputs(gdp_growth_pct=4.0, gdi_growth_pct=2.0))
    joined = " ".join(result.warnings)

    rate = as_float(result, key="divergence_base_rate")
    assert f"{rate * 100:.1f}%" in joined, (
        f"the base rate {rate * 100:.1f}% must appear in the warnings verbatim"
    )


# ---------------------------------------------------------------------------
# Step 5 — warning paths
# ---------------------------------------------------------------------------


def test_the_significant_path_warns() -> None:
    result = gdp_gdi_divergence(GdpGdiInputs(gdp_growth_pct=3.0, gdi_growth_pct=5.0))
    assert any("exceeds the" in w and "threshold" in w for w in result.warnings)


def test_the_insignificant_path_also_warns() -> None:
    """'Not flagged' must not read as 'no discrepancy'.

    The threshold is illustrative, so silence on the insignificant path would
    imply a confidence the boundary does not support.
    """
    result = gdp_gdi_divergence(GdpGdiInputs(gdp_growth_pct=6.562, gdi_growth_pct=6.614))
    assert any("not flagged" in w.lower() for w in result.warnings)


def test_the_revision_warning_names_the_stale_after_window() -> None:
    from macro_engine.config import get_settings

    stale_after = get_settings().gdp_gdi.divergence_base_rate.stale_after
    result = gdp_gdi_divergence(GdpGdiInputs(gdp_growth_pct=4.0, gdi_growth_pct=2.0))

    assert any(f"{stale_after} quarters" in w for w in result.warnings)


def test_the_stale_after_window_is_read_from_config() -> None:
    """Same symmetry-breaking check as the threshold, for the revision window.

    The test above reads ``stale_after`` from config, so a hardcoded literal
    equal to the shipped value (2) would satisfy it. This patches the config to
    a value the literal cannot produce and asserts the warning follows.
    """
    from macro_engine.config import get_settings

    settings = get_settings()
    original = settings.gdp_gdi
    original_rate = original.divergence_base_rate

    settings.gdp_gdi = original.model_copy(
        update={
            "divergence_base_rate": original_rate.model_copy(
                update={
                    "stale_after_quarters": original_rate.stale_after_quarters.model_copy(
                        update={"value": 7}
                    )
                }
            )
        }
    )
    try:
        result = gdp_gdi_divergence(GdpGdiInputs(gdp_growth_pct=4.0, gdi_growth_pct=2.0))
        assert any("7 quarters" in w for w in result.warnings), (
            "the model did not honour the patched revision window, so it is not "
            "reading stale_after from config"
        )
    finally:
        settings.gdp_gdi = original


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_a_non_finite_input_is_rejected(value: float) -> None:
    """A NaN would make ``abs(nan) > t`` False and be reported as 'not significant'.

    That is a missing observation disguised as a finding, which Section 21.0
    exists to prevent — so it must raise, not pass through.
    """
    with pytest.raises(ValueError, match="non-finite"):
        gdp_gdi_divergence(GdpGdiInputs(gdp_growth_pct=value, gdi_growth_pct=2.0))

    with pytest.raises(ValueError, match="non-finite"):
        gdp_gdi_divergence(GdpGdiInputs(gdp_growth_pct=2.0, gdi_growth_pct=value))


def test_the_rejection_names_the_offending_field() -> None:
    """A two-float signature needs the message to say WHICH float was bad."""
    with pytest.raises(ValueError, match="gdi_growth_pct"):
        gdp_gdi_divergence(GdpGdiInputs(gdp_growth_pct=2.0, gdi_growth_pct=math.nan))


# ---------------------------------------------------------------------------
# Input contract
# ---------------------------------------------------------------------------


def test_a_typo_in_a_keyword_is_rejected() -> None:
    """``extra="forbid"`` on the input model."""
    with pytest.raises(Exception, match=r"extra_forbidden|Extra inputs"):
        GdpGdiInputs(gdp_growth_pct=4.0, gdi_growth_pct=2.0, gdp_growth=4.0)  # type: ignore[call-arg]


def test_the_input_model_documents_the_unit_contract() -> None:
    """Both fields must state that they are growth rates, not levels.

    There is no way to detect a level input from two anonymous floats, so the
    contract has to be discoverable from the model and the field text.
    """
    for name in ("gdp_growth_pct", "gdi_growth_pct"):
        field = GdpGdiInputs.model_fields[name]
        assert field.description is not None
        assert "percent" in field.description.lower()

    doc = GdpGdiInputs.__doc__ or ""
    assert "growth" in doc.lower()
    assert "level" in doc.lower(), "the docstring must warn against level inputs"


# ---------------------------------------------------------------------------
# Result contract
# ---------------------------------------------------------------------------


def test_the_result_carries_its_provenance() -> None:
    result = gdp_gdi_divergence(GdpGdiInputs(gdp_growth_pct=4.0, gdi_growth_pct=2.0))

    assert result.model_name == "gdp_gdi_divergence"
    assert result.country == "us"
    assert result.as_of.tzinfo is not None, "as_of must be timezone-aware"
    assert result.inputs_used == ["gdp_growth_pct", "gdi_growth_pct"]
    assert result.context
    assert result.warnings


@pytest.mark.parametrize(
    ("gdp", "gdi"),
    [(6.562, 6.614), (3.0, 5.0), (0.0, 0.0), (-2.0, -3.5), (0.5, -0.5)],
)
def test_every_run_carries_warnings(gdp: float, gdi: float) -> None:
    """Module 7.1's output is never warning-free: the residual facts always apply."""
    result = gdp_gdi_divergence(GdpGdiInputs(gdp_growth_pct=gdp, gdi_growth_pct=gdi))
    assert len(result.warnings) >= 5, (
        "four standing warnings (residual, sign, level-vs-growth, revisions) plus "
        "one path-specific warning are always present"
    )
