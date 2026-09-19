"""Tests for Module 3 — ``classify_regime_rule_based``.

What is worth asserting here is **coverage**, because that is what the
specification gets wrong (D-045). The arithmetic is trivial — two threshold
comparisons — so every interesting test is about which cells of the grid are
reachable, whether the bands partition without a gap or an overlap, and whether
the sign conventions that decide the label point the right way.

Three findings shape this file:

1. **The specification can reach six of its nine declared states.**
   ``slowdown``, ``recovery`` and ``reflation`` are declared, carry distinct
   risk profiles in Section 15's ``FACTOR_REGIME_MAP``, and are consumed by
   ``sector_rotation_prior`` — but no point in the declared input plane produces
   them. The regression test enumerates a dense sweep of the plane and asserts
   all nine are reached, and a second test transcribes the specification's own
   logic and asserts it reaches only six. The second test is the load-bearing
   one: without it, "all nine reachable" could be satisfied by a correction that
   later drifts back.
2. **The specification's ``recession`` branch is too narrow.** A deep
   contraction with *rising* inflation fell through to ``early_expansion``.
   That specific input is pinned by name.
3. **``unemployment_gap`` was declared, listed in ``inputs_used``, and never
   read** — the D-037 inert-input class. It now corroborates the output gap, and
   because the two measures point in **opposite** directions the sign convention
   is pinned explicitly: getting it backwards produces a plausible
   ``CONTRADICTED`` verdict rather than an error.

Config leaves are patched to values the literal cannot produce, and the
synthetic leaves are **all distinct** so an accessor swap cannot hide (D-035).
"""

from __future__ import annotations

from contextlib import ExitStack
from itertools import product
from typing import get_args
from unittest.mock import patch

import pytest

from macro_engine.config import (
    CalibratedValue,
    RegimeBaseRates,
    RegimeRateValues,
    RegimeSettings,
    TrilemmaBaseRates,
    TrilemmaReferenceEpisode,
    TrilemmaSettings,
    get_settings,
)
from macro_engine.models.contracts import ConfidenceInputs, compute_confidence
from macro_engine.models.regime import (
    REGIME_STATES,
    GrowthAxis,
    InflationAxis,
    RegimeInputs,
    classify_regime_rule_based,
)
from tests.helpers import as_bool, as_float, as_str


def _leaf(value: float | int) -> CalibratedValue:
    """A synthetic config leaf whose value this test chose, distinct from every other."""
    return CalibratedValue(
        value=value,
        calibration_status="fitted_assumption",
        note="synthetic — chosen by this test to be distinct from every other leaf",
    )


#: Every synthetic leaf is a DIFFERENT number, so an accessor swap moves both
#: sides of any assertion that reads through the accessors (D-035). The values
#: are deliberately not the specification's literals, so a hardcoded copy of the
#: literal cannot satisfy a test that patches these.
_SYNTHETIC = RegimeSettings(
    recession_output_gap_max=_leaf(-2.0),
    weak_growth_output_gap_max=_leaf(-0.75),
    late_expansion_output_gap_min=_leaf(1.25),
    disinflation_output_gap_max=_leaf(0.6),
    neutral_inflation_trend_band_pp=_leaf(0.2),
    growth_momentum_band_pp=_leaf(0.35),
    # Distinct from every other leaf AND from the shipped 0.9375, so a property
    # that returns the shipped literal instead of reading the field is visible.
    measured_rising_inflation_rate=_leaf(0.775),
    base_rates=RegimeBaseRates(
        observations_measured_value=_leaf(0),
        rates=RegimeRateValues(
            early_expansion_value=_leaf(0.0),
            mid_expansion_value=_leaf(0.0),
            late_expansion_value=_leaf(0.0),
            slowdown_value=_leaf(0.0),
            recession_value=_leaf(0.0),
            recovery_value=_leaf(0.0),
            disinflation_value=_leaf(0.0),
            reflation_value=_leaf(0.0),
            stagflation_value=_leaf(0.0),
        ),
    ),
    # `RegimeSettings.trilemma` is required (D-048). It has to be supplied here
    # even though nothing in THIS file reads it, because the validator runs on
    # construction: a missing block raises before any assertion can be made.
    #
    # Worth noting how this was found. The two constructions near the bottom of
    # this file are wrapped in `pytest.raises(ValueError, match=...)`, and the
    # band/negative-half-width validators fire before pydantic reports the
    # missing field — so those tests PASSED while the model was unconstructible.
    # Only `mypy --strict` caught it. That is why the field is spelled out here
    # rather than left to a default.
    trilemma=TrilemmaSettings(
        reserves_depletion_threshold_3mo=_leaf(-0.05),
        reserves_break_threshold_1mo=_leaf(-0.03),
        confidence_penalty_for_manual_trilemma_booleans=_leaf(0.2),
        base_rates=TrilemmaBaseRates(
            observations_measured_value=_leaf(0),
            depletion_3mo_base_rate=_leaf(0.0),
            break_1mo_base_rate=_leaf(0.0),
        ),
        reference_episode=TrilemmaReferenceEpisode(
            country="gb",
            reserves_series="TRESEGGBM052N",
            event_date="1992-09-16",
            expected_severity="CRITICAL_PEG_STRESS",
            expected_month="1992-09",
        ),
    ),
)


