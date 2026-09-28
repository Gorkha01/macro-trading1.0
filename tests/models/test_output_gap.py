"""Phase 2 model tests — the output gap (AGENTS.md Section 11.1, Section 21.2).

Section 11.1 names four Phase 2 tests. Two concern the policy-rule family and
two concern functions in this module's neighbourhood; the one that belongs
here is:

    ``test_output_gap_sign()`` — actual > potential must yield a positive gap,
    and vice versa, on at least two hand-picked numeric cases.

It is present, and it is genuinely two hand-picked cases rather than one case
checked twice (``above`` and ``below``, with different magnitudes and different
arithmetic paths through the round).

Every expected value below was computed **before** the test was run, per
Section 21.2 Step 4:

    "If the test passes on the first attempt without you having computed the
     expected value independently, the test is worthless — you have asserted
     whatever the code produced."

The arithmetic is shown inline in each case.
"""

from __future__ import annotations

from datetime import date

import pytest

from macro_engine.data_layer.schemas import MacroDataSnapshot, ObservationPoint
from macro_engine.models.contracts import ConfidenceInputs, compute_confidence, utc_now
from macro_engine.models.gdp_nowcast import (
    OutputGapInputs,
    output_gap,
    output_gap_from_snapshot,
)
from tests.conftest import make_points, make_snapshot
from tests.helpers import as_float

# ---------------------------------------------------------------------------
# Step 4 — the formula, against hand-computed values
# ---------------------------------------------------------------------------


@pytest.mark.golden
def test_output_gap_matches_the_specified_formula_exactly() -> None:
    """The published 2026-09-16 snapshot pair, checked against hand arithmetic.

    Hand computation:
        actual    = 24,269.613  (FRED GDPC1, Q2 2026)
        potential = 29,443.0227 (FRED GDPPOT, CBO, same quarter)
        gap       = (24269.613 - 29443.0227) / 29443.0227 * 100
                  = -5173.4097 / 29443.0227 * 100
                  = -0.175709191... * 100
                  = -17.570919...
        round(..., 2) = -17.57
    """
    result = output_gap(OutputGapInputs(actual_gdp=24_269.613, potential_gdp=29_443.0227))

    assert result.value == pytest.approx(-17.57, abs=0.005)
    assert result.value == round(-17.570919102677593, 2)


@pytest.mark.golden
def test_output_gap_is_exactly_zero_when_at_potential() -> None:
    """A boundary case worth pinning: equality produces *positive* zero.

    ``(100 - 100) / 100 * 100 == 0.0``, and ``round(0.0, 2) == 0.0``. The
    interpretation string must say "at potential" rather than picking a
    direction — ``gap_pct > 0`` is False at exactly zero, so a naive
    ternary would label equilibrium as "below potential". This test would
    catch that.
    """
    result = output_gap(OutputGapInputs(actual_gdp=100.0, potential_gdp=100.0))

    assert result.value == 0.0
    assert "at potential" in result.interpretation
    assert "below" not in result.interpretation


# ---------------------------------------------------------------------------
# Section 11.1 MANDATED — test_output_gap_sign()
# ---------------------------------------------------------------------------


@pytest.mark.golden
def test_output_gap_sign_above_potential_is_positive() -> None:
    """MANDATED (Section 11.1). Hand-picked case 1 of 2: actual > potential.

    Hand computation:
        actual = 21,000, potential = 20,000
        gap = (21000 - 20000) / 20000 * 100 = 1000/20000*100 = 0.05*100 = +5.0
    """
    result = output_gap(OutputGapInputs(actual_gdp=21_000.0, potential_gdp=20_000.0))

    assert result.value == 5.0, "actual above potential must yield a POSITIVE gap"
    assert isinstance(result.value, float)
    assert +result.value > 0
    assert "above potential" in result.interpretation


