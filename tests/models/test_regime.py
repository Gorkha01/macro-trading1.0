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

import json
from contextlib import ExitStack
from itertools import product
from typing import Any, cast, get_args
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from macro_engine.config import (
    CalibratedValue,
    MarkovRegimeSettings,
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
    MARKOV_REGIME_ORDERING_RULE,
    MARKOV_TRANSITION_ORIENTATION,
    REGIME_STATES,
    REGIME_TENSIONS,
    GrowthAxis,
    InflationAxis,
    RegimeInputs,
    RegimeTension,
    _canonical_regime_order,
    _canonicalise_fit,
    classify_regime_markov_switching,
    classify_regime_rule_based,
    regime_tension,
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
    # `RegimeSettings.markov` is required for the same reason `trilemma` is, and
    # the SAME defect class recurred when it was added: three explicit
    # `RegimeSettings(...)` constructions in this file became unconstructible,
    # every one of the `pytest.raises(ValueError, ...)` tests still PASSED
    # (the band validators fire before pydantic reports the missing field), and
    # only `mypy --strict` caught it. The values are synthetic and distinct from
    # the shipped ones so a property returning a shipped literal is visible.
    markov=MarkovRegimeSettings(
        max_regimes_value=_leaf(5),
        min_observations_per_parameter_value=_leaf(4.0),
        max_iterations_value=_leaf(150),
        em_iterations_value=_leaf(4),
        search_reps_value=_leaf(0),
        modal_share_warning_threshold_value=_leaf(0.85),
        switching_variance=True,
        markov_trend="c",
        markov_optimizer="bfgs",
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
            markov=_SYNTHETIC.markov,
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
            markov=_SYNTHETIC.markov,
        )


def test_regime_states_tuple_and_literal_agree() -> None:
    """``REGIME_STATES`` and the ``RegimeState`` Literal must not drift.

    Pydantic's ``Literal`` is not iterable at runtime, so the vocabulary is
    declared twice and the two declarations are compared here.
    """
    from macro_engine.models.regime import RegimeState

    assert set(get_args(RegimeState)) == set(REGIME_STATES)
    assert len(REGIME_STATES) == 9


# ---------------------------------------------------------------------------
# Section 21 of the economic-integrity directive: the regime must not be a
# single-factor switch, and a one-axis label must be flagged REGIME_TENSION.
# ---------------------------------------------------------------------------


class TestRegimeTension:
    """§21 — a label decided by one axis is published as ``REGIME_TENSION``.

    The classifier has always read two axes. The §21 requirement is about the
    case where one of them **did not distinguish anything**: a flat inflation
    momentum inside the neutral band, or a deep contraction where the
    classifier consults the inflation axis not at all. In both cases the label
    is single-axis, and a consumer must be able to tell.
    """

    def test_a_flat_inflation_axis_flags_tension(self) -> None:
        """Inside the neutral band, the growth axis decides alone."""
        with _PatchedSettings(RegimeSettings(**_SYNTHETIC.model_dump())):
            result = classify_regime_rule_based(_inputs(output_gap=0.83, inflation_trend_3m=0.05))
        value = result.value
        assert isinstance(value, dict)
        assert value["regime_tension"] == "REGIME_TENSION"
        reasons = value["regime_tension_reasons"]
        assert isinstance(reasons, list)
        assert any("neutral band" in r for r in reasons), reasons

    def test_a_two_sided_inflation_axis_is_not_tension(self) -> None:
        """Outside the band, both axes contributed — the falsifiable half.

        Without this the flag could be a constant ``REGIME_TENSION`` and the
        first test would still pass.
        """
        with _PatchedSettings(RegimeSettings(**_SYNTHETIC.model_dump())):
            result = classify_regime_rule_based(_inputs(output_gap=0.83, inflation_trend_3m=0.5))
        value = result.value
        assert isinstance(value, dict)
        assert value["regime_tension"] == "NO_REGIME_TENSION"
        assert value["regime_tension_reasons"] == []

    def test_a_deep_contraction_flags_tension_whatever_the_inflation_axis(self) -> None:
        """Depth beats direction by design — so the inflation axis was unused.

        ``_select_state`` returns ``recession`` for ``deep_contraction`` without
        consulting inflation. A two-sided momentum reading therefore does NOT
        make this a two-axis classification, and the flag says so.
        """
        with _PatchedSettings(RegimeSettings(**_SYNTHETIC.model_dump())):
            result = classify_regime_rule_based(_inputs(output_gap=-3.0, inflation_trend_3m=0.9))
        value = result.value
        assert isinstance(value, dict)
        assert value["regime_tension"] == "REGIME_TENSION"
        reasons = value["regime_tension_reasons"]
        assert isinstance(reasons, list)
        assert any("deep_contraction" in r for r in reasons), reasons

    def test_the_band_edge_is_flat_matching_the_inflation_axis_boundary(self) -> None:
        """The ``<=`` test matches ``_inflation_axis``'s own boundary.

        If the two disagreed about whether a reading was neutral, the flag and
        the axis could contradict each other on the same number.
        """
        with _PatchedSettings(RegimeSettings(**_SYNTHETIC.model_dump())):
            at_edge = classify_regime_rule_based(
                _inputs(output_gap=0.83, inflation_trend_3m=0.2)  # == neutral band
            )
        value = at_edge.value
        assert isinstance(value, dict)
        assert value["inflation_axis"] == "flat"
        assert value["regime_tension"] == "REGIME_TENSION"

    def test_tension_rides_along_as_a_warning_too(self) -> None:
        """The structured flag and the prose warning cannot diverge."""
        with _PatchedSettings(RegimeSettings(**_SYNTHETIC.model_dump())):
            result = classify_regime_rule_based(_inputs(output_gap=0.83, inflation_trend_3m=0.05))
        assert any("REGIME_TENSION" in w for w in result.warnings), result.warnings

    def test_the_tension_vocabulary_and_literal_agree(self) -> None:
        """``REGIME_TENSIONS`` and the ``RegimeTension`` Literal must not drift."""
        assert set(get_args(RegimeTension)) == set(REGIME_TENSIONS)
        assert len(REGIME_TENSIONS) == 2

    def test_the_helper_is_pure_and_matches_the_classifier(self) -> None:
        """The published flag comes from ``regime_tension()``, not a re-derivation.

        Called directly with the classifier's own axes and band, the helper must
        return what the classifier published — so a future edit to one cannot
        silently diverge from the other.
        """
        with _PatchedSettings(RegimeSettings(**_SYNTHETIC.model_dump())):
            result = classify_regime_rule_based(_inputs(output_gap=0.83, inflation_trend_3m=0.05))
        value = result.value
        assert isinstance(value, dict)
        # The classifier publishes these as plain strings inside a dict, so they
        # must be narrowed back to the Literal the helper accepts. Validated by
        # membership FIRST, then cast — the assert is what makes the cast
        # honest, so a classifier that started emitting an unknown axis fails
        # here rather than being silently coerced into the helper's domain.
        growth = as_str(result, key="growth_axis")
        inflation = as_str(result, key="inflation_axis")
        assert growth in get_args(GrowthAxis), growth
        assert inflation in get_args(InflationAxis), inflation
        expected, _ = regime_tension(
            cast("GrowthAxis", growth),
            cast("InflationAxis", inflation),
            inflation_trend_3m=as_float(result, key="inflation_trend_3m_pp"),
            neutral_band=0.2,  # the patched neutral band
        )
        assert value["regime_tension"] == expected


# =============================================================================
# Module 3 (Phase 5+) — classify_regime_markov_switching (Section 6.2)
# =============================================================================
#
# What is worth asserting here is not the arithmetic — the arithmetic belongs to
# statsmodels — but the FOUR things this function exists to correct, each of
# which the library gets right *for a different purpose* and wrong for this one:
#
# 1. **The regime index is not identified.** The library numbers regimes by its
#    EM starting values; measured 2026-09-24, one fixed series at
#    `search_reps=10` put the HIGH-mean regime at index 1 for 4 of 12 seeds and
#    the MIDDLE-mean regime there for the other 8. The canonical ordering is the
#    fix, and the invariance test below is the proof: a label switch is exactly a
#    permutation of the library's index, so permuting the inputs must leave every
#    canonical output bit-identical while the RAW order changes.
# 2. **The transition matrix is column-stochastic.** The library documents
#    element (i,j) as P(from j to i). The published matrix is the transpose and
#    the orientation is stated; both are asserted.
# 3. **The smoothed path is retrospective.** `|smoothed - filtered|` is positive
#    somewhere in the sample and exactly 0 at the endpoint; the current read is
#    taken from the filtered path. Asserted as an identity, not a comment.
# 4. **`converged=False` is not evidence of a bad fit.** Measured here on the
#    module's own series: at `max_iterations=50` the flag is False while the
#    log-likelihood is within 0.32 of the converged value. The test pins that
#    gap, so the warning's claim is measured rather than asserted.
#
# Every guard has a NEGATIVE CONTROL beside it — the input the guard must ACCEPT
# — because a guard that refuses everything passes its own test. That matters
# most for the no-variation guard, whose tolerance is fully RELATIVE: the
# control is a series that moves a thousandth as much and must still be fitted.

_MARKOV_N = 120
_MARKOV_SEED = 20260924
_MARKOV_TRUE_MEANS = (-2.0, 0.0, 2.0)

#: Mutually non-colliding markers, one per warning branch (D-052's partition rule).
_MARKOV_WARNING_MARKERS: tuple[str, ...] = (
    "STATISTICAL DECOMPOSITION, NOT A CAUSAL CLAIM",
    "CHOSEN BY THE CALLER",
    "REGIME ORDERING:",
    "THE SMOOTHED PATH IS RETROSPECTIVE",
    "THE HARD LABEL IS DERIVED",
    "BASE RATE:",
    "BASE STATE:",
    "THE LIBRARY RAISED",
    "THE OPTIMIZER REPORTED NON-CONVERGENCE",
)


def _markov_series(n: int = _MARKOV_N, seed: int = _MARKOV_SEED) -> pd.Series:
    """A three-regime series with KNOWN means, on a quarterly index.

    Built from the true means so a test can assert recovery rather than merely
    that some number came back, and seeded so every assertion is reproducible.
    """
    rng = np.random.default_rng(seed)
    labels = np.repeat(np.arange(3), int(np.ceil(n / 3)))[:n]
    values = np.array(_MARKOV_TRUE_MEANS)[labels] + rng.normal(0.0, 0.35, n)
    return pd.Series(values, index=pd.date_range("1980-01-01", periods=n, freq="QS"))


def _markov_config(**leaf_updates: Any) -> MarkovRegimeSettings:
    """The shipped markov block with named leaves replaced by this test's values."""
    real = get_settings().regime.markov
    return MarkovRegimeSettings(**{**real.model_dump(), **leaf_updates})


def _with_markov(**leaf_updates: Any) -> _PatchedSettings:
    """Patch ONLY the `regime.markov` block, leaving confidence real."""
    real = get_settings().regime
    return _PatchedSettings(real.model_copy(update={"markov": _markov_config(**leaf_updates)}))


def _markov_leaf(value: float) -> CalibratedValue:
    return CalibratedValue(
        value=value,
        calibration_status="fitted_assumption",
        note="synthetic — moved by a test so a literal cannot produce the same answer",
    )


def _markov_value(result: Any) -> dict[str, Any]:
    """Narrow `ModelResult.value` to the dict this function publishes.

    `ModelResult.value` is a broad union by design (Section 22.9), so mypy cannot
    index it. The `assert` is what makes the annotation honest rather than a cast:
    a function that started returning a bare float fails here, loudly.
    """
    value = result.value
    assert isinstance(value, dict), f"expected a dict value, got {type(value).__name__}"
    return cast("dict[str, Any]", value)


@pytest.fixture(scope="module")
def markov_result() -> Any:
    """ONE fit, shared by the read-only assertions.

    Module-scoped deliberately: a fit costs ~1.7 s and most of what follows reads
    the result rather than producing a new one. The mutation sweep restarts
    pytest per mutant, so the fixture is rebuilt under every mutation — sharing it
    cannot hide a change in behaviour.
    """
    return classify_regime_markov_switching(_markov_series())


# --- 1. the canonical ordering (the increment's mechanism) -------------------


def test_markov_canonicalisation_is_invariant_under_a_label_switch() -> None:
    """THE PROOF: permuting the library's index must not move any published value.

    A label switch IS a permutation of the library's regime index — that is what
    the measured 4-of-12 / 8-of-12 split produces. So this drives the exact
    operation: the same fit, with every regime-keyed array re-indexed by a
    permutation, and every canonical output asserted bit-identical.

    The last assertion is the one that makes it a proof rather than a tautology:
    the RAW orderings must DIFFER, or the permutation changed nothing and the
    invariance was free.
    """
    constants = np.array([2.5, 0.0, 1.0])
    smoothed = np.array([[0.10, 0.70, 0.20], [0.60, 0.30, 0.10]])
    filtered = np.array([[0.20, 0.60, 0.20], [0.50, 0.40, 0.10]])
    transition = np.array([[0.8, 0.1, 0.1], [0.2, 0.7, 0.1], [0.1, 0.2, 0.7]])
    durations = np.array([5.0, 3.3333, 3.3333])

    straight = _canonicalise_fit(constants, smoothed, filtered, transition, durations)
    perm = [2, 0, 1]
    switched = _canonicalise_fit(
        constants[perm],
        smoothed[:, perm],
        filtered[:, perm],
        transition[np.ix_(perm, perm)],
        durations[perm],
    )

    assert straight.order != switched.order, (
        "the permutation did not change the raw ordering, so the invariance below "
        "is vacuous — pick a permutation that actually moves a regime"
    )
    assert np.array_equal(straight.means, switched.means)
    assert np.array_equal(straight.smoothed, switched.smoothed)
    assert np.array_equal(straight.filtered, switched.filtered)
    assert np.array_equal(straight.transition, switched.transition)
    assert np.array_equal(straight.durations, switched.durations)
    # The canonical means are the SORTED raw means, which is the rule itself.
    assert np.array_equal(straight.means, np.sort(constants))


def test_markov_ordering_puts_the_means_in_ascending_order() -> None:
    order = _canonical_regime_order(np.array([2.5, -1.0, 0.5]))
    assert order == [1, 2, 0]
    means = np.array([2.5, -1.0, 0.5])[order]
    assert list(means) == sorted(means)


def test_markov_ordering_ties_keep_the_library_index_order() -> None:
    """The tiebreak is `kind='stable'`, and it is what makes the order deterministic.

    Two regimes with equal estimated means are indistinguishable by the ordering
    rule; a non-stable sort would order them by whatever the algorithm happened to
    do, so the published permutation could differ between two runs of identical
    input. The stable sort keeps the library's index order instead.

    The 12-entry fixture is not decoration. MEASURED 2026-09-24: at 3, 4 and 6
    tied entries numpy's `quicksort` and `heapsort` return the SAME permutation as
    `stable`, so a small fixture cannot distinguish them and the `kind=` argument
    would be untested — this is 5y's "a grid must be fine enough to land off the
    boundary", in the sort-stability dimension. The first size that separates them
    is 12.
    """
    assert _canonical_regime_order(np.array([1.0, 1.0, 0.0])) == [2, 0, 1]
    assert _canonical_regime_order(np.array([0.0, 1.0, 1.0])) == [0, 1, 2]

    # Six regimes tied at 1.0 alternating with six tied at 0.0. The stable sort
    # preserves index order within each tied run.
    tied = np.zeros(12)
    tied[::2] = 1.0
    assert _canonical_regime_order(tied) == [1, 3, 5, 7, 9, 11, 0, 2, 4, 6, 8, 10]
    # The discriminating claim, asserted rather than assumed: a non-stable sort
    # returns something else at this size.
    assert list(np.argsort(tied, kind="quicksort")) != _canonical_regime_order(tied)


def test_markov_published_means_are_ascending_and_the_permutation_explains_them(
    markov_result: Any,
) -> None:
    """End to end: the published ordering must be checkable from the output alone.

    The last assertion is the load-bearing one. Checking that the means are
    sorted and that the permutation is a permutation is NOT enough: a
    permutation published beside an unrelated sorted list satisfies both. The
    raw means are published precisely so the two can be tied together.
    """
    value = _markov_value(markov_result)
    assert isinstance(value, dict)
    means = value["regime_means"]
    order = value["regime_order_raw_index"]
    raw = value["regime_means_raw_index"]
    assert means == sorted(means), f"means are not ascending: {means}"
    assert sorted(order) == list(range(value["k_regimes"])), (
        f"regime_order_raw_index is not a permutation: {order}"
    )
    assert means == [raw[i] for i in order], (
        f"the published permutation does not map the RAW means onto the published ones: "
        f"means={means}, raw={raw}, order={order}"
    )
    assert value["regime_ordering_rule"] == MARKOV_REGIME_ORDERING_RULE


# --- 2. the transition matrix orientation ------------------------------------


def test_markov_transition_matrix_is_published_row_stochastic(markov_result: Any) -> None:
    """Rows sum to 1 — the OPPOSITE of the library's own orientation.

    The library's `regime_transition[i, j]` is P(from j to i), so its COLUMNS sum
    to one. Asserting the row sums is what distinguishes the published matrix
    from a verbatim copy of the library's, and asserting the COLUMN sums differ
    from 1 is what proves the transpose actually happened.
    """
    value = _markov_value(markov_result)
    matrix = value["transition_matrix"]
    rows = [sum(row) for row in matrix]
    assert rows == pytest.approx([1.0] * value["k_regimes"], rel=1e-12), rows
    columns = [
        sum(matrix[i][j] for i in range(value["k_regimes"])) for j in range(value["k_regimes"])
    ]
    assert any(abs(c - 1.0) > 1e-6 for c in columns), (
        f"the columns also sum to 1 ({columns}), so the transpose was a no-op and the "
        f"orientation claim is untested"
    )
    assert value["transition_matrix_orientation"] == MARKOV_TRANSITION_ORIENTATION
    assert "row_stochastic" in MARKOV_TRANSITION_ORIENTATION


def test_markov_expected_durations_match_the_transition_diagonal(markov_result: Any) -> None:
    """`1 / (1 - p_ii)`, recomputed from the PUBLISHED matrix.

    Recomputing from the published matrix rather than from the library's own
    `expected_durations` is the point: it checks the two published quantities
    against each other, so a re-indexing applied to one and not the other fails.
    """
    value = _markov_value(markov_result)
    matrix = value["transition_matrix"]
    recomputed = [1.0 / (1.0 - matrix[i][i]) for i in range(value["k_regimes"])]
    # Exact to floating-point noise, because neither side is rounded: rounding the
    # matrix would break this identity by 1/(1-p)^2 per 1e-6 of p.
    assert value["expected_durations"] == pytest.approx(recomputed, rel=1e-12)


# --- 3. the look-ahead in the smoothed path ----------------------------------


def test_markov_current_read_is_the_filtered_endpoint_and_equals_the_smoothed_one(
    markov_result: Any,
) -> None:
    """The current read is the FINAL observation, where the two paths must coincide.

    The equality is asserted EXACTLY rather than approximately, because it is the
    fact that licenses taking the real-time read from either path at the endpoint
    while the *history* must come from the filtered one. It is also the reason a
    mutation swapping the two is **construction-inert** — the two forms are the
    same program at ``t = T`` — so this test is the tripwire that makes a change
    in the library's smoothing (which would separate them) loud instead of silent.
    See D-105.
    """
    value = _markov_value(markov_result)
    current = value["current_probabilities"]
    assert current == value["smoothed_probabilities"][-1], (
        "the current read and the final smoothed row differ, so the choice between the "
        "filtered and smoothed paths at the endpoint is now load-bearing and the "
        "construction-inert argument for it no longer holds"
    )
    assert sum(current) == pytest.approx(1.0, rel=1e-12)
    assert value["current_regime"] == int(np.argmax(current))
    assert value["current_regime_probability"] == current[value["current_regime"]]


def test_markov_look_ahead_gap_is_measured_and_positive_historically(markov_result: Any) -> None:
    """The published gap must be a real measurement, not a decorative zero.

    If the function silently published the filtered path under the smoothed name,
    the gap would be 0.0 and the retrospective warning would be false.
    """
    value = _markov_value(markov_result)
    assert value["max_smoothed_filtered_gap"] > 0.0, (
        "the smoothed and filtered paths never differ, which cannot be true of a "
        "smoothed path that is revised by later observations"
    )
    assert value["max_smoothed_filtered_gap"] <= 1.0


# --- 4. the guards, each with its negative control ---------------------------


def test_markov_refuses_a_non_series_and_accepts_a_series() -> None:
    with pytest.raises(TypeError, match="must be a pandas Series"):
        classify_regime_markov_switching(pd.DataFrame({"x": _markov_series()}))  # type: ignore[arg-type]
    # NEGATIVE CONTROL: the accepted shape really is accepted.
    assert _markov_value(classify_regime_markov_switching(_markov_series()))["periods"] == _MARKOV_N


def test_markov_refuses_a_non_finite_series() -> None:
    broken = _markov_series()
    broken.iloc[7] = float("nan")
    with pytest.raises(ValueError, match="non-finite"):
        classify_regime_markov_switching(broken)
    infinite = _markov_series()
    infinite.iloc[3] = float("inf")
    with pytest.raises(ValueError, match="non-finite"):
        classify_regime_markov_switching(infinite)


def test_markov_refuses_a_constant_series() -> None:
    with pytest.raises(ValueError, match="no variation"):
        classify_regime_markov_switching(pd.Series([2.0] * _MARKOV_N))


def test_markov_accepts_a_series_that_moves_at_a_tiny_scale() -> None:
    """NEGATIVE CONTROL for the no-variation guard — and the reason it is RELATIVE.

    An absolute guard (`max - min <= eps`) would refuse this series, which moves
    perfectly well; it is only small. That is D-100/O-121's defect — an
    effectively-absolute tolerance below scale 1 — and this is the case that
    distinguishes the two.
    """
    tiny = _markov_series() * 1e-9
    assert float(tiny.max() - tiny.min()) < 1e-8  # an ABSOLUTE guard would refuse it
    result = classify_regime_markov_switching(tiny)
    assert _markov_value(result)["periods"] == _MARKOV_N


def test_markov_refuses_a_large_series_whose_variation_is_only_float_noise() -> None:
    """The OTHER half of the divergence, and the half that actually discriminates.

    The tiny-scale test above shows the guard is not absolute on the small side —
    but MEASURED 2026-09-24, an absolute guard and a relative one give the SAME
    verdict there (both accept: the span is `5.9e-09`, far above the absolute
    threshold), so that fixture lies OUTSIDE the region where the two disagree
    and a mutation making the guard absolute SURVIVES it. This is the project's
    recurring lesson (M74, M108): **a relative guard needs a divergent case lying
    inside the divergence.**

    The divergent region is large magnitude with small RELATIVE variation. At
    `1e10` with a `1e-4` span the absolute span is `9.918e-05` — 52 double-precision
    ULPs at that magnitude, so the series genuinely moves — while the relative
    span is `9.918e-15`, below the `2.22e-14` threshold. The relative guard
    refuses it; an absolute one would accept it and hand the fit a likelihood
    dominated by float noise. The divergence is asserted explicitly, so this test
    cannot silently drift outside it again.
    """
    magnitudes = 1e10 + (np.arange(_MARKOV_N) % 2) * 1e-4
    series = pd.Series(magnitudes, index=pd.date_range("1980-01-01", periods=_MARKOV_N, freq="QS"))

    absolute_span = float(series.max() - series.min())
    relative_span = absolute_span / float(np.max(np.abs(series.to_numpy())))
    # The claim, stated: this fixture is inside the divergence, and a series that
    # moves by 52 ULPs is not degenerate in any absolute sense.
    assert absolute_span > 1e-8, absolute_span
    assert absolute_span / np.spacing(float(series.max())) > 10.0, "the variation is float noise"
    assert relative_span < 100.0 * float(np.finfo(np.float64).eps), relative_span

    with pytest.raises(ValueError, match="no variation"):
        classify_regime_markov_switching(series)


def test_markov_length_floor_is_derived_from_the_parameter_count() -> None:
    """The floor MOVES with the parameter count, which is why it is derived.

    With the shipped 5.0 per parameter and 12 parameters (k=3, switching
    variance) the floor is 60. Lowering the per-parameter factor to 2.0 makes the
    floor 24, so a 30-observation series is refused under the shipped config and
    accepted under the moved one — a symmetry-breaking test, because a hardcoded
    floor cannot follow the leaf.
    """
    short = _markov_series(n=30)
    with pytest.raises(ValueError, match="requiring at least 60"):
        classify_regime_markov_switching(short)
    with _with_markov(min_observations_per_parameter_value=_markov_leaf(2.0)):
        assert _markov_value(classify_regime_markov_switching(short))["periods"] == 30


def test_markov_refuses_k_below_two_above_the_ceiling_and_non_integer() -> None:
    series = _markov_series()
    with pytest.raises(ValueError, match="at least 2"):
        classify_regime_markov_switching(series, k_regimes=1)
    with pytest.raises(ValueError, match=r"exceeds regime\.markov\.max_regimes_value"):
        classify_regime_markov_switching(series, k_regimes=7)
    with pytest.raises(TypeError, match="must be an int"):
        classify_regime_markov_switching(series, k_regimes=3.0)  # type: ignore[arg-type]
    # `isinstance(True, int)` is True in Python, so a bool would silently select a
    # two-regime model without this check.
    with pytest.raises(TypeError, match="must be an int"):
        classify_regime_markov_switching(series, k_regimes=True)


def test_markov_k_ceiling_is_read_from_config() -> None:
    with (
        _with_markov(max_regimes_value=_markov_leaf(2)),
        pytest.raises(ValueError, match=r"max_regimes_value=2"),
    ):
        classify_regime_markov_switching(_markov_series(), k_regimes=3)


def test_markov_refuses_a_degenerate_two_valued_series() -> None:
    """The library's raw `LinAlgError` must be converted into a named refusal.

    Measured 2026-09-24: a 0/1 series has plenty of variation (so the no-variation
    guard passes it) and still kills the fit inside the EM step with
    `numpy.linalg.LinAlgError: SVD did not converge` — an exception that names
    neither the series nor the row.
    """
    rng = np.random.default_rng(5)
    binary = pd.Series(rng.integers(0, 2, _MARKOV_N).astype(float))
    with pytest.raises(ValueError, match="Markov-switching fit failed"):
        classify_regime_markov_switching(binary)


# --- 5. config leaves are read, not restated ---------------------------------


def test_markov_switching_variance_is_read_from_config(markov_result: Any) -> None:
    """The parameter count is the observable, and it moves with the leaf."""
    assert (
        _markov_value(markov_result)["n_parameters"] == 12
    )  # 6 transitions + 3 means + 3 variances
    with _with_markov(switching_variance=False):
        common = classify_regime_markov_switching(_markov_series())
    assert _markov_value(common)["n_parameters"] == 10  # one shared variance


def test_markov_modal_share_bar_is_read_from_config(markov_result: Any) -> None:
    """Move the bar below the measured share and the base-state warning must appear."""
    value = _markov_value(markov_result)
    share = value["modal_regime_share"]
    assert share < 0.9, f"the fixture's modal share ({share}) is above the shipped bar"
    assert not any("BASE STATE:" in w for w in markov_result.warnings)
    with _with_markov(modal_share_warning_threshold_value=_markov_leaf(share / 2.0)):
        moved = classify_regime_markov_switching(_markov_series())
    assert any("BASE STATE:" in w for w in moved.warnings)


def test_markov_max_iterations_is_read_from_config(markov_result: Any) -> None:
    """The cap is not decorative: at 50 the optimizer reports non-convergence."""
    assert _markov_value(markov_result)["converged"] is True
    with _with_markov(max_iterations_value=_markov_leaf(50)):
        truncated = classify_regime_markov_switching(_markov_series())
    assert _markov_value(truncated)["converged"] is False


def test_markov_non_convergence_is_reported_without_discarding_the_fit() -> None:
    """D-101's finding, MEASURED here on a different library: the flag can lie.

    At `max_iterations=50` the optimizer reports `converged=False` while the
    log-likelihood is within a few tenths of the fully converged value — it is at
    the optimum and does not know it. The function therefore PUBLISHES the flag
    and warns, rather than refusing. This test pins the gap, so the warning's
    claim is a measurement rather than an assertion.
    """
    with _with_markov(max_iterations_value=_markov_leaf(50)):
        truncated = classify_regime_markov_switching(_markov_series())
    converged = classify_regime_markov_switching(_markov_series())
    assert _markov_value(truncated)["converged"] is False
    assert _markov_value(converged)["converged"] is True
    gap = abs(
        _markov_value(truncated)["log_likelihood"] - _markov_value(converged)["log_likelihood"]
    )
    assert gap < 1.0, (
        f"the truncated fit is {gap:.2f} log-likelihood units from the converged one, so "
        f"non-convergence here is NOT the benign stopping-rule case the warning describes"
    )


def test_markov_config_refuses_unusable_leaves() -> None:
    from pydantic import ValidationError

    share = "modal_share_warning_threshold_value"
    with pytest.raises(ValidationError, match="must be at least 2"):
        _markov_config(max_regimes_value=_markov_leaf(1))
    with pytest.raises(ValidationError, match="must be a whole number"):
        _markov_config(max_regimes_value=_markov_leaf(3.5))
    with pytest.raises(ValidationError, match=r"strictly\s+inside"):
        _markov_config(**{share: _markov_leaf(1.0)})
    with pytest.raises(ValidationError, match=r"strictly\s+inside"):
        _markov_config(**{share: _markov_leaf(0.0)})
    with pytest.raises(ValidationError, match=r"must exceed 1\.0"):
        _markov_config(min_observations_per_parameter_value=_markov_leaf(1.0))
    with pytest.raises(ValidationError, match="markov_trend"):
        _markov_config(markov_trend="n")
    with pytest.raises(ValidationError, match="markov_optimizer"):
        _markov_config(markov_optimizer="gradient-descent")
    with pytest.raises(ValidationError, match="whole number >= 0"):
        _markov_config(search_reps_value=_markov_leaf(-1))


def test_markov_trend_leaf_excludes_the_values_without_a_regime_intercept() -> None:
    """The exclusion is load-bearing: without an intercept there is nothing to order by.

    Probed 2026-09-24: `trend="n"` produces no regime-specific parameter at all
    and `trend="t"` produces a TIME TREND (`x1[i]`) rather than a level. Under
    either, the canonical ordering would have no key and the published index
    would revert to the library's arbitrary labelling.
    """
    from pydantic import ValidationError

    for excluded in ("n", "t"):
        with pytest.raises(ValidationError, match="markov_trend"):
            _markov_config(markov_trend=excluded)
    for permitted in ("c", "ct"):
        assert _markov_config(markov_trend=permitted).markov_trend == permitted


def test_markov_parameter_count_formula_matches_the_fitted_model(markov_result: Any) -> None:
    """The derived count must equal what the library actually estimated.

    The floor is derived from this formula, so if the formula and the library
    disagree the floor is enforcing the wrong number.
    """
    settings = get_settings().regime.markov
    for k in (2, 3, 4):
        expected = k * (k - 1) + k + (k if settings.switching_variance else 1)
        assert settings.parameters_for(k) == expected
    assert _markov_value(markov_result)["n_parameters"] == settings.parameters_for(
        _markov_value(markov_result)["k_regimes"]
    )
    assert _markov_value(markov_result)["observations_per_parameter"] == pytest.approx(
        _MARKOV_N / _markov_value(markov_result)["n_parameters"], rel=1e-6
    )


# --- 6. warnings: every branch reachable, and a partition not a hit ----------


def test_markov_warning_markers_are_mutually_non_colliding() -> None:
    """5f: a hit is not a partition. No marker may be a substring of another."""
    for outer in _MARKOV_WARNING_MARKERS:
        for inner in _MARKOV_WARNING_MARKERS:
            if inner is not outer:
                assert inner not in outer, f"{inner!r} collides inside {outer!r}"


def test_markov_every_emitted_warning_matches_exactly_one_marker(markov_result: Any) -> None:
    """The partition half: each emitted warning is claimed by exactly one branch."""
    for warning in markov_result.warnings:
        hits = [m for m in _MARKOV_WARNING_MARKERS if m in warning]
        assert len(hits) == 1, f"warning matched {hits}: {warning[:120]}"


def test_markov_every_warning_branch_is_reachable_by_some_test() -> None:
    """The coverage half, driven explicitly so no branch can ship uncovered."""
    seen: set[str] = set()

    def collect(result: Any) -> None:
        for warning in result.warnings:
            for marker in _MARKOV_WARNING_MARKERS:
                if marker in warning:
                    seen.add(marker)

    collect(classify_regime_markov_switching(_markov_series()))
    with _with_markov(max_iterations_value=_markov_leaf(50)):
        collect(classify_regime_markov_switching(_markov_series()))
    with _with_markov(modal_share_warning_threshold_value=_markov_leaf(0.05)):
        collect(classify_regime_markov_switching(_markov_series()))

    missing = set(_MARKOV_WARNING_MARKERS) - seen
    assert not missing, f"warning branches no test reaches: {sorted(missing)}"


def test_markov_library_warnings_are_counted_and_named() -> None:
    """A library call that warns is a silent-failure surface unless the count travels.

    Driven with a random walk, which was measured 2026-09-24 to make the library
    raise EstimationWarnings while still converging — so this exercises the
    library-warning branch WITHOUT the non-convergence branch.
    """
    rng = np.random.default_rng(0)
    walk = pd.Series(np.cumsum(rng.normal(0.05, 1.0, _MARKOV_N)))
    result = classify_regime_markov_switching(walk)
    value = _markov_value(result)
    assert value["converged"] is True, "this fixture is chosen to converge"
    assert value["library_warning_count"] > 0, "the library was expected to warn on this series"
    assert sum(value["library_warning_categories"].values()) == value["library_warning_count"]
    assert any("THE LIBRARY RAISED" in w for w in result.warnings)


def test_markov_base_rate_is_published_with_its_denominator(markov_result: Any) -> None:
    """A share without its denominator is not a base rate (D-029)."""
    value = _markov_value(markov_result)
    shares = value["regime_shares"]
    counts = value["regime_period_counts"]
    assert len(shares) == value["k_regimes"]
    # The counts are the auditable form: they must total the sample exactly, and
    # the shares must be exactly those counts over that total.
    assert sum(counts) == value["periods"]
    assert shares == pytest.approx([c / value["periods"] for c in counts], rel=1e-12)
    assert sum(shares) == pytest.approx(1.0, rel=1e-12)
    assert value["modal_regime_share"] == pytest.approx(max(shares))
    assert value["modal_regime"] == int(np.argmax(shares))
    assert value["periods"] == _MARKOV_N
    assert any(f"{value['modal_regime_share']:.1%}" in w for w in markov_result.warnings)


def test_markov_base_rate_is_measured_on_the_smoothed_path() -> None:
    """Recomputed from the PUBLISHED path, which is what makes the choice testable.

    The base rate is a frequency over HISTORY, so it is measured on the smoothed
    path — the retrospective best estimate of which regime each period was in —
    not on the real-time filtered one. That choice is invisible whenever the two
    paths agree on the argmax, and MEASURED 2026-09-24 they agree on the module's
    own fixture (its three regimes are 40 clean consecutive periods each), so a
    mutation swapping the paths SURVIVED it.

    This fixture is built to be INSIDE the disagreement — two means only 0.6 apart
    with unit noise — and the disagreement is ASSERTED rather than assumed: at
    seed 8 it leaves 18 of 120 periods where the two paths' argmax differs, with
    counts `[43, 4, 73]` (smoothed) against `[34, 3, 83]` (filtered). The counts
    are then recomputed from `smoothed_probabilities`, a published component, so a
    base rate taken from the other path cannot match.

    The filtered path is recomputed below ONLY to prove the FIXTURE discriminates —
    a test of the fixture, not of the function — because a fixture that drifted out
    of the divergence would let the mutation survive silently (M74/M108).
    """
    from statsmodels.tsa.regime_switching.markov_regression import MarkovRegression

    rng = np.random.default_rng(8)
    values = np.concatenate([np.full(60, 0.0), np.full(60, 0.6)]) + rng.normal(0.0, 1.0, _MARKOV_N)
    series = pd.Series(values, index=pd.date_range("1980-01-01", periods=_MARKOV_N, freq="QS"))
    value = _markov_value(classify_regime_markov_switching(series))

    smoothed = np.asarray(value["smoothed_probabilities"], dtype=float)
    recomputed = np.bincount(np.argmax(smoothed, axis=1), minlength=value["k_regimes"]).tolist()
    assert value["regime_period_counts"] == recomputed, (
        f"the published counts {value['regime_period_counts']} are not the argmax of the "
        f"published smoothed path {recomputed} — the base rate was taken from a "
        f"different path than the one published"
    )
    assert sum(recomputed) == value["periods"]

    # The fixture's discriminating power, measured rather than assumed.
    settings = get_settings().regime.markov
    order = value["regime_order_raw_index"]
    model = MarkovRegression(
        np.asarray(series.to_numpy(), dtype=float),
        k_regimes=value["k_regimes"],
        trend=settings.markov_trend,
        switching_variance=settings.switching_variance,
    )
    fitted = model.fit(
        method=settings.markov_optimizer,
        maxiter=settings.max_iterations,
        em_iter=settings.em_iterations,
        search_reps=settings.search_reps,
    )
    filtered = np.asarray(fitted.filtered_marginal_probabilities, dtype=float)[:, order]
    filtered_counts = np.bincount(
        np.argmax(filtered, axis=1), minlength=value["k_regimes"]
    ).tolist()
    assert filtered_counts != recomputed, (
        f"this fixture's smoothed and filtered argmax paths now agree ({recomputed}), so "
        f"it can no longer distinguish a base rate measured on one from a base rate "
        f"measured on the other — pick a seed inside the divergence"
    )


# --- 7. the output contract --------------------------------------------------


def test_markov_confidence_comes_from_compute_confidence(markov_result: Any) -> None:
    """Pinned against the ABSOLUTE rule, not against the function's own output.

    Comparing two calls of the same function would move both sides together, so a
    changed constant would be invisible (D-046). The expected value is recomputed
    from `compute_confidence` with the inputs the docstring states, and is also
    asserted to DIFFER from the value a naive `base` literal would give.
    """
    expected = compute_confidence(
        ConfidenceInputs(
            is_heuristic_not_calibrated=True,
            depends_on_unobservable=True,
            source_independence_count=0,
        )
    )
    assert markov_result.confidence == expected
    assert markov_result.confidence != compute_confidence(ConfidenceInputs())


def test_markov_output_is_json_serialisable(markov_result: Any) -> None:
    """A numpy scalar leaking into `value` would break the API layer, not the model.

    `ModelResult.value` is a broad union, so pydantic accepts a `np.float64` and
    the failure would surface only at serialisation — one layer away from the
    cause.
    """
    payload = json.dumps({"value": markov_result.value, "warnings": markov_result.warnings})
    assert '"smoothed_probabilities"' in payload


def test_markov_provenance_and_prohibitions_are_published(markov_result: Any) -> None:
    value = _markov_value(markov_result)
    assert markov_result.inputs_used == ["series"]
    assert markov_result.country == "us"
    assert markov_result.as_of.tzinfo is not None
    assert value["current_period"].startswith("2009"), value["current_period"]
    assert markov_result.observation_dates == {"series_last_period": value["current_period"]}
    joined = " ".join(markov_result.decision_prohibition)
    assert "causal" in joined
    assert "k_regimes" in joined
    assert any("NO channel for a data-quality flag" in item for item in markov_result.limitations)


def test_markov_fit_is_deterministic() -> None:
    """The shipped `search_reps=0` makes the fit reproducible, which the tests rely on."""
    series = _markov_series()
    assert (
        classify_regime_markov_switching(series).value
        == classify_regime_markov_switching(series).value
    )