class _PatchedSettings:
    """Context manager replacing ``get_settings().regime`` only.

    Only ``regime`` is swapped: the real ``confidence`` block is used, so a
    test asserting a confidence value is asserting the system's actual rule.

    This exists instead of a bare ``with patch(...)`` at each call site because
    the patch must target ``macro_engine.models.regime.get_settings`` — the
    name the model module bound at import time. Patching
    ``macro_engine.config.get_settings`` would leave the model looking at the
    real settings, and every assertion in this file would silently test the
    shipped config instead of the fixture. (A function-local
    ``from macro_engine.config import get_settings`` inside the model is
    invisible to either patch — that defect already cost this increment once.)
    """

    def __init__(self, regime: RegimeSettings) -> None:
        self._regime = regime
        self._stack = ExitStack()

    def __enter__(self) -> None:
        real = get_settings()
        patched = real.model_copy(update={"regime": self._regime})
        self._stack.enter_context(
            patch("macro_engine.models.regime.get_settings", return_value=patched)
        )

    def __exit__(self, *exc: object) -> None:
        self._stack.close()


def _inputs(
    *,
    output_gap: float = 0.0,
    inflation_yoy: float = 3.0,
    inflation_trend_3m: float = 0.0,
    unemployment_gap: float = 0.0,
    output_gap_change: float | None = None,
) -> RegimeInputs:
    return RegimeInputs(
        output_gap=output_gap,
        inflation_yoy=inflation_yoy,
        inflation_trend_3m=inflation_trend_3m,
        unemployment_gap=unemployment_gap,
        output_gap_change=output_gap_change,
    )


def _state(**kwargs: float | None) -> str:
    return as_str(classify_regime_rule_based(_inputs(**kwargs)), key="state")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 1. The specification's defect, pinned by name
# ---------------------------------------------------------------------------


def _specification_form(gap: float, trend: float) -> str:
    """Section 6.2's classifier, transcribed exactly, to pin what it reaches.

    Kept in the test file rather than in the source: the point is to assert a
    property of the *specification*, and if the specification is ever revised
    this transcription is what should change — not the shipped model.
    """
    if gap < -1.5 and trend < 0:
        return "recession"
    if gap < -0.5 and trend > 0:
        return "stagflation"
    if gap > 1.0 and trend > 0:
        return "late_expansion"
    if -0.5 <= gap <= 0.5 and trend < 0:
        return "disinflation"
    if gap > 0 and trend <= 0:
        return "mid_expansion"
    return "early_expansion"


def test_specification_form_cannot_reach_three_of_its_nine_states() -> None:
    """The specification declares nine states and its logic produces six.

    This is the claim the correction rests on, so it is asserted rather than
    described. If a future revision of the specification fixed its own logic,
    this test would fail and the correction could be re-justified on current
    text rather than on this record.
    """
    sweep = [
        _specification_form(gap / 4.0, trend / 4.0)
        for gap, trend in product(range(-24, 25), range(-32, 33))
    ]
    reached = set(sweep)
    assert reached == {
        "early_expansion",
        "mid_expansion",
        "late_expansion",
        "recession",
        "disinflation",
        "stagflation",
    }
    unreachable = set(REGIME_STATES) - reached
    assert unreachable == {"slowdown", "recovery", "reflation"}, (
        "the specification's unreachable set changed; the correction in "
        "models/regime.py was justified by exactly this set"
    )


def test_the_shipped_classifier_reaches_every_declared_state() -> None:
    """All nine states are reachable over the declared input plane.

    The sweep spans both axes well beyond every band, and includes a present
    and an absent ``output_gap_change``, because ``recovery`` is only reachable
    when the direction of the gap is supplied.
    """
    sweep = {
        _state(
            output_gap=gap / 4.0,
            inflation_trend_3m=trend / 4.0,
            unemployment_gap=-gap / 4.0,
            output_gap_change=change,
        )
        for gap, trend, change in product(range(-24, 25), range(-32, 33), (None, -0.5, 0.5))
    }
    missing = set(REGIME_STATES) - sweep
    assert not missing, f"these declared states are unreachable: {sorted(missing)}"


def test_every_returned_state_is_in_the_declared_vocabulary() -> None:
    """A state outside ``REGIME_STATES`` would break every downstream consumer.

    ``sector_rotation_prior`` and ``factor_tilt_prior`` both look the state up
    in a map and fall back to a generic answer on a miss — so an undeclared
    state degrades silently rather than raising.
    """
    sweep = {
        _state(
            output_gap=gap / 3.0,
            inflation_trend_3m=trend / 3.0,
            unemployment_gap=-gap / 3.0,
        )
        for gap, trend in product(range(-18, 19), range(-24, 25))
    }
    assert sweep <= set(REGIME_STATES)


# ---------------------------------------------------------------------------
# 2. The deep-contraction defect, pinned by name
# ---------------------------------------------------------------------------