@pytest.mark.golden
def test_output_gap_sign_below_potential_is_negative() -> None:
    """MANDATED (Section 11.1). Hand-picked case 2 of 2: actual < potential.

    Hand computation:
        actual = 20,000, potential = 21,000
        gap = (20000 - 21000) / 21000 * 100 = -1000/21000*100 = -4.761904...
        round(..., 2) = -4.76

    Deliberately chosen with a *non-round* denominator so the assertion is
    sensitive to sign and magnitude, not just to a round-number coincidence:
    a sign flip here yields +4.76, which differs from -4.76 by 9.52 — far
    outside any tolerance, while a sign flip on a symmetric pair like
    (21k, 20k)/(20k, 21k) would differ by exactly 10.0 and could be masked by
    a sloppy tolerance.
    """
    result = output_gap(OutputGapInputs(actual_gdp=20_000.0, potential_gdp=21_000.0))

    assert result.value == -4.76, "actual below potential must yield a NEGATIVE gap"
    assert +result.value < 0
    assert "below potential" in result.interpretation
    # Explicit mirror check: the two mandated cases must have opposite signs.
    mirrored = output_gap(OutputGapInputs(actual_gdp=21_000.0, potential_gdp=20_000.0))
    assert mirrored.value is not None
    assert as_float(result) < 0 < as_float(mirrored)


# ---------------------------------------------------------------------------
# Section 21.2 Step 5 — warning paths
# ---------------------------------------------------------------------------


@pytest.mark.warning_path
def test_output_gap_always_warns_that_potential_is_an_estimate() -> None:
    """Step 5: the mandatory warning must actually fire, not just exist.

    Section 6.5 specifies this warning unconditionally. A warning that is
    specified but never asserted is an untested safety mechanism — it could be
    commented out and nothing would notice.
    """
    result = output_gap(OutputGapInputs(actual_gdp=21_000.0, potential_gdp=20_000.0))

    assert result.warnings, "output_gap must always carry at least one warning"
    joined = " ".join(result.warnings)
    assert "ESTIMATE, not observed" in joined
    assert "Module 7.2" in joined


def test_output_gap_refuses_a_non_positive_potential() -> None:
    """A zero denominator is rejected by the input contract, not by luck.

    ``(actual - 0)/0`` is a ZeroDivisionError, but ``(actual - (-5))/(-5)`` is
    finite and would *invert the sign* of the gap — a negative potential GDP
    would make a shortfall read as an excess. The constraint lives on the input
    model so both are impossible by construction.
    """
    with pytest.raises(ValueError, match="greater than 0"):
        OutputGapInputs(actual_gdp=21_000.0, potential_gdp=0.0)
    with pytest.raises(ValueError, match="greater than 0"):
        OutputGapInputs(actual_gdp=21_000.0, potential_gdp=-5.0)


def test_output_gap_confidence_is_computed_never_a_literal() -> None:
    """Section 22.8: no model may hardcode confidence.

    This assertion needed two rewrites, and both reasons are worth recording
    because together they define the limit of what a unit test can prove here.

    **Attempt 1** asserted ``confidence == compute_confidence(...)`` and
    ``<= 0.5``. Mutation testing — substituting ``confidence=0.5``, the exact
    literal Section 22.8 bans — showed **all 17 tests still passed**. The
    specified literal and the computed value coincide:

        base 0.7 - unobservable_penalty 0.2 - source_independence 0 = 0.5

    **Attempt 2** asserted the flagged path yields a value different from the
    unflagged one. Mutating *both* call sites to their respective literals
    (0.5 and 0.25) still passed — because the flagged literal was chosen to
    match, which is circular: it tests that two hardcoded numbers differ, not
    that either is computed.

    The root cause is not the test. Every constant in the confidence formula is
    ``uncalibrated_illustrative`` (verified: ``settings.is_calibrated(
    "confidence.base") is False``), and with the current constants the
    formula's outputs happen to land exactly on the specification's
    illustrative literals. **With this config, no black-box assertion on
    confidence alone can distinguish computation from a hardcoded literal** —
    the two are numerically identical. Claiming otherwise would be a test that
    looks like a guarantee and is not.

    What is therefore asserted instead: the *structure* is present and wired,
    and the discrimination gap is computed rather than assumed. The moment
    Phase 5+ calibrates ``base``, the gap becomes non-zero and
    ``test_confidence_formula_becomes_discriminating_once_calibrated`` starts
    enforcing the real requirement.
    """
    result = output_gap(OutputGapInputs(actual_gdp=21_000.0, potential_gdp=20_000.0))

    bare = compute_confidence(
        ConfidenceInputs(depends_on_unobservable=True, source_independence_count=0)
    )
    assert result.confidence == bare
    assert 0.0 <= result.confidence <= 1.0

    flagged_result, _ = output_gap_from_snapshot(
        _live_shaped_snapshot(data_quality_flags=["[ERROR] gdp_real: VALUE_ABOVE_MAX — 999999"])
    )
    flagged = compute_confidence(
        ConfidenceInputs(
            depends_on_unobservable=True,
            data_quality_flags_present=True,
            source_independence_count=0,
        )
    )
    assert flagged_result.confidence == flagged
    assert flagged < bare, "a flagged snapshot must carry less confidence than a clean one"

    # Record the discrimination gap explicitly. Today it is zero, which IS the
    # finding: the test above cannot currently fail for the right reason.
    assert _confidence_discrimination_gap() == pytest.approx(0.0), (
        "The discrimination gap closed — Phase 5+ has calibrated the confidence "
        "constants, so test_confidence_formula_becomes_discriminating_once_calibrated "
        "is now live and this test's docstring is stale. Update both."
    )


