"""Module 3.6 tests — the projected inflation trajectory (D-053).

The centrepiece here is the **reachability test**, and it is a different kind of
test from the direction test that anchors the sibling Phillips-curve module.

A ``Literal`` return type is a promise with two halves (D-045a): every value
returned must be a member, *and* every member must be producible. The
specification's version of this function satisfied the first half and violated
the second by accident — it admitted three labels, but its ``0.05`` threshold
against a quantity on the ``-0.3..+0.3`` score-fraction scale put ``stable`` in
**79.1% of real months** (measured 2001-12..2026-07, n=296). The two directional
labels were technically reachable and practically rare, so the function's own
discriminating power was mostly absent and nothing in the code said so.

``test_every_direction_is_reachable_over_the_declared_range`` is that check made
mechanical: it drives the classifier across the score's **declared** range and
asserts all three labels appear. A future config edit that re-narrows the band
until one label becomes unreachable fails here rather than silently shipping an
uninformative classifier. This is the D-047 lesson — "the confident label is the
base state" — caught at the point where it would be introduced.

The second centrepiece is the **sign test**. The specification negates twice
(``slack = -s/100``, then ``pc = -beta*slack``) and the negations cancel, so a
tight market must produce a *positive* projected change. Writing the negation
once instead of twice is a one-character change that produces a
plausible-looking output in the wrong direction, so it is asserted against a
case whose answer is known before the code runs, not checked by inspection.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from macro_engine.config import get_settings
from macro_engine.models.contracts import ModelResult, utc_now
from macro_engine.models.inflation_trajectory import (
    InflationTrajectoryInputs,
    TrajectoryDirection,
    project_inflation_trajectory,
)

# --------------------------------------------------------------------------
# Fixtures — hand-verified, from the module docstring's worked examples
# --------------------------------------------------------------------------


def _result(
    name: str,
    value: float | int | str | bool | dict[str, object] | list[object] | None,
    warnings: list[str] | None = None,
) -> ModelResult:
    """A minimal ``ModelResult`` carrying a chosen value.

    Built directly rather than by calling the upstream models: this module's
    contract is about what it does with a *result*, so the test should be able
    to hand it one with a chosen value without three other models agreeing
    first. The upstream models have their own tests.

    ``value`` is typed as the ``ModelResult`` union rather than ``object`` so a
    test passing a genuinely inadmissible type is a type error at the call site
    -- the non-numeric cases below pass ``"n/a"`` and ``None``, which are legal
    members of the union and exercise the model's own guards.
    """
    return ModelResult(
        model_name=name,
        country="us",
        as_of=utc_now(),
        value=value,
        confidence=0.35,
        interpretation="fixture",
        context="fixture",
        inputs_used=["fixture"],
        warnings=warnings or [],
    )


def _inputs(
    *,
    labor: float = 0.0,
    growth: float = 1.0,
    inflation: float = 2.6,
    fiscal: bool = False,
    labor_warnings: list[str] | None = None,
) -> InflationTrajectoryInputs:
    return InflationTrajectoryInputs(
        growth=_result("output_gap", growth),
        labor=_result("labor_tightness_score", labor, labor_warnings),
        inflation=_result("inflation_breadth_score", inflation),
        fiscal_response_active=fiscal,
    )


def _change_pp(result: ModelResult) -> float:
    value = result.value
    assert isinstance(value, dict)
    entry = value["projected_change_pp"]
    assert isinstance(entry, (int, float)) and not isinstance(entry, bool)
    return float(entry)


def _direction(result: ModelResult) -> str:
    value = result.value
    assert isinstance(value, dict)
    entry = value["direction"]
    assert isinstance(entry, str)
    return entry


def _corroboration(result: ModelResult) -> str:
    value = result.value
    assert isinstance(value, dict)
    entry = value["growth_corroboration"]
    assert isinstance(entry, str)
    return entry


def _beta() -> float:
    return get_settings().phillips.trajectory.beta_pp_per_score_point


# --------------------------------------------------------------------------
# The sign test — catches the single-negation error
# --------------------------------------------------------------------------


def test_tight_labor_projects_reaccelerating_inflation() -> None:
    """The direction the specification intends, asserted on a known case.

    A *tight* labor market (positive score) must produce a **positive** projected
    change. The specification reaches this through two negations that cancel;
    writing one of them inverts a one-character detail into a wrong-signed
    output that no shape or magnitude assertion can catch.
    """
    tight = project_inflation_trajectory(_inputs(labor=+40.0))
    loose = project_inflation_trajectory(_inputs(labor=-40.0))

    assert _change_pp(tight) > 0.0, (
        f"a TIGHT labor market must project RISING inflation; got "
        f"{_change_pp(tight):+.4f}pp. A sign has been lost — the specification "
        f"negates twice (slack = -s/100, then pc = -beta*slack) and the two "
        f"cancel, so change_pp carries the SAME sign as the score."
    )
    assert _change_pp(loose) < 0.0, "a LOOSE labor market must project FALLING inflation"


def test_sign_is_monotone_in_the_score() -> None:
    """Strictly increasing across the declared range: no flat or reversing span.

    A sign error can pass a two-point test by landing both points on the wrong
    side of a threshold. Monotonicity across the *whole* range cannot.
    """
    scores = [-100.0, -50.0, -10.0, 0.0, 10.0, 50.0, 100.0]
    changes = [_change_pp(project_inflation_trajectory(_inputs(labor=s))) for s in scores]
    assert changes == sorted(changes), f"projected change not monotone: {changes}"
    assert len(set(changes)) == len(changes), f"projected change has ties: {changes}"


def test_the_projected_change_is_beta_times_the_score() -> None:
    """The arithmetic, stated independently of the implementation.

    Verifies the *named estimand* has the value the docstring claims, so a
    change to ``beta``'s unit in config cannot silently alter the relationship
    between the score and the published number.
    """
    beta = _beta()
    for score in (-100.0, -7.5, 0.0, 3.25, 100.0):
        expected = beta * score
        actual = _change_pp(project_inflation_trajectory(_inputs(labor=score)))
        assert actual == pytest.approx(expected, abs=1e-4), (
            f"score {score}: expected {expected!r}pp, got {actual!r}pp"
        )


# --------------------------------------------------------------------------
# The reachability test — the D-047 base-state failure, made mechanical
# --------------------------------------------------------------------------


def test_every_direction_is_reachable_over_the_declared_range() -> None:
    """All three labels appear across the score's DECLARED range (-100..+100).

    This is the defect the specification shipped: three declared labels, one of
    which covered 79.1% of real months. A ``Literal`` is a promise that every
    member is producible, and this asserts it rather than assuming it.
    """
    seen = {
        _direction(project_inflation_trajectory(_inputs(labor=float(score))))
        for score in range(-100, 101)
    }
    assert seen == {"reaccelerating", "stable", "decelerating"}, (
        f"unreachable direction(s) over the declared score range: "
        f"{{'reaccelerating', 'stable', 'decelerating'}} - {seen}. The labels "
        f"must all be producible or the classifier carries no information."
    )


def test_both_directional_labels_are_reachable_within_a_realistic_score() -> None:
    """Reachability must not depend on the *extremes* of the scale.

    The declared range runs to ±100, but the measured score has a standard
    deviation of 19.3 and a maximum of +59.6 (2001-12..2026-07). If a label were
    reachable only at ±100 it would be unreachable in practice. Assert both
    directional labels fire for scores within two standard deviations.
    """
    for label, score in (("reaccelerating", +30.0), ("decelerating", -30.0)):
        got = _direction(project_inflation_trajectory(_inputs(labor=score)))
        assert got == label, (
            f"score {score:+.1f} (±1.6 sd of the measured distribution) produced "
            f"{got!r}, not {label!r} — the band is too wide to discriminate on "
            f"real data"
        )


def test_band_width_matches_the_configured_threshold() -> None:
    """The dead band's *width* is what config says, not what the code implies.

    The specification's effective band was ±16.67 score points, chosen by
    accident from a unit mismatch. This asserts the band is the one config
    names, in the score-point units a reader can check.
    """
    settings = get_settings().phillips.trajectory
    beta = settings.beta_pp_per_score_point
    half_width = settings.bands.reaccelerating_above / beta
    inside = half_width * 0.999
    outside = half_width * 1.001

    assert _direction(project_inflation_trajectory(_inputs(labor=+inside))) == "stable"
    assert _direction(project_inflation_trajectory(_inputs(labor=+outside))) == "reaccelerating"
    assert _direction(project_inflation_trajectory(_inputs(labor=-inside))) == "stable"
    assert _direction(project_inflation_trajectory(_inputs(labor=-outside))) == "decelerating"


def test_the_band_and_beta_are_independent_config_values() -> None:
    """The band, in SCORE POINTS, is ``band_pp / beta`` — so they are not free.

    The live check caught an earlier configuration where ``beta`` had been
    derived from a band-corner spread and the band had then been chosen
    separately, producing a 7x error in the slope and a band that put 79% of
    history in ``stable``. This test pins the relationship so a future edit to
    either value has to confront the other.
    """
    settings = get_settings().phillips.trajectory
    beta = settings.beta_pp_per_score_point
    band_pp = settings.bands.reaccelerating_above

    assert beta > 0, "beta must be positive: a tight market raises inflation"
    assert band_pp > 0, "the upper band must be positive"
    assert settings.bands.decelerating_below == pytest.approx(-band_pp), (
        "the bands must be symmetric: an asymmetric band makes one direction "
        "rarer for reasons unrelated to the economy"
    )

    half_width_points = band_pp / beta
    assert 2.0 < half_width_points < 40.0, (
        f"the band is ±{half_width_points:.2f} score points. Below ~2 points it "
        f"fires on noise; above ~40 the score's whole interquartile range sits "
        f"inside it and `stable` becomes the base state (D-047)."
    )


def test_the_configured_band_is_not_a_base_state_on_the_declared_range() -> None:
    """No single label may cover more than 75% of a uniform score sweep.

    A coarse but config-only proxy for the live base-rate check: with a uniform
    score distribution over the declared range, a band so wide that one label
    dominates is the specification's failure. The live measurement in
    ``scripts/live_projection_check.py`` is the real test; this is the cheap one
    that runs with the suite.
    """
    labels = [
        _direction(project_inflation_trajectory(_inputs(labor=float(score))))
        for score in range(-100, 101)
    ]
    counts = {name: labels.count(name) for name in set(labels)}
    worst_name, worst_count = max(counts.items(), key=lambda kv: kv[1])
    worst_share = worst_count / len(labels)
    assert worst_share <= 0.75, (
        f"{worst_name!r} covers {worst_share:.1%} of the declared range — the "
        f"band is too wide to discriminate (the specification's 79.1%)"
    )


# --------------------------------------------------------------------------
# The band partition — exhaustive, non-overlapping, boundary-assigned
# --------------------------------------------------------------------------


def test_band_partition_is_exhaustive_and_non_overlapping() -> None:
    """Every score on a fine grid lands in exactly one band, by the stated rule.

    The comparison is strict on *both* sides, so a reading exactly on a bound
    falls to ``stable``. Recomputed here from the published ``projected_change_pp``
    rather than from the direction, so the two are checked against each other.
    """
    upper = get_settings().phillips.trajectory.bands.reaccelerating_above
    lower = get_settings().phillips.trajectory.bands.decelerating_below

    for index in range(-2000, 2001):
        score = index / 20.0  # 0.05-point grid over -100..+100
        out = project_inflation_trajectory(_inputs(labor=score))
        change = _change_pp(out)
        expected = (
            "reaccelerating" if change > upper else "decelerating" if change < lower else "stable"
        )
        assert _direction(out) == expected, (
            f"score {score}: change {change:+.6f}pp, upper {upper}, lower {lower} "
            f"-> expected {expected!r}, got {_direction(out)!r}"
        )


def test_exactly_on_a_bound_is_stable() -> None:
    """A reading *exactly* on the boundary is ``stable``: the comparisons are strict.

    This is a boundary convention, not an accident, and it is asserted because
    ``>`` versus ``>=`` is invisible in every non-boundary test.
    """
    settings = get_settings().phillips.trajectory
    beta = settings.beta_pp_per_score_point
    boundary_score = settings.bands.reaccelerating_above / beta

    on_upper = project_inflation_trajectory(_inputs(labor=+boundary_score))
    on_lower = project_inflation_trajectory(_inputs(labor=-boundary_score))

    assert _direction(on_upper) == "stable", "a reading exactly on the upper bound must be stable"
    assert _direction(on_lower) == "stable", "a reading exactly on the lower bound must be stable"
    assert _change_pp(on_upper) == pytest.approx(settings.bands.reaccelerating_above, abs=1e-9)
    assert _change_pp(on_lower) == pytest.approx(settings.bands.decelerating_below, abs=1e-9)


def test_zero_score_is_stable() -> None:
    """A balanced score projects no change, and lands in the dead band."""
    out = project_inflation_trajectory(_inputs(labor=0.0))
    assert _direction(out) == "stable"
    assert _change_pp(out) == pytest.approx(0.0, abs=1e-9)


# --------------------------------------------------------------------------
# The declared-but-unread defect: `growth` must actually be read
# --------------------------------------------------------------------------


def test_growth_actually_changes_the_output() -> None:
    """``growth`` is read, so varying it alone can change the result.

    The specification declares ``growth``, lists it implicitly, and never reads
    it — enumerated over its whole admissible space the return value was
    invariant. This test fails against a body that ignores the parameter.
    """
    baseline = project_inflation_trajectory(_inputs(labor=-20.0, growth=-2.0))
    other = project_inflation_trajectory(_inputs(labor=-20.0, growth=+2.0))

    value_a = baseline.value
    value_b = other.value
    assert isinstance(value_a, dict) and isinstance(value_b, dict)
    assert value_a["growth_corroboration"] != value_b["growth_corroboration"], (
        "varying `growth` alone left the output's corroboration unchanged — the "
        "parameter is declared and unread (the specification's defect 3)"
    )


def test_growth_and_labor_disagreement_is_reported() -> None:
    """A tight labor market against a contracting output gap is flagged.

    This is the case where the labor-derived projection is a claim about a
    *narrower* mechanism than the caller may be treating it as. The flag is the
    information; silently returning a direction would hide it.
    """
    out = project_inflation_trajectory(_inputs(labor=+30.0, growth=-2.0))
    value = out.value
    assert isinstance(value, dict)
    assert value["growth_corroboration"] == "disagrees_tight_labor_weak_growth"
    assert any("DISAGREE" in warning for warning in out.warnings), (
        "the disagreement must be a warning, not only a field"
    )


def test_growth_agreement_is_reported_as_corroboration() -> None:
    """A tight labor market in an expansion corroborates the projection."""
    out = project_inflation_trajectory(_inputs(labor=+30.0, growth=+2.0))
    value = out.value
    assert isinstance(value, dict)
    assert value["growth_corroboration"] == "agrees_expansion"


def test_all_four_corroboration_quadrants_are_distinguished() -> None:
    """The full 2x2 of (labor sign, growth sign) maps to four distinct states.

    Added because the mutation sweep found this gap: the four states each had a
    test, but each test exercised **one** quadrant, so a mutation that forced the
    agreement test true survived — it broke the ``loose + expanding`` quadrant,
    which no test drove. Both agreement branches need to be asserted on their own
    inputs *and* against the disagreeing inputs that share those inputs' sign
    pattern, which is what a quadrant table does and a per-state test does not.

    The mapping:
        tight labor + expanding growth  -> agrees_expansion
        loose labor + contracting growth-> agrees_contraction
        tight labor + contracting growth-> disagrees_tight_labor_weak_growth
        loose labor + expanding growth  -> disagrees_loose_labor_strong_growth
    """
    expected = {
        (+30.0, +2.0): "agrees_expansion",
        (-30.0, -2.0): "agrees_contraction",
        (+30.0, -2.0): "disagrees_tight_labor_weak_growth",
        (-30.0, +2.0): "disagrees_loose_labor_strong_growth",
    }
    produced = {
        (labor, growth): _corroboration(
            project_inflation_trajectory(_inputs(labor=labor, growth=growth))
        )
        for labor, growth in expected
    }
    assert produced == expected, f"quadrant mapping wrong: {produced}"
    assert len(set(produced.values())) == 4, (
        "the four quadrants must map to four DISTINCT states; a collapsed pair "
        "means one branch is unreachable"
    )


def test_every_corroboration_state_is_reachable() -> None:
    """All five declared corroboration states are producible.

    The same discipline as the direction reachability test: a named state that no
    input can produce is a contract nothing can reach.
    """
    cases = [
        _inputs(labor=+30.0, growth=+2.0),
        _inputs(labor=-30.0, growth=-2.0),
        _inputs(labor=+30.0, growth=-2.0),
        _inputs(labor=-30.0, growth=+2.0),
        _inputs(labor=0.0, growth=+2.0),
    ]
    states = {_corroboration(project_inflation_trajectory(case)) for case in cases}
    assert states == {
        "agrees_expansion",
        "agrees_contraction",
        "disagrees_tight_labor_weak_growth",
        "disagrees_loose_labor_strong_growth",
        "not_directional",
    }


def test_non_numeric_growth_does_not_crash_and_is_declared() -> None:
    """A verdict-valued growth result degrades to a stated limitation.

    ``ModelResult.value`` is a union by design (Section 22.9), so a caller can
    legitimately hand this function a result whose value is a string. The
    function must not raise, and must say that the corroboration did not run.
    """
    out = project_inflation_trajectory(
        InflationTrajectoryInputs(
            growth=_result("output_gap", "unavailable"),
            labor=_result("labor_tightness_score", +20.0),
            inflation=_result("inflation_breadth_score", 2.6),
        )
    )
    value = out.value
    assert isinstance(value, dict)
    assert value["growth_corroboration"] == "unavailable"
    assert any("could not run" in warning for warning in out.warnings)


# --------------------------------------------------------------------------
# The numeric-validity tests: `labor.value` is the only sign-bearing input
# --------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [True, False, "40.0", None, [40.0], {"v": 40.0}])
def test_non_numeric_labor_value_raises(
    bad: float | int | str | bool | dict[str, object] | list[object] | None,
) -> None:
    """A non-numeric score raises rather than being coerced.

    ``bool`` is included and is the important one: ``isinstance(True, int)`` is
    true, so a bare ``float()`` would silently accept ``True`` as ``1.0`` — a
    wrong value producing a plausible output, which is the failure mode this
    project's tests exist to catch.

    The parameter is typed as the ``ModelResult`` union so the parametrisation
    stays within what a real result can carry. A ``complex`` or a ``set`` would
    be rejected by mypy before it reached the model, which would test the type
    checker rather than the guard.
    """
    with pytest.raises(TypeError, match="must be a float"):
        project_inflation_trajectory(
            InflationTrajectoryInputs(
                growth=_result("output_gap", 1.0),
                labor=_result("labor_tightness_score", bad),
                inflation=_result("inflation_breadth_score", 2.6),
            )
        )


@pytest.mark.parametrize("bad", [-100.1, 100.1, 1e6, -1e6])
def test_out_of_range_labor_value_raises(bad: float) -> None:
    """A score outside the declared range raises rather than being clamped.

    The producer clamps; this function does not. Clamping here would hide a
    caller passing the wrong field — for example a raw claims level — behind a
    result that still looks like a score.
    """
    with pytest.raises(ValueError, match="outside the scale's declared range"):
        project_inflation_trajectory(_inputs(labor=bad))


@pytest.mark.parametrize("edge", [-100.0, 100.0])
def test_range_endpoints_are_accepted(edge: float) -> None:
    """Both endpoints of the declared range are valid, not off-by-one."""
    out = project_inflation_trajectory(_inputs(labor=edge))
    assert _direction(out) in ("reaccelerating", "decelerating")


# --------------------------------------------------------------------------
# The §18.6 fiscal flag
# --------------------------------------------------------------------------


def test_fiscal_flag_scales_the_change_and_is_reported() -> None:
    """The §18.6 parameter exists, is consumed, and names the scale applied."""
    settings = get_settings().phillips.trajectory
    scale = settings.fiscal_active_scale

    without = project_inflation_trajectory(_inputs(labor=+20.0, fiscal=False))
    with_fiscal = project_inflation_trajectory(_inputs(labor=+20.0, fiscal=True))

    value_without = without.value
    value_with = with_fiscal.value
    assert isinstance(value_without, dict) and isinstance(value_with, dict)
    assert value_without["fiscal_scale_applied"] == pytest.approx(1.0)
    assert value_with["fiscal_scale_applied"] == pytest.approx(scale)
    assert _change_pp(with_fiscal) == pytest.approx(_change_pp(without) * scale, abs=1e-9)


def test_fiscal_flag_never_changes_the_sign() -> None:
    """The fiscal multiplier changes magnitude, never direction.

    Asserted because the multiplier is the one input that can move a reading
    across a *band* boundary, and it would be easy to write it so that it can
    also flip a sign — which would invent a direction the labor market does not
    support.
    """
    for score in (-100.0, -10.0, -1.0, 0.0, 1.0, 10.0, 100.0):
        plain = _change_pp(project_inflation_trajectory(_inputs(labor=score, fiscal=False)))
        scaled = _change_pp(project_inflation_trajectory(_inputs(labor=score, fiscal=True)))
        assert (plain > 0) == (scaled > 0) or plain == scaled == 0.0, (
            f"score {score}: fiscal flag flipped the sign ({plain!r} -> {scaled!r})"
        )


def test_fiscal_flag_defaults_to_false() -> None:
    """The conservative default: no fiscal response unless a caller says so."""
    inputs = InflationTrajectoryInputs(
        growth=_result("output_gap", 1.0),
        labor=_result("labor_tightness_score", +20.0),
        inflation=_result("inflation_breadth_score", 2.6),
    )
    assert inputs.fiscal_response_active is False
    value = project_inflation_trajectory(inputs).value
    assert isinstance(value, dict)
    assert value["fiscal_scale_applied"] == pytest.approx(1.0)


def test_fiscal_active_warning_only_when_active() -> None:
    """The fiscal warning is emitted when active and absent when not."""
    active = project_inflation_trajectory(_inputs(labor=+20.0, fiscal=True))
    inactive = project_inflation_trajectory(_inputs(labor=+20.0, fiscal=False))
    assert any("FISCAL RESPONSE ACTIVE" in warning for warning in active.warnings)
    assert not any("FISCAL RESPONSE ACTIVE" in warning for warning in inactive.warnings)


# --------------------------------------------------------------------------
# The prose/level inputs that must be read, and the §22.8 confidence rule
# --------------------------------------------------------------------------


def test_inflation_level_is_reported() -> None:
    """``inflation.value`` is the level the change is measured from, and is read."""
    out = project_inflation_trajectory(_inputs(labor=+20.0, inflation=3.75))
    value = out.value
    assert isinstance(value, dict)
    assert value["inflation_level"] == pytest.approx(3.75)


def test_non_numeric_inflation_level_is_reported_as_none_with_a_warning() -> None:
    """An unusable level is ``None`` with a warning, not ``0.0``.

    ``0.0`` would assert a measured zero-inflation level. The rule is the one
    ``ahe_composition_flag`` established: absent is ``None``, not a number.
    """
    out = project_inflation_trajectory(
        InflationTrajectoryInputs(
            growth=_result("output_gap", 1.0),
            labor=_result("labor_tightness_score", +20.0),
            inflation=_result("inflation_breadth_score", "n/a"),
        )
    )
    value = out.value
    assert isinstance(value, dict)
    assert value["inflation_level"] is None
    assert any("could not be reported" in warning for warning in out.warnings)


def test_confidence_is_produced_not_hardcoded() -> None:
    """§22.8: confidence is a fact about the computation, never a literal.

    The specification wrote ``confidence=0.35``. This asserts the value *varies*
    with a stated factor — a hardcoded constant would be invariant and would pass
    a single-case check.
    """
    agreeing = project_inflation_trajectory(_inputs(labor=+20.0, growth=+2.0))
    disagreeing = project_inflation_trajectory(_inputs(labor=+20.0, growth=-2.0))
    assert agreeing.confidence != disagreeing.confidence, (
        "confidence did not change when the source-independence factor changed — "
        "it is being hardcoded rather than produced by compute_confidence()"
    )


def test_confidence_matches_compute_confidence_exactly() -> None:
    """The published confidence equals ``compute_confidence()`` on the stated inputs.

    Recomputes independently, so a model that adjusted the result after the call
    would fail. The inputs are the model's own documented factors.
    """
    from macro_engine.models.contracts import ConfidenceInputs, compute_confidence

    out = project_inflation_trajectory(_inputs(labor=+20.0, growth=+2.0))
    expected = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=False,
            is_heuristic_not_calibrated=True,
            depends_on_unobservable=True,
            source_independence_count=1,
        )
    )
    assert out.confidence == pytest.approx(expected)


def test_labor_warnings_flag_the_confidence() -> None:
    """A data-quality flag on the labor input lowers confidence."""
    clean = project_inflation_trajectory(_inputs(labor=+20.0, growth=+2.0))
    flagged = project_inflation_trajectory(
        _inputs(labor=+20.0, growth=+2.0, labor_warnings=["clamped from +180.0"])
    )
    assert flagged.confidence < clean.confidence


# --------------------------------------------------------------------------
# Provenance: inputs_used must not overstate
# --------------------------------------------------------------------------


def test_inputs_used_lists_only_read_inputs() -> None:
    """Every entry in ``inputs_used`` is an input the body actually reads.

    The specification listed ``inflation.value`` while never reading it — a
    provenance claim that was false. This asserts the four names this
    implementation reads, and that the set is exactly those four.
    """
    out = project_inflation_trajectory(_inputs(labor=+20.0))
    assert set(out.inputs_used) == {
        "growth.value",
        "labor.value",
        "inflation.value",
        "fiscal_response_active",
    }


def test_the_declared_literal_and_its_members_agree() -> None:
    """``TrajectoryDirection``'s runtime half matches the declared members.

    The two halves of a ``Literal`` promise: this asserts the tuple a test can
    iterate names exactly the three labels the annotation declares.
    """
    import typing

    declared = set(typing.get_args(TrajectoryDirection))
    assert declared == {"reaccelerating", "stable", "decelerating"}
    produced = {
        _direction(project_inflation_trajectory(_inputs(labor=score)))
        for score in (-50.0, 0.0, 50.0)
    }
    assert produced <= declared


# --------------------------------------------------------------------------
# Model plumbing
# --------------------------------------------------------------------------


def test_result_carries_the_expected_shape() -> None:
    """``model_name``, ``country`` and a UTC ``as_of`` — the ModelResult contract."""
    out = project_inflation_trajectory(_inputs(labor=+20.0))
    assert out.model_name == "project_inflation_trajectory"
    assert out.country == "us"
    assert out.as_of.tzinfo is not None, "as_of must be timezone-aware (no naive datetimes)"


def test_value_dict_has_exactly_the_published_keys() -> None:
    """The key set is asserted, not iterated — an empty dict would pass a loop."""
    out = project_inflation_trajectory(_inputs(labor=+20.0))
    value = out.value
    assert isinstance(value, dict)
    assert set(value) == {
        "projected_change_pp",
        "direction",
        "beta_pp_per_score_point",
        "labor_score",
        "inflation_level",
        "growth_corroboration",
        "fiscal_response_active",
        "fiscal_scale_applied",
    }


def test_extra_fields_are_forbidden() -> None:
    """``extra="forbid"`` on the input model, per the project convention.

    Constructed through ``model_validate`` because the extra key is the point of
    the test and a typed constructor call would reject it at the call site --
    which would prove mypy works, not that the model guards its input.
    """
    with pytest.raises(ValidationError):
        InflationTrajectoryInputs.model_validate(
            {
                "growth": _result("output_gap", 1.0),
                "labor": _result("labor_tightness_score", 0.0),
                "inflation": _result("inflation_breadth_score", 2.6),
                "unexpected": True,
            }
        )


def test_the_near_term_horizon_limitation_is_always_stated() -> None:
    """The reversal is a warning on every call, because it bounds every reading."""
    for score in (-50.0, 0.0, +50.0):
        out = project_inflation_trajectory(_inputs(labor=score))
        assert any("NEAR TERM ONLY" in warning for warning in out.warnings)


def test_the_unfitted_beta_limitation_is_always_stated() -> None:
    """``beta`` is measured but not fitted, and every call says so."""
    out = project_inflation_trajectory(_inputs(labor=+20.0))
    assert any("NOT FITTED" in warning for warning in out.warnings)


def test_the_non_centred_score_limitation_is_always_stated() -> None:
    """The score's non-zero mean is a standing property of the projection."""
    out = project_inflation_trajectory(_inputs(labor=0.0))
    assert any("NOT centred on zero" in warning for warning in out.warnings)


def test_beta_is_read_from_config_not_hardcoded() -> None:
    """The published beta equals the configured one, and the key names its unit."""
    settings = get_settings().phillips.trajectory
    out = project_inflation_trajectory(_inputs(labor=+20.0))
    value = out.value
    assert isinstance(value, dict)
    assert value["beta_pp_per_score_point"] == pytest.approx(settings.beta_pp_per_score_point)
    assert "pp_per_score_point" in str(out.value), (
        "the unit must be visible in the published value, not only in the docstring"
    )