def test_deep_contraction_with_rising_inflation_is_a_recession() -> None:
    """The sharpest single error in the specification, and a measure-zero branch.

    ``gap = -3.0`` with rising inflation: the specification's first branch
    requires falling inflation, its second requires ``gap < -0.5`` (satisfied)
    and rising inflation (satisfied) — so the specification returns
    ``stagflation``, not ``recession``. A 3% negative output gap with
    reaccelerating inflation is the 1974/1980 shape and it is not called a
    recession.

    The ``early_expansion`` branch is worse: it is reachable **only** when
    inflation momentum is *exactly* ``0.0``, because every other value is
    claimed by an earlier branch. So the state the specification falls back to
    is decided by a measure-zero set of inputs, and ``early_expansion`` — one of
    its six "reachable" states — is not reachable on any realistic reading.
    """
    assert _specification_form(-3.0, +1.0) == "stagflation"
    assert _specification_form(-6.0, -1.0) == "recession"
    # Exactly zero momentum is the ONLY way to reach the specification's else.
    assert _specification_form(-6.0, 0.0) == "early_expansion"
    with _PatchedSettings(_SYNTHETIC):
        assert _state(output_gap=-3.0, inflation_trend_3m=1.0) == "recession"
        assert _state(output_gap=-6.0, inflation_trend_3m=1.0) == "recession"


def test_specification_else_branch_is_its_slowdown_zone_mislabelled() -> None:
    """Pins exactly which inputs reach the specification's ``else``.

    Working the five predicates out by hand: the ``else`` receives

    * ``trend < 0`` and ``-1.5 <= gap < -0.5``,
    * ``trend == 0`` and ``gap <= 0``,
    * ``trend > 0`` and ``-0.5 <= gap <= 1.0``.

    The first is the important one. It is the *entire* "below trend but not a
    deep contraction" region with inflation falling — economically the textbook
    ``slowdown``/``recovery`` zone — and the specification labels all of it
    ``early_expansion``. That is why ``slowdown`` and ``recovery`` are
    unreachable: their economic territory is occupied by the fallthrough.

    The exactness matters. A dense float sweep is noisy at the boundaries; this
    enumerates a fine grid and asserts the region membership directly.
    """
    reached = {
        (gap / 4.0, trend / 4.0)
        for gap in range(-20, 21)
        for trend in range(-20, 21)
        if _specification_form(gap / 4.0, trend / 4.0) == "early_expansion"
    }
    assert (-1.25, -1.0) in reached, "the below-trend, disinflating zone is the else"
    assert (-1.0, -2.0) in reached
    assert (-0.25, 0.0) in reached
    assert (0.5, 1.0) in reached
    # And NOT this: a deep contraction with falling inflation IS a recession.
    assert (-2.0, -1.0) not in reached


def test_the_below_trend_disinflating_zone_is_the_slowdown_we_recover() -> None:
    """The correction: that same zone is ``slowdown``, or ``recovery`` when closing.

    The specification put ``-1.25`` gap with falling inflation in
    ``early_expansion``. It is below trend and not contracting, so it is a
    slowdown — and when the gap is closing, it is a recovery. Both readings come
    from the same cell, split only by the direction of the gap.
    """
    assert _specification_form(-1.25, -1.0) == "early_expansion"
    assert _state(output_gap=-1.25, inflation_trend_3m=-1.0) == "slowdown"
    assert _state(output_gap=-1.25, inflation_trend_3m=-1.0, output_gap_change=+0.5) == "recovery"


# ---------------------------------------------------------------------------
# 3. Each band boundary, built by ADDITION (D-029)
# ---------------------------------------------------------------------------

# With the synthetic config: recession < -2.0, weak < -0.75, disinflation <= 0.6,
# late >= 1.25, neutral momentum band 0.2, growth momentum band 0.35.


def test_growth_band_boundaries_are_exclusive_at_the_stated_edge() -> None:
    """``gap < recession`` is strict, so the boundary itself is NOT a recession.

    Built by addition from the synthetic -2.0 threshold: -2.0 is the edge and
    therefore contraction, -2.0001 is past it. Asserting the edge value is what
    distinguishes a strict comparison from a non-strict one.
    """
    with _PatchedSettings(_SYNTHETIC):
        assert _state(output_gap=-2.0, inflation_trend_3m=-1.0) == "slowdown"
        assert _state(output_gap=-2.0 - 0.0001, inflation_trend_3m=-1.0) == "recession"


def test_weak_growth_boundary_separates_slowdown_from_expansion() -> None:
    """``gap < weak_growth`` is strict: -0.75 is not contraction, -0.7501 is.

    The synthetic boundary is -0.75. A gap of -0.7501 is past it and is
    contraction, so with falling inflation it is ``slowdown``. Exactly -0.75 is
    NOT contraction — it is ``above_trend`` — and since its magnitude (0.75)
    exceeds the 0.35 momentum band it is ``disinflation``, not
    ``early_expansion``. Both readings differ by 0.0001, which is what
    demonstrates the comparison is strict rather than inclusive.
    """
    with _PatchedSettings(_SYNTHETIC):
        assert _state(output_gap=-0.7501, inflation_trend_3m=-1.0) == "slowdown"
        assert _state(output_gap=-0.7500, inflation_trend_3m=-1.0) == "disinflation"
        # A gap at the boundary whose magnitude is INSIDE the band is the
        # early_expansion case; the band is what confines that state.
        assert _state(output_gap=-0.75 + 0.4, inflation_trend_3m=-1.0) == "early_expansion"