def _confidence_discrimination_gap() -> float:
    """How far the confidence formula's output for a bare call sits from 0.5.

    The specification's illustrative literal for this model is 0.5 (Section
    6.5). While ``compute_confidence`` also returns 0.5, a hardcoded literal is
    indistinguishable from the computation. The gap is the sharpest available
    measure of whether the config still has that coincidence.
    """
    return abs(
        compute_confidence(
            ConfidenceInputs(depends_on_unobservable=True, source_independence_count=0)
        )
        - 0.5
    )


def test_confidence_formula_becomes_discriminating_once_calibrated() -> None:
    """The requirement that will bite after Phase 5+ calibration.

    Skips while the config's constants make computation and literal
    numerically identical (see the sibling test). Not a permanently-skipped
    test: it asserts the *precondition* for its own skip, so it cannot rot into
    a test nobody notices is never running — if the precondition changes, the
    assertion below executes and a hardcoded literal fails it.
    """
    gap = _confidence_discrimination_gap()
    if gap == pytest.approx(0.0):
        pytest.skip(
            "Confidence constants are still uncalibrated_illustrative and the formula "
            "coincides with the specification's literal; discrimination is impossible "
            "until Phase 5+ calibrates confidence.base."
        )

    result = output_gap(OutputGapInputs(actual_gdp=21_000.0, potential_gdp=20_000.0))
    assert result.confidence != 0.5, (
        "the confidence formula is now discriminating, so a hardcoded 0.5 is "
        "detectable and must not appear"
    )


def test_output_gap_confidence_never_exceeds_the_banned_literal() -> None:
    """Section 6.5's illustrative ``confidence=0.5`` is an upper bound, not a target.

    Section 22.8 replaces the literal with a computation; the computation may
    only be *more* humble about an output gap built from an unobservable
    potential-output estimate. It must never be less.

    Honest note on its strength: with the current illustrative config constants
    this bound is met with **zero margin** (base 0.7 - unobservable 0.2 = 0.5
    exactly), so on its own this assertion is currently non-discriminating. It
    is retained because it becomes binding the moment Phase 5+ raises ``base``
    — which is precisely when an unnoticed regression would let this model
    claim more confidence about an unobservable than the specification allows.
    """
    result = output_gap(OutputGapInputs(actual_gdp=21_000.0, potential_gdp=20_000.0))

    assert result.confidence <= 0.5


def test_output_gap_declares_its_inputs_and_is_us_scoped() -> None:
    result = output_gap(OutputGapInputs(actual_gdp=21_000.0, potential_gdp=20_000.0))

    assert result.inputs_used == ["actual_gdp", "potential_gdp"]
    assert result.model_name == "output_gap"
    assert result.country == "us"
    assert result.as_of.tzinfo is not None, "as_of must be timezone-aware (DTZ rule)"


