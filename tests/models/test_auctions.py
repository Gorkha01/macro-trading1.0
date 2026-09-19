"""Tests for Module 8.2 — ``auction_demand_signal``.

Four findings from the probe shape what is worth asserting (D-036):

1. **The tail input is MANUAL.** No route publishes the when-issued yield a
   tail is measured against, so the model must disclose that one of its five
   numbers was typed by a human. A disclosure that is not tested is a
   disclosure that can be dropped.
2. **The sign convention inverts the answer.** ``stop_through_bp`` is
   (expected - clearing), so negative is a tail. Both signs produce a plausible
   verdict, which is exactly why the published ``tailed`` flag is asserted
   against a value whose sign is known before the call.
3. **The indirect share has two bases differing by ~27pp.** The model takes the
   accepted basis; that is a property of the input contract, so it is pinned in
   the field description rather than in arithmetic.
4. **Both flags fire often** — 17.9% and 32.1% of 140 live auctions — so per
   D-029 each must travel with its own measured frequency.

The thresholds are read from config, so every test that depends on one patches
the config to a value the literal cannot produce (PROGRESS.md rule 7), and the
synthetic leaves are all DISTINCT so an accessor swap cannot hide (D-035).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from macro_engine.config import (
    AuctionBaseRates,
    AuctionDemandSettings,
    CalibratedValue,
    get_settings,
)
from macro_engine.models.auctions import AuctionInputs, auction_demand_signal
from macro_engine.models.contracts import ConfidenceInputs, compute_confidence
from tests.helpers import as_bool, as_float, as_int, as_str


def _leaf(value: float | int) -> CalibratedValue:
    """A synthetic config leaf whose value this test chose.

    Every leaf a test patches in is given a DIFFERENT value, so no two can be
    confused and an accessor that reads the wrong field cannot pass (D-035).
    """
    return CalibratedValue(
        value=value,
        calibration_status="fitted_assumption",
        note="synthetic — chosen by this test to be distinct from every other leaf",
    )


def _settings() -> AuctionDemandSettings:
    return get_settings().auction_demand


def _inputs(
    *,
    btc: float = 2.60,
    btc_avg: float = 2.50,
    indirect: float = 60.0,
    indirect_avg: float = 58.0,
    stop_through: float = 0.5,
) -> AuctionInputs:
    """Inputs whose every branch is known by construction.

    Defaults are a CLEANLY STRONG auction: bid-to-cover 2.60 against a 2.50
    average (4% above, so not weak), indirect 60.0 against 58.0 (2pp above, so
    not fading), and a +0.5bp stop-through (positive, so not tailed).
    """
    return AuctionInputs(
        bid_to_cover=btc,
        bid_to_cover_trailing_avg=btc_avg,
        indirect_bidder_pct=indirect,
        indirect_bidder_trailing_avg=indirect_avg,
        stop_through_bp=stop_through,
    )


# ---------------------------------------------------------------------------
# The four verdict branches
# ---------------------------------------------------------------------------


def test_weak_and_tailed_is_the_term_premium_verdict() -> None:
    """Both conditions present -> the weak verdict.

    Hand-checked: 2.30 against 2.50 x 0.95 = 2.375, so weak; -1.5bp is below
    the 0.0 boundary, so tailed.
    """
    result = auction_demand_signal(_inputs(btc=2.30, stop_through=-1.5))
    assert as_str(result, key="verdict") == "WEAK_AUCTION_term_premium_pressure"
    assert as_bool(result, key="weak_bid_to_cover") is True
    assert as_bool(result, key="tailed") is True


def test_neither_condition_is_a_strong_auction() -> None:
    """Neither condition present -> the strong verdict."""
    result = auction_demand_signal(_inputs(btc=2.60, stop_through=0.5))
    assert as_str(result, key="verdict") == "STRONG_AUCTION"
    assert as_bool(result, key="weak_bid_to_cover") is False
    assert as_bool(result, key="tailed") is False


def test_a_weak_auction_that_did_not_tail_is_mixed() -> None:
    """One condition only -> MIXED. A weak bid-to-cover with no tail is not
    the term-premium verdict, because the two are separate evidence."""
    result = auction_demand_signal(_inputs(btc=2.30, stop_through=0.5))
    assert as_str(result, key="verdict") == "MIXED"
    assert as_bool(result, key="weak_bid_to_cover") is True
    assert as_bool(result, key="tailed") is False


def test_a_tail_on_a_strong_bid_to_cover_is_mixed() -> None:
    """The mirror of the previous case, and it must not be reported as weak."""
    result = auction_demand_signal(_inputs(btc=2.60, stop_through=-1.5))
    assert as_str(result, key="verdict") == "MIXED"
    assert as_bool(result, key="weak_bid_to_cover") is False
    assert as_bool(result, key="tailed") is True


# ---------------------------------------------------------------------------
# The boundaries. Built so the comparison's strictness is observable.
# ---------------------------------------------------------------------------


def test_the_bid_to_cover_threshold_comes_from_config_and_is_strict() -> None:
    """A value exactly at the threshold is NOT weak.

    The config ratio is patched to 0.5 and the average to 4.0, so the threshold
    is exactly 2.0 — a value that can be written down rather than one that has
    to be rounded. At exactly 2.0 the comparison ``2.0 < 2.0`` is False, so the
    auction is not weak; a fixture built by subtracting an epsilon would test a
    point *outside* the band while claiming its edge.
    """
    patched = _settings().model_copy(update={"weak_bid_to_cover_ratio_value": _leaf(0.5)})
    with patch("macro_engine.models.auctions._auction_settings", return_value=patched):
        at_boundary = auction_demand_signal(_inputs(btc=2.0, btc_avg=4.0))
        just_below = auction_demand_signal(_inputs(btc=1.99, btc_avg=4.0))
    assert as_bool(at_boundary, key="weak_bid_to_cover") is False, (
        "exactly at 0.5 x 4.0 = 2.0 the comparison must be False — it is strict"
    )
    assert as_bool(just_below, key="weak_bid_to_cover") is True


def test_the_tail_boundary_is_zero_and_strict() -> None:
    """The boundary is 0.0bp, and a value exactly at it is not a tail.

    Two halves, and the first is the one that took a mutation sweep to get
    right. Asserting the shipped value is exactly zero is a **definitional**
    check — a tail is a negative stop-through, so the boundary has no free
    parameter and a non-zero value would be a defect.

    The earlier version read the boundary from ``_settings().tail_boundary_bp``
    and tested against it, which is PROGRESS.md rule 7: the test's expectation
    moved with the accessor, so a mutation making that property return 0.5
    passed. The strictness check below now patches in a boundary the shipped
    config cannot produce, so both the value and its use are pinned.
    """
    assert _settings().tail_boundary_bp == 0.0, (
        "the tail boundary is definitional — a tail IS a negative stop-through — "
        "so a non-zero value here is a defect, not a calibration choice"
    )

    patched = _settings().model_copy(update={"tail_boundary_bp_value": _leaf(1.5)})
    with patch("macro_engine.models.auctions._auction_settings", return_value=patched):
        at_patched = auction_demand_signal(_inputs(stop_through=1.5))
        below_patched = auction_demand_signal(_inputs(stop_through=1.4))
    assert as_bool(at_patched, key="tailed") is False, (
        "with the boundary patched to 1.5, a stop-through of exactly 1.5 is not a "
        "tail — the comparison is strict"
    )
    assert as_bool(below_patched, key="tailed") is True

    # And on the shipped boundary, the same strictness holds at zero.
    at_zero = auction_demand_signal(_inputs(stop_through=0.0))
    assert as_bool(at_zero, key="tailed") is False


def test_the_indirect_fade_threshold_comes_from_config() -> None:
    """The fade threshold is read from config, not baked in.

    Patched to 12.0pp, which the shipped 3.0pp literal cannot produce: an
    indirect share 5pp below its average must NOT be fading under the patched
    value, and must be under the shipped one.
    """
    patched = _settings().model_copy(update={"indirect_fade_threshold_pp_value": _leaf(12.0)})
    with patch("macro_engine.models.auctions._auction_settings", return_value=patched):
        under_patched = auction_demand_signal(_inputs(indirect=53.0, indirect_avg=58.0))
    under_shipped = auction_demand_signal(_inputs(indirect=53.0, indirect_avg=58.0))
    assert as_bool(under_patched, key="foreign_demand_fading") is False, (
        "5pp below the average is inside a 12pp band"
    )
    assert as_bool(under_shipped, key="foreign_demand_fading") is True, (
        "5pp below the average is outside the shipped 3pp band"
    )


def test_the_fade_threshold_boundary_is_strict() -> None:
    """Exactly the threshold below the average is not fading."""
    patched = _settings().model_copy(update={"indirect_fade_threshold_pp_value": _leaf(5.0)})
    with patch("macro_engine.models.auctions._auction_settings", return_value=patched):
        at_boundary = auction_demand_signal(_inputs(indirect=55.0, indirect_avg=60.0))
    assert as_bool(at_boundary, key="foreign_demand_fading") is False, (
        "60.0 - 5.0 = 55.0 exactly, and the comparison is strict"
    )


# ---------------------------------------------------------------------------
# The sign convention — the trap that inverts without changing plausibility
# ---------------------------------------------------------------------------


def test_the_stop_through_sign_convention_is_negative_is_tailed() -> None:
    """A negative stop-through is a tail; a positive one is not.

    The direction is known before the call, so this is a sign assertion rather
    than a restatement of the code: an auction that cleared ABOVE expectations
    is the weak one. Reversing the convention flips every verdict while leaving
    both values perfectly plausible (the D-034 failure mode).
    """
    tailed = auction_demand_signal(_inputs(stop_through=-2.0))
    stopped_through = auction_demand_signal(_inputs(stop_through=+2.0))
    assert as_bool(tailed, key="tailed") is True, (
        "the auction cleared above expectations, which is a tail, which is weak"
    )
    assert as_bool(stopped_through, key="tailed") is False


def test_the_published_flag_matches_the_raw_value_in_sign() -> None:
    """The published flag and the raw bp must tell the same story.

    A reader auditing the verdict reads ``stop_through_bp``; if the flag were
    computed against the wrong side of zero the two would disagree, and the
    output would carry its own contradiction.
    """
    for value in (-3.0, -0.01, 0.0, 0.01, 3.0):
        result = auction_demand_signal(_inputs(stop_through=value))
        raw = as_float(result, key="stop_through_bp")
        flag = as_bool(result, key="tailed")
        assert flag == (raw < _settings().tail_boundary_bp), (
            f"stop_through_bp={value} published tailed={flag}; the flag must be "
            f"the sign of the raw value against the boundary"
        )


# ---------------------------------------------------------------------------
# The cross-field identity (D-009)
# ---------------------------------------------------------------------------


def test_the_verdict_is_recomputable_from_its_published_components() -> None:
    """The verdict must equal what the published flags imply.

    This is the cross-field identity: recompute the reported value from its
    reported components. A verdict that disagreed with its own booleans would
    be unauditable, and the disagreement is exactly what a reordered branch
    would produce.
    """
    cases = [
        (2.30, 2.50, -1.5),
        (2.60, 2.50, 0.5),
        (2.30, 2.50, 0.5),
        (2.60, 2.50, -1.5),
    ]
    for btc, btc_avg, stop_through in cases:
        result = auction_demand_signal(_inputs(btc=btc, btc_avg=btc_avg, stop_through=stop_through))
        weak = as_bool(result, key="weak_bid_to_cover")
        tailed = as_bool(result, key="tailed")
        expected = (
            "WEAK_AUCTION_term_premium_pressure"
            if weak and tailed
            else "STRONG_AUCTION"
            if not weak and not tailed
            else "MIXED"
        )
        assert as_str(result, key="verdict") == expected, (
            f"btc={btc} tail={stop_through}: published verdict disagrees with "
            f"its own published flags (weak={weak}, tailed={tailed})"
        )


def test_the_raw_inputs_are_republished_unchanged() -> None:
    """Every input must appear in the output at the reported precision.

    A consumer who reads only ``value`` must be able to see what the model was
    given, because the manual entry among them cannot be re-derived.
    """
    result = auction_demand_signal(
        _inputs(btc=2.31, btc_avg=2.49, indirect=61.5, indirect_avg=58.25, stop_through=-1.25)
    )
    assert as_float(result, key="bid_to_cover") == pytest.approx(2.31)
    assert as_float(result, key="bid_to_cover_trailing_avg") == pytest.approx(2.49)
    assert as_float(result, key="indirect_bidder_pct") == pytest.approx(61.5)
    assert as_float(result, key="indirect_bidder_trailing_avg") == pytest.approx(58.25)
    assert as_float(result, key="stop_through_bp") == pytest.approx(-1.25)


# ---------------------------------------------------------------------------
# The disclosures
# ---------------------------------------------------------------------------


def test_the_manual_entry_of_the_tail_input_is_published_and_warned() -> None:
    """The one hand-entered number must be flagged in the output AND warned about.

    Two halves, because either alone is insufficient: a reader parsing ``value``
    needs the flag, and a reader reading prose needs the sentence. The warning
    must name the field, since a warning that says "an input is manual" without
    saying which is not actionable.
    """
    result = auction_demand_signal(_inputs())
    assert as_bool(result, key="stop_through_is_manual_entry") is True, (
        "the tail input is manual entry and the output must say so"
    )
    matches = [w for w in result.warnings if "MANUAL ENTRY" in w]
    assert len(matches) == 1, (
        f"the manual-entry disclosure must appear exactly once; found {len(matches)}"
    )
    assert "stop_through_bp" in matches[0], "the warning must name the field that was hand-entered"


def test_the_sign_convention_is_warned_about_in_prose() -> None:
    """The convention must reach a reader who reads warnings, not field text.

    The field description is where a caller learns the convention, but a
    consumer reading a result never sees it. The warning must state the
    direction (negative is a tail) AND name the field, because a warning that
    says "mind the sign" without saying which sign is not actionable.

    This test exists because a mutation removing the warning survived the first
    sweep: the manual-entry and base-rate warnings were both asserted, and this
    one was not.
    """
    result = auction_demand_signal(_inputs())
    matches = [w for w in result.warnings if "Sign convention" in w]
    assert len(matches) == 1, (
        f"the sign-convention warning must appear exactly once; found {len(matches)}"
    )
    warning = matches[0]
    assert "stop_through_bp" in warning, "the warning must name the field"
    assert "TAIL" in warning, "the warning must state what a negative value means"


def test_both_flags_travel_with_their_measured_base_rate() -> None:
    """D-029: a flag from a noisy comparison must carry its own frequency.

    The rates are patched to distinct values, so the assertion cannot be
    satisfied by an accessor reading the wrong leaf or by a hardcoded literal.
    """
    base = _settings().base_rates
    patched_rates = AuctionBaseRates(
        auctions_measured_value=_leaf(1234),
        weak_bid_to_cover_rate_value=_leaf(0.1111),
        foreign_fading_rate_value=_leaf(0.2222),
    )
    patched = _settings().model_copy(update={"base_rates": patched_rates})
    with patch("macro_engine.models.auctions._auction_settings", return_value=patched):
        result = auction_demand_signal(_inputs())

    assert as_int(result, key="auctions_measured") == 1234
    assert as_float(result, key="weak_bid_to_cover_base_rate") == pytest.approx(0.1111)
    assert as_float(result, key="foreign_fading_base_rate") == pytest.approx(0.2222)
    assert base.auctions_measured != 1234, (
        "the fixture must differ from the shipped record or the patch proves nothing"
    )
    # Both rates must also reach the prose, which is where a reader meets them.
    assert any("11.1%" in w for w in result.warnings), (
        "the weak bid-to-cover rate must be stated in a warning"
    )
    assert any("22.2%" in w for w in result.warnings), (
        "the foreign-fading rate must be stated in a warning"
    )


def test_the_verdict_does_not_fold_in_the_indirect_share_and_says_so() -> None:
    """A STRONG verdict alongside fading indirect demand must be qualified.

    The verdict is computed from price outcomes only. The one case where that
    omission could mislead is a clean price outcome with deteriorating
    composition, so the model must say which it is.
    """
    result = auction_demand_signal(_inputs(btc=2.60, indirect=50.0, indirect_avg=58.0))
    assert as_str(result, key="verdict") == "STRONG_AUCTION"
    assert as_bool(result, key="foreign_demand_fading") is True
    matches = [w for w in result.warnings if "does not incorporate" in w]
    assert len(matches) == 1, f"exactly one warning must qualify the verdict; found {len(matches)}"


def test_the_qualification_is_absent_when_indirect_demand_is_not_fading() -> None:
    """The absence half: the qualifier must not fire unconditionally.

    An assertion that a warning is present is half a test without the case
    where it must be absent (D-035's M7b).
    """
    result = auction_demand_signal(_inputs(btc=2.60, indirect=60.0, indirect_avg=58.0))
    assert as_str(result, key="verdict") == "STRONG_AUCTION"
    assert as_bool(result, key="foreign_demand_fading") is False
    assert not any("does not incorporate" in w for w in result.warnings), (
        "the qualifier must not appear when composition is healthy"
    )


def test_the_single_auction_warning_is_always_present() -> None:
    """Section 20.8's own warning must survive every branch."""
    for stop_through in (-2.0, 0.0, 2.0):
        result = auction_demand_signal(_inputs(stop_through=stop_through))
        assert any("temporary liquidity artifact" in w for w in result.warnings), (
            "the persistence caveat is the reason one print is not a conclusion"
        )


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------


def test_confidence_is_computed_not_asserted() -> None:
    """Section 22.8: confidence comes from stated factors.

    The expected value is recomputed from ``ConfidenceInputs`` here rather than
    written as a number, so calibrating the thresholds in a later phase moves
    this test with the model instead of breaking it.
    """
    result = auction_demand_signal(_inputs())
    expected = compute_confidence(
        ConfidenceInputs(
            is_heuristic_not_calibrated=not _thresholds_calibrated_today(),
            source_independence_count=0,
        )
    )
    assert result.confidence == pytest.approx(expected)


def test_the_heuristic_penalty_is_applied_while_the_thresholds_are_placeholders() -> None:
    """An uncalibrated threshold must lower confidence automatically.

    Both thresholds are ``uncalibrated_illustrative`` today, so the model must
    take the heuristic penalty. Asserted as an inequality against the base so
    the test states the *reason*, not the arithmetic.
    """
    result = auction_demand_signal(_inputs())
    base = get_settings().confidence.values["base"]
    assert _thresholds_calibrated_today() is False, (
        "this test assumes the thresholds are still illustrative; if a phase "
        "calibrates them, replace this test rather than deleting it"
    )
    assert result.confidence < base, "leaning on uncalibrated thresholds must cost confidence"


def test_confidence_rises_when_the_thresholds_are_calibrated() -> None:
    """The penalty is wired to the calibration status, not hardcoded.

    Patched to True, which the shipped config cannot produce. This is the test
    that would fail if someone replaced the derived factor with a literal.
    """
    with patch("macro_engine.models.auctions._thresholds_calibrated", return_value=True):
        calibrated = auction_demand_signal(_inputs())
    illustrative = auction_demand_signal(_inputs())
    assert calibrated.confidence > illustrative.confidence, (
        "calibrating the thresholds must raise confidence; a hardcoded factor "
        "would leave the two equal"
    )


def _thresholds_calibrated_today() -> bool:
    """The shipped calibration status of Module 8.2's two decision thresholds."""
    from macro_engine.models.auctions import _thresholds_calibrated

    return _thresholds_calibrated()


# ---------------------------------------------------------------------------
# The input contract
# ---------------------------------------------------------------------------


def test_the_input_contract_forbids_extra_fields() -> None:
    """``extra="forbid"`` so a misspelled input fails loudly.

    The fixture supplies **all five valid fields plus one unknown field**. That
    is deliberate, and it is the second version of this test. The first passed
    ``stop_through=-1.0`` instead of ``stop_through_bp`` and matched the error
    against ``"stop_through"`` — but with ``extra="forbid"`` REMOVED the
    unknown field is simply ignored, ``stop_through_bp`` is then missing, and
    the "field required" message still contains ``stop_through_bp``, which
    matches. The assertion passed under the mutation, so the mutation survived.

    A complete valid payload plus one extra field has no such ambiguity: the
    only thing that can make it raise is the forbid itself.
    """
    with pytest.raises(Exception, match="stop_through"):
        AuctionInputs(  # type: ignore[call-arg]
            bid_to_cover=2.5,
            bid_to_cover_trailing_avg=2.5,
            indirect_bidder_pct=60.0,
            indirect_bidder_trailing_avg=58.0,
            stop_through_bp=-1.0,
            stop_through=-1.0,
        )


def test_the_trailing_window_is_published_from_config() -> None:
    """The window must be observable in the output.

    A config leaf that no code path reads is one a mutation can change with no
    consequence, which is what the first sweep found: hardcoding
    ``trailing_window_auctions`` to 3 changed nothing, because the model never
    read it. It is now published, so a caller can see what window the averages
    they supplied were taken over.

    The value is patched to one the shipped config does not hold, so an
    accessor returning a literal cannot pass.
    """
    patched = _settings().model_copy(update={"trailing_window_auctions_value": _leaf(9)})
    with patch("macro_engine.models.auctions._auction_settings", return_value=patched):
        result = auction_demand_signal(_inputs())
    assert as_int(result, key="trailing_window_auctions") == 9, (
        "the published window must be the configured one"
    )
    assert _settings().trailing_window_auctions != 9, (
        "the fixture must differ from the shipped window or the patch proves nothing"
    )


def test_a_non_positive_trailing_average_is_refused() -> None:
    """A zero or negative comparison base must be refused, not divided by.

    A zero bid-to-cover average would make ``btc < 0 x 0.95`` False for every
    auction, silently disabling the flag. A zero indirect average would do the
    same through the subtraction. Both are refusals rather than substitutions
    (Section 21.0 rule 4).
    """
    with pytest.raises(Exception, match="bid_to_cover_trailing_avg"):
        _inputs(btc_avg=0.0)
    with pytest.raises(Exception, match="bid_to_cover_trailing_avg"):
        _inputs(btc_avg=-1.0)
    with pytest.raises(Exception, match="indirect_bidder_trailing_avg"):
        _inputs(indirect_avg=0.0)


def test_an_indirect_share_outside_zero_to_one_hundred_is_refused() -> None:
    """The share is a percentage of the amount accepted, so it is bounded.

    A negative share or one above 100% is arithmetically impossible and is
    refused rather than clamped.
    """
    with pytest.raises(Exception, match="indirect_bidder_pct"):
        _inputs(indirect=-1.0)
    with pytest.raises(Exception, match="indirect_bidder_pct"):
        _inputs(indirect=140.0)


def test_a_fraction_passed_as_a_percentage_is_not_caught_by_the_range_check() -> None:
    """The residual risk, asserted so it is not mistaken for a defended case.

    A caller passing ``0.55`` meaning "55%" instead of ``55.0`` is the likely
    unit error, and **the ``[0, 100]`` bound does not catch it** — 0.55 is a
    perfectly legal percentage. The mistake is silent, and it reads as a
    collapse in demand rather than as a unit slip.

    This test exists because the first version of the range test *claimed* to
    cover this case and did not: it asserted that ``0.55`` would raise, and
    ``0.55`` does not raise. A test asserting a defence that is not there is
    worse than no test, because it closes the question.

    The behaviour below is what actually happens, recorded rather than wished
    away. Closing it properly needs either a cross-field scale check (the share
    and its trailing average must be on the same scale) or a units convention
    in the input model, and neither is in Section 20.8's contract.
    """
    result = auction_demand_signal(_inputs(indirect=0.55, indirect_avg=58.0))
    assert as_float(result, key="indirect_bidder_pct") == pytest.approx(0.55)
    assert as_bool(result, key="foreign_demand_fading") is True, (
        "a 57pp 'fade' is what the unit error produces — flagged as fading, "
        "which is the right answer to the wrong question"
    )


def test_every_input_used_is_declared() -> None:
    """``inputs_used`` must list all five, including the trailing averages.

    Section 20.8's sample lists three. The trailing averages are also consumed,
    and an undeclared input is one a consumer cannot audit.
    """
    result = auction_demand_signal(_inputs())
    assert set(result.inputs_used) == {
        "bid_to_cover",
        "bid_to_cover_trailing_avg",
        "indirect_bidder_pct",
        "indirect_bidder_trailing_avg",
        "stop_through_bp",
    }