def test_a_gap_beyond_the_momentum_band_does_not_return_early_expansion() -> None:
    """``early_expansion`` is confined to the near-trend band, by construction.

    A gap of ``-0.6`` is above the synthetic ``weak_growth`` boundary of -0.75
    (so not contraction) but *outside* the 0.35 momentum band, so with falling
    inflation it is ``disinflation`` — not an expansion state. The distinction
    matters because a naive implementation that tested only ``gap < 0`` would
    return ``early_expansion`` for any negative gap, however large, which is
    what made it a catch-all in the specification.
    """
    with _PatchedSettings(_SYNTHETIC):
        assert _state(output_gap=-0.6, inflation_trend_3m=-1.0) == "disinflation"
        # Inside the band and negative -> early_expansion, for contrast.
        assert _state(output_gap=-0.3, inflation_trend_3m=-1.0) == "early_expansion"


def test_neutral_inflation_band_is_closed_on_both_edges() -> None:
    """``abs(trend) <= band`` is inclusive, so the edge is FLAT, not rising.

    A closed band is what stops two adjacent buckets both rejecting a boundary
    value. With the synthetic band at 0.2, exactly +0.2 is flat and the smallest
    step above it is rising.
    """
    with _PatchedSettings(_SYNTHETIC):
        # gap = 0.0 -> above_trend, inside the growth band (0.35).
        assert _state(output_gap=0.0, inflation_trend_3m=0.2) == "mid_expansion"
        assert _state(output_gap=0.0, inflation_trend_3m=-0.2) == "mid_expansion"
        assert _state(output_gap=0.0, inflation_trend_3m=0.2 + 1e-9) == "reflation"


def test_growth_momentum_band_decides_which_side_of_above_trend() -> None:
    """Inside the band the state splits on the SIGN of the gap; outside it does not.

    Synthetic band 0.35: a gap of -0.34 is inside and below zero, so with
    falling inflation it is ``early_expansion``; a gap of +0.34 is inside and
    above zero, so ``mid_expansion``. Past the band, ``late_expansion`` /
    ``disinflation``.
    """
    with _PatchedSettings(_SYNTHETIC):
        assert _state(output_gap=-0.34, inflation_trend_3m=-1.0) == "early_expansion"
        assert _state(output_gap=+0.34, inflation_trend_3m=-1.0) == "mid_expansion"
        assert _state(output_gap=+0.35 + 1e-9, inflation_trend_3m=-1.0) == "disinflation"


# ---------------------------------------------------------------------------
# 4. The state grid, one cell at a time
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("gap", "trend", "change", "expected"),
    [
        # deep contraction -- all three inflation buckets
        (-3.0, -1.0, None, "recession"),
        (-3.0, 0.0, None, "recession"),
        (-3.0, +1.0, None, "recession"),
        # contraction -- rising is stagflation; the other two split on direction
        (-1.0, +1.0, None, "stagflation"),
        (-1.0, 0.0, None, "slowdown"),
        (-1.0, -1.0, None, "slowdown"),
        (-1.0, -1.0, +0.5, "recovery"),
        (-1.0, -1.0, -0.5, "slowdown"),
        (-1.0, +0.0, +0.5, "slowdown"),
        # above_trend, inside the band. The sign of the gap separates
        # early_expansion (below potential) from mid_expansion (above it) --
        # Section 6.2's own definition, which requires gap > 0 for
        # mid_expansion. A NEGATIVE gap that is not flat/rising is
        # early_expansion even when momentum is flat.
        (-0.2, -1.0, None, "early_expansion"),
        (-0.2, 0.0, None, "early_expansion"),
        (-0.2, +1.0, None, "reflation"),
        (+0.2, -1.0, None, "mid_expansion"),
        (+0.2, 0.0, None, "mid_expansion"),
        (+0.2, +1.0, None, "reflation"),
        # above_trend, past the band
        (+2.0, -1.0, None, "disinflation"),
        (+2.0, 0.0, None, "reflation"),
        (+2.0, +1.0, None, "late_expansion"),
    ],
)
def test_every_grid_cell_maps_to_the_stated_state(
    gap: float, trend: float, change: float | None, expected: str
) -> None:
    """The grid as a table, one row per cell, with the synthetic bands.

    Expectations are computed by hand from the grid in the module docstring,
    not read back from the code (Section 21.2 Step 4).
    """
    with _PatchedSettings(_SYNTHETIC):
        assert (
            _state(
                output_gap=gap,
                inflation_trend_3m=trend,
                output_gap_change=change,
            )
            == expected
        )


def test_recovery_requires_the_gap_to_be_closing() -> None:
    """``recovery`` and ``slowdown`` share a cell and are split on direction only.

    Three readings of the same cell — narrowing gap, widening gap, unknown
    direction — must give ``recovery``, ``slowdown``, ``slowdown``. The third is
    the important one: an absent direction is NOT treated as recovery, because a
    level cannot show a turning point.
    """
    kwargs = {"output_gap": -1.0, "inflation_trend_3m": -1.0}
    assert _state(**kwargs, output_gap_change=+0.01) == "recovery"
    assert _state(**kwargs, output_gap_change=0.0) == "slowdown"
    assert _state(**kwargs, output_gap_change=-0.01) == "slowdown"
    assert _state(**kwargs, output_gap_change=None) == "slowdown"