def test_output_gap_input_contract_is_exactly_two_floats() -> None:
    """The docstring's Confidence section and ``OutputGapInputs`` must agree (D-127).

    This test exists because they once did NOT. The docstring listed four
    caller-supplied confidence factors — ``data_quality_flags_present``,
    ``source_independence_count``, ``is_heuristic_not_calibrated`` and
    ``depends_on_unobservable`` — while ``OutputGapInputs`` refused every one of
    them (``extra="forbid"``) and accepted only the two floats. A docstring that
    advertises an input surface the model rejects is a defect of the same class
    as a ``Literal`` with an unproducible member (D-045a): the documented
    contract and the enforced contract were two different promises.

    The audit's preferred remedy was to make the CODE the truth and rewrite the
    docstring, not to widen the model — because a pure two-float function
    *cannot* honestly report a caller's data-quality flag (it never sees the
    snapshot). So the pinned contract is deliberately the NARROW one:

      * the two floats are accepted;
      * each of the four formerly-documented factors is REFUSED.

    A future revision that either widens ``OutputGapInputs`` back to accept a
    quality factor, or trims the docstring's claim, must update this test —
    which is the point: the two halves cannot silently drift apart again.
    """
    # The accepted surface: exactly two floats, nothing else.
    assert set(OutputGapInputs.model_fields) == {"actual_gdp", "potential_gdp"}

    # The refused surface: every factor the old docstring promised is rejected
    # by the model, so the docstring's current (narrow) claim is the honest one.
    for rejected in (
        "data_quality_flags_present",
        "source_independence_count",
        "is_heuristic_not_calibrated",
        "depends_on_unobservable",
    ):
        with pytest.raises(ValueError, match="Extra inputs are not permitted"):
            OutputGapInputs(
                actual_gdp=21_000.0,
                potential_gdp=20_000.0,
                **{rejected: True},
            )


def test_output_gap_confidence_is_pinned_at_half_by_construction() -> None:
    """Every legal call publishes exactly 0.5 — the fact the docstring now states.

    The docstring's claim is specific and falsifiable: a pure two-float function
    supplies ``depends_on_unobservable=True`` and ``source_independence_count=0``
    and nothing else, so ``compute_confidence`` has one answer for every input
    pair. This asserts that constancy directly, rather than through the
    config-coincidence reasoning of the sibling test, so the "fixed by
    construction" sentence is backed by a check and not merely asserted in prose.

    Two different input pairs are used so the claim is shown to be
    input-INdependent: a positive gap (above potential) and a negative one
    (slack) must both land on 0.5.
    """
    above = output_gap(OutputGapInputs(actual_gdp=21_000.0, potential_gdp=20_000.0))
    slack = output_gap(OutputGapInputs(actual_gdp=19_000.0, potential_gdp=20_000.0))

    assert as_float(above) > 0 and as_float(slack) < 0, "the two cases must differ in sign"
    assert above.confidence == slack.confidence == 0.5


# ---------------------------------------------------------------------------
# Snapshot adapter — where O-7 is closed
# ---------------------------------------------------------------------------

# The live snapshot's shape, deliberately including BOTH defects this module
# guards against. Dates are relative to *today* so the fixture cannot go stale
# and silently stop exercising the future-dating filter.
#
# The three features that matter, all reproduced from the real 2026-09-16 build:
#
#   1. gdp_potential runs ONE QUARTER AHEAD of gdp_real (D-009). On the live
#      snapshot: latest GDPC1 = 2026-04-01, latest realised GDPPOT = 2026-07-01.
#      A naive "each series' own latest" read pairs those two.
#   2. gdp_potential carries a multi-year projection block (O-7): 41 of 62
#      points on the live snapshot were dated after retrieval.
#   3. The values are the real ones, so the hand-computed expectations in the
#      tests below are the same arithmetic a reader could do from FRED.
#
# Quarter arithmetic is done on (year, month) pairs, NOT by adding 91 days.
# A 91-day step drifts: four steps back from 2025-04-01 lands on 2024-07-02,
# and the resulting one-day misalignments make the two series' dates fail to
# intersect — which is the exact fault this fixture exists to detect, so
# introducing it into the fixture itself would be self-defeating.
_AS_OF = utc_now()


def _quarter_start(year: int, month: int, *, offset: int = 0) -> date:
    """The first day of the quarter ``offset`` quarters from (year, month).

    (2025, 4) with offset=+1 -> 2025-07-01.  (2025, 1) with offset=-1 -> 2024-10-01.
    """
    index = (year * 4 + (month - 1) // 3) + offset
    return date(index // 4, (index % 4) * 3 + 1, 1)


_ACTUAL_DATE = _quarter_start(_AS_OF.year - 1, 4)  # latest GDPC1 quarter
_POTENTIAL_DATE = _ACTUAL_DATE  # latest quarter where BOTH exist
_POTENTIAL_AHEAD_DATE = _quarter_start(_AS_OF.year - 1, 4, offset=1)  # GDPPOT head start
_FORWARD_DATE = _quarter_start(_AS_OF.year + 10, 10)
_QUARTER = "quarter"  # sentinel: use _quarter_start, never day arithmetic

# Live values, verbatim from the 2026-09-16 FRED fetch.
_GDP_REAL = [24_269.613, 24_180.419, 24_055.749, 24_026.834]  # 2026Q2 .. 2025Q3
_GDP_POTENTIAL_PAIRED = [
    24_070.9386484,
    23_945.1378387,
    23_811.2238968,
    23_680.1524766,
]  # same four quarters as _GDP_REAL
_GDP_POTENTIAL_AHEAD = 24_200.4446936  # 2026Q3 — no matching actual GDP print
_GDP_POTENTIAL_PROJECTIONS = [24_330.3745288, 24_460.7088379, 24_590.8094599, 24_720.7004814]


def _live_shaped_snapshot(**overrides: object) -> MacroDataSnapshot:
    """A snapshot shaped exactly like the real 2026-09-16 build.

    Real GDP has four realised quarters. Potential GDP has the same four
    realised quarters, **plus one more realised quarter** (the head start that
    produced D-009), **plus a projection block** a decade out (the condition
    O-7 describes).
    """
    actual = [
        ObservationPoint(
            observation_date=_quarter_start(_ACTUAL_DATE.year, _ACTUAL_DATE.month, offset=-k),
            value=v,
            series_id="gdp_real",
            retrieved_at=_AS_OF,
        )
        for k, v in enumerate(_GDP_REAL)
    ]
    potentials = [
        ObservationPoint(
            observation_date=_quarter_start(_POTENTIAL_DATE.year, _POTENTIAL_DATE.month, offset=-k),
            value=v,
            series_id="gdp_potential",
            retrieved_at=_AS_OF,
        )
        for k, v in enumerate(_GDP_POTENTIAL_PAIRED)
    ]
    potentials.append(
        ObservationPoint(
            observation_date=_POTENTIAL_AHEAD_DATE,
            value=_GDP_POTENTIAL_AHEAD,
            series_id="gdp_potential",
            retrieved_at=_AS_OF,
        )
    )
    potentials.extend(
        ObservationPoint(
            observation_date=_quarter_start(_FORWARD_DATE.year, _FORWARD_DATE.month, offset=k),
            value=v,
            series_id="gdp_potential",
            retrieved_at=_AS_OF,
        )
        for k, v in enumerate(_GDP_POTENTIAL_PROJECTIONS)
    )
    base: dict[str, object] = {
        "country": "us",
        "as_of": _AS_OF,
        "gdp_real": actual,
        "gdp_potential": potentials,
    }
    base.update(overrides)
    return make_snapshot(**base)


@pytest.mark.golden
def test_output_gap_from_snapshot_ignores_forward_projections() -> None:
    """O-7: the gap must be computed against realised capacity, not a 2036 projection.

    This is the test that would have failed before O-7 was closed. Without the
    filter, ``points[-1]`` picks a projection dated a decade out, and the gap
    becomes (24,269.613 - 34,600) / 34,600 * 100 = -29.86 — a number no
    economist would produce from this data, and one that looks entirely normal
    in a report.

    Hand computation with the filter applied:
        actual    = 24,269.613 @ 2026-04-01
        potential = 24,070.9386484 @ 2026-04-01   (same quarter, per D-009)
        gap       = (24269.613 - 24070.9386484) / 24070.9386484 * 100
                  = +0.8253... -> +0.83

    And the value the unfiltered read would have produced, for contrast:
        potential = 24,720.7004814 @ the last projection in the block
        "gap"     = (24269.613 - 24720.7004814) / 24720.7004814 * 100
                  = -1.8250... -> -1.83 at the wrong horizon entirely, and with
        the seven-quarter history (+1.52 ... +0.83) as the disconfirming evidence.
    """
    snapshot = _live_shaped_snapshot()
    result, report = output_gap_from_snapshot(snapshot)

    assert result.value == 0.83  # round(0.8253701881..., 2)
    assert report.potential_value == _GDP_POTENTIAL_PAIRED[0], (
        "the filter must select the realised, same-quarter potential value"
    )
    assert report.potential_date == _POTENTIAL_DATE.isoformat()

    # The projection block must be accounted for, not silently discarded.
    # 4 projections dated after as_of, plus 1 realised-but-unpaired quarter.
    # Reported separately (D-076): only the first is "forward-dated".
    assert report.withheld_forward_points == 4
    assert report.withheld_unpaired_points == 1
    assert report.withheld_potential_points == 5
    assert (
        report.withheld_horizon
        == _quarter_start(_FORWARD_DATE.year, _FORWARD_DATE.month, offset=3).isoformat()
    )


def test_output_gap_from_snapshot_warns_about_withheld_projections() -> None:
    """Step 5: the O-7 truncation warning path must fire."""
    _result, report = output_gap_from_snapshot(_live_shaped_snapshot())

    warnings = report.warnings()
    assert any("forward-dated CBO projection(s)" in w for w in warnings)
    assert any("withheld" in w for w in warnings)


def test_withheld_forward_points_counts_only_forward_dated_points() -> None:
    """D-076 REGRESSION — the forward-dated count must not absorb the unpaired one.

    Found by running the whole system end to end and comparing two numbers that
    were supposed to agree. The live thesis warned of

        "gdp_potential: 42 forward-dated CBO projection(s) to 2036-10-01 withheld"

    while an independent count of ``gdp_potential`` points dated after the
    snapshot's ``as_of`` was 41. Neither number was wrong in isolation; the
    *label* was. ``withheld_forward_points`` was defined as

        potential_series.withheld + withheld_unpaired

    which folds two categories with different meanings into one figure:

    * 41 points dated AFTER as_of — genuinely forward-dated CBO projections,
      excluded by the O-7 horizon filter; and
    * 1 point dated 2026-07-01, which is *on or before* as_of and is therefore
      NOT forward-dated at all. It is withheld only because the matching actual
      GDP quarter (2026-07-01) has not been published, so it cannot be paired
      (D-009). It is a completed quarter whose actual print is pending.

    Calling the second category a "projection" is the defect: it tells a reader
    that 42 of 62 points are future estimates when the true count is 41, and it
    makes the number irreconcilable with any direct count of the series.

    The two figures are therefore split, and this test pins both — plus the
    warning text, which must never describe a realised-but-pending quarter as a
    forward-dated projection.
    """
    snapshot = _live_shaped_snapshot()
    _result, report = output_gap_from_snapshot(snapshot)

    # The fixture carries 4 points dated after as_of and 1 realised point that
    # post-dates the paired quarter. They are two different things.
    assert report.withheld_forward_points == 4, (
        "withheld_forward_points must count ONLY points dated after as_of"
    )
    assert report.withheld_unpaired_points == 1, (
        "the realised-but-unpairable quarter is a separate category"
    )
    assert report.withheld_potential_points == 5, (
        "the total withheld from the potential series is the sum of the two"
    )

    warnings = report.warnings()
    forward = [w for w in warnings if "forward-dated" in w]
    assert len(forward) == 1
    assert "4 forward-dated" in forward[0], (
        f"the warning must report 4 forward-dated points, not 5; got: {forward[0]}"
    )
    assert "5 forward-dated" not in forward[0]


@pytest.mark.warning_path
def test_output_gap_from_snapshot_warns_when_potential_runs_ahead() -> None:
    """Step 5: potential GDP's one-quarter head start must be surfaced.

    ``GDPPOT`` is published one quarter ahead of ``GDPC1``. On a live
    2026-09-16 snapshot the latest realised potential estimate is Q3 2026 while
    the latest actual GDP print is Q2 2026. Pairing those two would measure a
    quarter of growth, not slack (D-009), so the point is withheld from the
    computation — and the fact that it was withheld, and why, belongs in the
    output rather than in a comment.
    """
    snapshot = _live_shaped_snapshot()
    result, report = output_gap_from_snapshot(snapshot)

    assert report.withheld_unpaired_points == 1
    assert report.staleness_quarters == 1
    assert report.potential_date == _POTENTIAL_DATE.isoformat()
    assert result.value == 0.83  # round(0.8253701881..., 2)
    assert any("extends 1 quarter(s) beyond" in w for w in report.warnings())
    assert any("growth rather than" in w for w in report.warnings())
    # The head start is one quarter — the normal publication lag — so the
    # narrower "stale fetch" warning must NOT fire. A warning that fires on the
    # ordinary case is noise, and noise is how real warnings get ignored.
    assert not any("wider than the normal one-quarter" in w for w in report.warnings())


def test_output_gap_pairs_the_same_quarter_never_each_series_own_latest() -> None:
    """D-009 REGRESSION — the pairing defect found by live execution.

    This is the test that would have caught the original bug, and it is written
    to encode the *wrong* answer explicitly so the failure mode is unmistakable
    rather than merely absent.

    Live 2026-09-16 data, unpaired (the defect):
        actual    = 24,269.613 @ 2026-04-01   (latest GDPC1)
        potential = 24,200.445 @ 2026-07-01   (latest realised GDPPOT)
        "gap"     = (24269.613 - 24200.4446936) / 24200.4446936 * 100
                  = +0.2858...  -> +0.29  "above potential"   <- WRONG

    Live 2026-09-16 data, same-quarter paired (the fix):
        actual    = 24,269.613 @ 2026-04-01
        potential = 24,070.9386484 @ 2026-04-01
        gap       = (24269.613 - 24070.9386484) / 24070.9386484 * 100
                  = 198.6743516 / 24070.9386484 * 100
                  = +0.8253...  -> +0.83

    The two answers differ in sign and in interpretation ("above potential" vs
    a smaller above-potential reading), and only the paired one is consistent
    with the seven-quarter history: +1.52, +1.35, +0.57, +0.95, +1.46, +1.03,
    +0.98, +0.83.

    Also asserted: the unpaired value is *not* what the function returns. Without
    that assertion, a future refactor could reintroduce the defect and the
    paired assertion alone might still pass on a coincidence.
    """
    snapshot = _live_shaped_snapshot()
    result, report = output_gap_from_snapshot(snapshot)

    # Hand-computed paired answer.
    assert result.value == 0.83  # round(0.8253701881..., 2)

    # Hand-computed UNPAIRED answer — must not be the result.
    unpaired = (24_269.613 - _GDP_POTENTIAL_AHEAD) / _GDP_POTENTIAL_AHEAD * 100
    assert unpaired == 0.2858141958783705, "hand-check the defect value"
    assert result.value != round(unpaired, 2), (
        "the function returned the unpaired answer — each series' own latest point was "
        "used instead of the latest common quarter (D-009)"
    )

    # Both series must be reported at the SAME date.
    assert report.actual_date == report.potential_date == _POTENTIAL_DATE.isoformat()


def test_output_gap_warns_when_the_actual_series_goes_stale() -> None:
    """Step 5: a wider-than-normal lag is a fetch problem, not a publication lag.

    The normal ``GDPPOT`` head start is one quarter. Two means the actual-GDP
    fetch is stale — a condition that must not be silently absorbed into a
    smaller sample. Here ``gdp_real`` stops two quarters before potential does,
    while still overlapping on a common date so the pairing itself succeeds and
    the *staleness* is what surfaces.
    """
    snapshot = _live_shaped_snapshot(
        gdp_real=[
            ObservationPoint(
                observation_date=_quarter_start(
                    _ACTUAL_DATE.year, _ACTUAL_DATE.month, offset=offset
                ),
                value=value,
                series_id="gdp_real",
                retrieved_at=_AS_OF,
            )
            # The two OLDEST quarters of the actual series are dropped, so it
            # stops at offset -1 (the quarter before the normal pair) while
            # potential's latest realised estimate is at offset +1. The lag is
            # therefore 2 quarters instead of the normal 1.
            #
            # The offset is a NAMED variable, not `-k`. Writing `offset=-k` over
            # `zip((-3, -2), ...)` yields offset +3 and +2 (dates in the FUTURE),
            # which silently produced an empty intersection and a hard failure
            # rather than the stale-fetch warning this test is for.
            for offset, value in zip((-1, -2), _GDP_REAL[-2:], strict=True)
        ]
    )
    _result, report = output_gap_from_snapshot(snapshot)

    assert report.staleness_quarters == 2
    assert report.actual_date == report.potential_date, (
        "the pair must still be same-quarter; staleness is a separate condition"
    )
    assert any("wider than the normal one-quarter" in w for w in report.warnings())

    assert report.staleness_quarters == 2
    assert any("wider than the normal one-quarter" in w for w in report.warnings())


def test_output_gap_reports_full_pair_in_context() -> None:
    """The output must carry both values and the pairing date, so a reader can audit it."""
    result, report = output_gap_from_snapshot(_live_shaped_snapshot())

    assert report.actual_date in result.context
    assert str(report.actual_value) in result.context
    assert str(report.potential_value) in result.context
    assert "same-quarter pair" in result.context


def test_output_gap_from_snapshot_refuses_an_all_future_dated_potential() -> None:
    """No realised value at all is an explicit failure, never a default.

    Section 21.4: the system must be able to say "I don't know". If every
    potential-GDP point is future-dated, there is no output gap — but a
    careless implementation might fall back to the first projection, or to
    zero, and produce a dramatic-looking -100%.
    """
    snapshot = _live_shaped_snapshot(
        gdp_potential=[
            ObservationPoint(
                observation_date=_FORWARD_DATE,
                value=34_000.0,
                series_id="gdp_potential",
                retrieved_at=_AS_OF,
            )
        ]
    )
    with pytest.raises(ValueError, match="no observations dated on or before"):
        output_gap_from_snapshot(snapshot)


def test_output_gap_from_snapshot_names_missing_series_rather_than_zeroing_it() -> None:
    """A missing series is named, not treated as zero."""
    with pytest.raises(ValueError, match="gdp_potential"):
        output_gap_from_snapshot(
            make_snapshot(country="us", as_of=_AS_OF, gdp_real=make_points([1.0], series_id="r"))
        )


def test_output_gap_from_snapshot_rejects_a_units_mismatch() -> None:
    """An order-of-magnitude divergence is a mapping fault, not a market state.

    Both series are declared in billions of chained dollars. If one were
    accidentally mapped to an index level (e.g. ~100) the ratio would be ~240x
    and the gap would read -99.6% — plausible-looking only until you notice it
    implies the economy is at 0.4% of capacity.
    """
    snapshot = _live_shaped_snapshot(
        gdp_potential=[
            ObservationPoint(
                observation_date=_POTENTIAL_DATE,
                value=100.0,
                series_id="gdp_potential",
                retrieved_at=_AS_OF,
            )
        ]
    )
    with pytest.raises(ValueError, match="order of magnitude"):
        output_gap_from_snapshot(snapshot)


def test_output_gap_from_snapshot_refuses_a_non_us_country() -> None:
    """Section 22.3 / Finding #3: no false genericity claim."""
    snapshot = make_snapshot(country="de", as_of=_AS_OF)
    with pytest.raises(NotImplementedError, match="country 'us' only"):
        output_gap_from_snapshot(snapshot)


def test_flagged_snapshot_lowers_the_computed_confidence() -> None:
    """Section 5.4 + 22.8: a flagged snapshot cannot report unflagged confidence.

    The arithmetic function sees two floats and cannot know the snapshot was
    flagged, so the adapter re-computes. Without this, a data-quality flag
    would have no effect on the confidence of a model that consumed flagged
    data — making the whole flag mechanism decorative.
    """
    clean_result, _ = output_gap_from_snapshot(_live_shaped_snapshot())
    flagged_result, _ = output_gap_from_snapshot(
        _live_shaped_snapshot(data_quality_flags=["[ERROR] gdp_real: VALUE_ABOVE_MAX — 999999"])
    )

    assert flagged_result.confidence < clean_result.confidence
    assert flagged_result.value == clean_result.value, "flags must not alter the arithmetic"