def test_recovery_is_not_produced_by_rising_inflation() -> None:
    """A narrowing gap with inflation accelerating is still stagflation.

    The direction of the gap must not override the inflation axis entirely:
    closing the gap while inflation reaccelerates is the stagflation case, and
    the specification's own pairing for it is kept.
    """
    assert _state(output_gap=-1.0, inflation_trend_3m=+1.0, output_gap_change=+0.5) == "stagflation"


# ---------------------------------------------------------------------------
# 5. The sign convention that decides the corroboration verdict
# ---------------------------------------------------------------------------


def test_slack_corroboration_pairs_the_measures_with_opposite_signs() -> None:
    """``output_gap < 0`` agrees with ``unemployment_gap > 0``.

    The two measures point in opposite directions: a negative output gap means
    below potential, a positive unemployment gap means slacker than u*. Getting
    this backwards turns a clean corroboration into a flat contradiction, and
    the wrong verdict is perfectly plausible rather than an exception — which is
    why it is pinned here and recomputed by the live check.
    """
    agree = classify_regime_rule_based(_inputs(output_gap=-2.0, unemployment_gap=+1.0))
    agree_above = classify_regime_rule_based(_inputs(output_gap=+2.0, unemployment_gap=-1.0))
    disagree = classify_regime_rule_based(_inputs(output_gap=-2.0, unemployment_gap=-1.0))

    assert as_bool(agree, key="slack_corroborated") is True
    assert as_bool(agree_above, key="slack_corroborated") is True
    assert as_bool(disagree, key="slack_corroborated") is False


def test_a_zero_gap_is_not_counted_as_corroboration() -> None:
    """``0.0`` carries no sign, so it cannot corroborate.

    A product-of-signs test would treat ``0.0 * x`` as agreement. The model
    reports the absence explicitly and warns that the rest of the reading is
    unsupported.

    **The signs of the non-zero partner are load-bearing, and this test was
    wrong before they were chosen deliberately.** Dropping the zero guard
    leaves ``(output_gap < 0.0) == (unemployment_gap > 0.0)``, which is not
    uniformly true for a zero reading — it depends on which side the *other*
    measure sits. Enumerating the four cases:

        gap=0.0, ugap=+2.0  shipped False, unguarded False   (indistinguishable)
        gap=0.0, ugap=-2.0  shipped False, unguarded True    (observable)
        gap=+2.0, ugap=0.0  shipped False, unguarded True    (observable)
        gap=-2.0, ugap=+0.0 shipped False, unguarded False   (indistinguishable)

    The original fixture used the first and fourth rows, so the mutation
    survived it — a survivor of D-035's "a fixture must make the mutation
    observable" kind. The pair below is chosen from rows two and three.
    """
    zero_output = classify_regime_rule_based(_inputs(output_gap=0.0, unemployment_gap=-2.0))
    zero_unemp = classify_regime_rule_based(_inputs(output_gap=+2.0, unemployment_gap=0.0))
    assert as_bool(zero_output, key="slack_corroborated") is False
    assert as_bool(zero_unemp, key="slack_corroborated") is False
    assert any("SLACK CORROBORATION ABSENT" in w for w in zero_output.warnings)
    assert any("SLACK CORROBORATION ABSENT" in w for w in zero_unemp.warnings)


def test_every_zero_reading_is_uncorroborated_whatever_the_partner_sign() -> None:
    """All four zero configurations, so no zero case can hide behind the other.

    The zero guard's replacement candidate — the bare sign comparison — returns
    ``True`` for exactly the readings where the zero sits on the negative-
    compatible side. Asserting all four pins the guard's whole domain rather
    than the two rows that happen to coincide with the unguarded behaviour.
    """
    zero_output_positive_ugap = _inputs(output_gap=0.0, unemployment_gap=+2.0)
    zero_output_negative_ugap = _inputs(output_gap=0.0, unemployment_gap=-2.0)
    zero_ugap_positive_gap = _inputs(output_gap=+2.0, unemployment_gap=0.0)
    zero_ugap_negative_gap = _inputs(output_gap=-2.0, unemployment_gap=0.0)

    for bad_inputs in (
        zero_output_positive_ugap,
        zero_output_negative_ugap,
        zero_ugap_positive_gap,
        zero_ugap_negative_gap,
    ):
        result = classify_regime_rule_based(bad_inputs)
        assert bad_inputs.slack_corroborated is False
        assert as_bool(result, key="slack_corroborated") is False, (
            f"a zero reading with output_gap={bad_inputs.output_gap:+.1f}, "
            f"unemployment_gap={bad_inputs.unemployment_gap:+.1f} was reported as "
            f"corroboration; a product-of-signs test counts it, the guard must not"
        )
        assert any("SLACK CORROBORATION ABSENT" in w for w in result.warnings)


def test_disagreement_is_disclosed_with_both_values() -> None:
    """Section 12's "divergence is information" must reach the output."""
    result = classify_regime_rule_based(_inputs(output_gap=-2.0, unemployment_gap=-1.0))
    combined = " ".join(result.warnings)
    assert "SLACK MEASURES DISAGREE" in combined
    assert "-2.00" in combined
    assert "-1.00" in combined


# ---------------------------------------------------------------------------
# 6. Confidence comes from the rule, not a literal (Section 22.8)
# ---------------------------------------------------------------------------


def test_confidence_is_computed_not_hardcoded() -> None:
    """The specification writes ``confidence=0.5``; Section 22.8 forbids it.

    Asserted against ``compute_confidence`` with the factors the model states,
    so a hardcoded literal would have to reproduce this exact number by
    coincidence.
    """
    result = classify_regime_rule_based(_inputs())
    expected = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=False,
            is_heuristic_not_calibrated=True,
            source_independence_count=0,
            depends_on_unobservable=True,
        )
    )
    assert result.confidence == expected
    assert result.confidence != 0.5, (
        "the specification's hardcoded 0.5 would satisfy a weaker test; this "
        "asserts the computed value differs from it"
    )


def test_data_quality_flags_lower_the_confidence() -> None:
    """A flagged input must cost confidence, which is the only reason to flag it."""
    clean = classify_regime_rule_based(_inputs())
    flagged = classify_regime_rule_based(
        RegimeInputs(
            output_gap=0.0,
            inflation_yoy=3.0,
            inflation_trend_3m=0.0,
            unemployment_gap=0.0,
            data_quality_flags_present=True,
        )
    )
    assert flagged.confidence < clean.confidence


def test_source_independence_is_zero_not_one() -> None:
    """Two surveys of one concept are not two independent families.

    Asserted by constructing the confidence the model *would* have claimed if it
    counted them as independent, and showing the shipped value is lower.
    """
    result = classify_regime_rule_based(_inputs())
    if_counted_as_independent = compute_confidence(
        ConfidenceInputs(
            is_heuristic_not_calibrated=True,
            source_independence_count=1,
            depends_on_unobservable=True,
        )
    )
    assert result.confidence < if_counted_as_independent


# ---------------------------------------------------------------------------
# 7. The base rate travels with the categorical (D-029)
# ---------------------------------------------------------------------------


def test_unmeasured_base_rate_is_reported_as_absent_not_zero() -> None:
    """``None`` means "not measured"; ``0.0`` would assert a measured zero.

    The registry ships ``observations_measured: 0`` until the live check records
    a window. A consumer must be able to tell the two apart, so the model
    publishes ``None`` and says so in a warning.

    **The shipped config no longer exercises this branch** — the base rates were
    measured on 2026-09-17 and ``observations_measured`` is now 240. The
    unmeasured path is therefore reached by patching, not by relying on the
    shipped default: a test that read it from config would silently start
    asserting the measured path once the config was populated, and would stop
    covering the branch it names.
    """
    unmeasured = _SYNTHETIC.model_copy(
        update={
            "base_rates": _SYNTHETIC.base_rates.model_copy(
                update={"observations_measured_value": _leaf(0)}
            )
        }
    )
    with _PatchedSettings(unmeasured):
        result = classify_regime_rule_based(_inputs())
    assert result.value is not None
    assert isinstance(result.value, dict)
    assert result.value["state_base_rate"] is None
    assert result.value["rising_inflation_base_rate"] is None
    assert any("NO BASE RATE AVAILABLE" in w for w in result.warnings)


def test_the_inflation_axis_base_rate_is_disclosed_and_read_from_config() -> None:
    """The axis base rate must travel with the label, and come from config.

    ``rising`` fires in 93.75% of the measured window, which makes every state
    needing a non-rising axis rare *by construction*. A reader looking at
    ``disinflation`` cannot tell that from an economic fact without the number,
    so it is published and warned.

    Read from config rather than hardcoded: the fixture's 0.775 is distinct from
    the shipped 0.9375, so a literal — or a swap of the accessor — is visible.
    """
    measured = _SYNTHETIC.model_copy(
        update={
            "base_rates": _SYNTHETIC.base_rates.model_copy(
                update={"observations_measured_value": _leaf(240)}
            )
        }
    )
    with _PatchedSettings(measured):
        result = classify_regime_rule_based(_inputs())
    assert result.value is not None
    assert isinstance(result.value, dict)
    assert as_float(result, key="rising_inflation_base_rate") == pytest.approx(0.775)
    combined = " ".join(result.warnings)
    assert "INFLATION-AXIS BASE RATE" in combined
    assert "77.5%" in combined, (
        "the warning must state the measured share it read from config; a "
        "hardcoded share would not follow the fixture"
    )


def test_measured_base_rate_is_published_for_the_state_returned() -> None:
    """With a measured window, the rate is looked up BY the state just produced.

    The synthetic map gives each state a different rate, so a lookup that
    returned the wrong state's rate — or a fixed one — fails.
    """
    distinct = {
        "early_expansion": 0.11,
        "mid_expansion": 0.22,
        "late_expansion": 0.33,
        "slowdown": 0.44,
        "recession": 0.55,
        "recovery": 0.66,
        "disinflation": 0.77,
        "reflation": 0.88,
        "stagflation": 0.99,
    }
    measured = _SYNTHETIC.model_copy(
        update={
            "base_rates": RegimeBaseRates(
                observations_measured_value=_leaf(120),
                rates=RegimeRateValues(
                    **{f"{name}_value": _leaf(rate) for name, rate in distinct.items()}
                ),
            )
        }
    )
    with _PatchedSettings(measured):
        result = classify_regime_rule_based(
            _inputs(output_gap=-1.0, inflation_trend_3m=-1.0)  # slowdown
        )
    state = as_str(result, key="state")
    rate = as_float(result, key="state_base_rate")
    assert state == "slowdown"
    assert rate == pytest.approx(distinct["slowdown"])
    assert any("occurred in 44.0%" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# 8. Disclosures
# ---------------------------------------------------------------------------


def test_momentum_not_level_is_disclosed() -> None:
    """The axis is a change, and the warning says so on every result.

    Without it a reader who assumes level semantics reads ``disinflation`` as
    "inflation is low" rather than "inflation is falling".
    """
    result = classify_regime_rule_based(_inputs())
    assert any("MOMENTUM" in w and "not the level" in w for w in result.warnings)


def test_flat_momentum_is_disclosed() -> None:
    """A flat reading means the inflation axis decided nothing."""
    result = classify_regime_rule_based(_inputs(output_gap=2.0, inflation_trend_3m=0.0))
    assert any("FLAT" in w and "growth axis alone" in w for w in result.warnings)


def test_at_trend_gap_is_disclosed() -> None:
    """Stability under revision is a property worth stating."""
    result = classify_regime_rule_based(_inputs(output_gap=0.05, inflation_trend_3m=1.0))
    assert any("AT TREND" in w for w in result.warnings)


def test_recession_carries_its_own_caveat() -> None:
    """A severe label from a revised, model-dependent gap must say so."""
    result = classify_regime_rule_based(_inputs(output_gap=-4.0, inflation_trend_3m=-1.0))
    assert result.value is not None and isinstance(result.value, dict)
    assert result.value["state"] == "recession"
    assert any("SEVERE LABEL" in w or "RECESSION is a severe label" in w for w in result.warnings)


def test_undecidable_recovery_is_disclosed() -> None:
    """The cell where recovery and slowdown coincide must explain itself."""
    result = classify_regime_rule_based(_inputs(output_gap=-1.0, inflation_trend_3m=-1.0))
    assert any("SLOWDOWN, NOT RECOVERY" in w for w in result.warnings)


def test_the_warning_list_is_never_empty() -> None:
    """Section 21.2: an untested warning path is an untested safety mechanism."""
    result = classify_regime_rule_based(_inputs())
    assert result.warnings


# ---------------------------------------------------------------------------
# 9. Contract
# ---------------------------------------------------------------------------


def test_the_two_axes_are_published_so_the_label_is_auditable() -> None:
    """Publishing only the state is not enough — the reader must see WHICH axis chose it.

    The state is a cell of a 2-D grid. Given the label alone, a reader cannot
    tell whether ``mid_expansion`` came from an above-trend gap with flat
    momentum or from an at-trend gap on the same axis, and those are materially
    different economies. The two bucketed axes are what make the label
    checkable. A mutation that dropped them from the published value survived
    an earlier version of this suite, which is why this test exists.
    """
    at_trend_flat = classify_regime_rule_based(_inputs(output_gap=0.2, inflation_trend_3m=0.0))
    above_trend_rising = classify_regime_rule_based(_inputs(output_gap=2.0, inflation_trend_3m=1.0))
    for result in (at_trend_flat, above_trend_rising):
        # as_str asserts the key exists and is a str, so a dropped axis fails
        # here rather than silently comparing None to None.
        growth = as_str(result, key="growth_axis")
        inflation = as_str(result, key="inflation_axis")
        assert growth in get_args(GrowthAxis)
        assert inflation in get_args(InflationAxis)
        assert "unknown" not in growth
        assert "unknown" not in inflation
    # And they genuinely differ, so the fields carry information rather than
    # being constants that happen to be strings. Note the GROWTH axes are
    # intentionally equal here: `above_trend` covers the near-trend strip as
    # well as full expansions, so the strip is not a separate bucket. What
    # separates these two readings is the inflation axis, which is exactly the
    # information the published pair is meant to carry.
    assert as_str(at_trend_flat, key="growth_axis") == as_str(above_trend_rising, key="growth_axis")
    assert as_str(at_trend_flat, key="inflation_axis") != as_str(
        above_trend_rising, key="inflation_axis"
    )


def test_the_growth_axis_has_no_at_trend_member() -> None:
    """A declared-but-unreachable axis member is the defect, not the contract.

    ``GrowthAxis`` previously included ``at_trend`` while ``_growth_axis`` never
    returned it — a published vocabulary advertising a value the function cannot
    produce. The near-trend strip is a sub-split of ``above_trend`` inside the
    state selection, not a fourth bucket, so the honest fix is to remove the
    member rather than to invent a branch that returns it. Pinned here so it
    cannot be re-added without the code to back it.
    """
    assert "at_trend" not in get_args(GrowthAxis)
    assert set(get_args(GrowthAxis)) == {"deep_contraction", "contraction", "above_trend"}


def test_every_growth_axis_member_is_reachable_and_the_boundary_belongs_to_the_upper_band() -> None:
    """Each declared member must be producible, and the boundary must be pinned.

    A vocabulary member nothing can produce is D-037's dead-branch class at the
    type level. The boundary assertions are the other half: ``_growth_axis`` uses
    strict ``<``, so a gap exactly on ``weak_growth_gap`` is ``above_trend``, not
    ``contraction``. Nothing else in the suite sits exactly on a configured
    threshold, so flipping the operator would otherwise be unobservable.
    """
    settings = get_settings().regime
    recession_max = float(settings.recession_output_gap_max.value)
    weak_max = float(settings.weak_growth_output_gap_max.value)

    # Every declared member is produced by some reading.
    produced = {
        as_str(
            classify_regime_rule_based(_inputs(output_gap=gap, inflation_trend_3m=1.0)),
            key="growth_axis",
        )
        for gap in (recession_max - 1.0, weak_max - 1.0, 5.0)
    }
    assert produced == set(get_args(GrowthAxis))

    # Exactly on each threshold: the upper band wins, so the partition is
    # half-open with no value falling through a gap between bands.
    assert (
        as_str(
            classify_regime_rule_based(_inputs(output_gap=recession_max, inflation_trend_3m=1.0)),
            key="growth_axis",
        )
        == "contraction"
    )
    assert (
        as_str(
            classify_regime_rule_based(_inputs(output_gap=weak_max, inflation_trend_3m=1.0)),
            key="growth_axis",
        )
        == "above_trend"
    )


def test_all_four_inputs_are_reported_as_used_and_all_are_actually_read() -> None:
    """Section 6.2 listed ``unemployment_gap`` and ``inflation_yoy`` and read neither.

    A field that is reported in ``inputs_used`` but never consulted is the
    D-037 defect class. This checks that changing each declared input can change
    the output — the only way to demonstrate an input is live.
    """
    result = classify_regime_rule_based(_inputs())
    assert set(result.inputs_used) == {
        "output_gap",
        "inflation_yoy",
        "inflation_trend_3m",
        "unemployment_gap",
    }
    # `unemployment_gap` is read (it drives the corroboration flag).
    moved_unemployment = classify_regime_rule_based(_inputs(output_gap=-2.0, unemployment_gap=-5.0))
    assert (
        moved_unemployment.value
        != classify_regime_rule_based(_inputs(output_gap=-2.0, unemployment_gap=+5.0)).value
    )
    # `inflation_yoy` is read (it is published and appears in the interpretation).
    assert "inflation_yoy_pct" in result.value  # type: ignore[operator]
    assert as_float(
        classify_regime_rule_based(_inputs(inflation_yoy=9.5)), key="inflation_yoy_pct"
    ) == pytest.approx(9.5)


def test_extra_fields_are_forbidden() -> None:
    """``extra="forbid"`` on every input model (Section 22.x)."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RegimeInputs(  # type: ignore[call-arg]
            output_gap=0.0,
            inflation_yoy=3.0,
            inflation_trend_3m=0.0,
            unemployment_gap=0.0,
            not_a_real_field=1.0,
        )


def test_country_is_us_and_as_of_is_timezone_aware() -> None:
    """Section 22.3: ``country`` is a label; naive datetimes are banned."""
    result = classify_regime_rule_based(_inputs())
    assert result.country == "us"
    assert result.as_of.tzinfo is not None


def test_config_bands_must_be_ordered() -> None:
    """An inverted band order makes a state unreachable by position, silently.

    Each rule is a self-contained comparison, so inverting two bands raises
    nothing — the branches simply overlap and one state disappears. The
    validator turns that into a startup error.
    """
    with pytest.raises(ValueError, match="not strictly ordered"):
        RegimeSettings(
            recession_output_gap_max=_leaf(-0.5),
            weak_growth_output_gap_max=_leaf(-1.5),
            late_expansion_output_gap_min=_leaf(1.0),
            disinflation_output_gap_max=_leaf(0.5),
            neutral_inflation_trend_band_pp=_leaf(0.1),
            growth_momentum_band_pp=_leaf(0.25),
            measured_rising_inflation_rate=_leaf(0.775),
            base_rates=_SYNTHETIC.base_rates,
            trilemma=_SYNTHETIC.trilemma,
        )


def test_negative_half_width_band_is_rejected() -> None:
    """``abs(x) <= negative`` is never true, so the branch silently vanishes."""
    with pytest.raises(ValueError, match="must not be negative"):
        RegimeSettings(
            recession_output_gap_max=_leaf(-1.5),
            weak_growth_output_gap_max=_leaf(-0.5),
            late_expansion_output_gap_min=_leaf(1.0),
            disinflation_output_gap_max=_leaf(0.5),
            neutral_inflation_trend_band_pp=_leaf(0.1),
            growth_momentum_band_pp=_leaf(-0.25),
            measured_rising_inflation_rate=_leaf(0.775),
            base_rates=_SYNTHETIC.base_rates,
            trilemma=_SYNTHETIC.trilemma,
        )


def test_regime_states_tuple_and_literal_agree() -> None:
    """``REGIME_STATES`` and the ``RegimeState`` Literal must not drift.

    Pydantic's ``Literal`` is not iterable at runtime, so the vocabulary is
    declared twice and the two declarations are compared here.
    """
    from typing import get_args

    from macro_engine.models.regime import RegimeState

    assert set(get_args(RegimeState)) == set(REGIME_STATES)
    assert len(REGIME_STATES) == 9
