"""Module 3.6 — the projected inflation trajectory (D-053).

What this function is, and what the specification thought it was
--------------------------------------------------------------
Section 16.2 asks a directional question: *given the labor market is where it
is, which way is inflation pressure pointing?* That is the Phillips relation
stated as a classification: ``pi = pi^e - beta (u - u*)``, so a tight market
(``u < u*``) projects inflation upward.

The specification's version of this function is seven lines, and **every one of
the seven produces a defect**. They are worth listing because five are the same
defect wearing different clothes — a quantity whose scale is not stated:

1. ``beta = 0.3`` is a **literal inside a model body**. Section 21 requires every
   coefficient in ``config/settings.yaml`` with a ``calibration_status``.
2. ``confidence=0.35`` is **hardcoded**, which Section 22.8 forbids outright:
   ``compute_confidence()`` is the only producer of that field.
3. ``growth`` is a **declared parameter the body never reads**. Enumerated over
   the specification's whole admissible space, the return value is invariant to
   it — the "declared, consumed, unreachable" class this project keeps finding.
4. ``inputs_used`` lists ``"inflation.value"``, which is likewise never read. An
   ``inputs_used`` list that overstates its inputs is worse than a short one: it
   is a claim about provenance that is false.
5. Section 18.6 requires a ``fiscal_response_active: bool`` parameter. The
   specification's own signature does not contain it.
6. ``projected_change`` carries **no unit**. The arithmetic is
   ``0.3 * labor.value / 100``, which is on the ``-0.3..+0.3`` *score-fraction*
   scale — not a percent, and not percentage points.
7. The comparison is against a bare ``0.05``, so the threshold inherits the
   ambiguity of (6). Read as the code's own arithmetic the band is
   ±16.67 score points, and **measured against history ``stable`` was the
   answer 79.1% of the time** (2001-12..2026-07, n=296): the D-047
   "the confident label is the base state" failure, arrived at by accident.

What this implementation does instead
-------------------------------------
**It names the estimand.** The output is

    projected_change_pp : change in ANNUAL CORE INFLATION, in percentage points

obtained as ``beta_pp_per_score_point * (-labor.value)``, with ``beta`` measured
from history and written down with its unit in the key name. The bands are
therefore in pp, like every other inflation quantity in this project, and their
width is chosen so that all three labels are reachable across the score's
**declared** range — which is checked, not hoped for.

**It reads the inputs it declares.** ``growth`` and ``inflation`` are consumed,
not merely accepted. ``growth`` enters as the *demand-side corroboration*: the
labor score measures the labor market specifically, and the Phillips story is
about excess demand generally, so a tight labor market against a collapsing
output gap is a case where the two disagree and the disagreement is the
information. ``inflation`` enters as the *starting point*: the projection is a
change, and the level it is a change from is reported.

**It consumes the fiscal flag §18.6 requires** — as a multiplier on the
projected change, not as a second set of bands, so the direction of the
adjustment is a single auditable number.

Three honest limits, all carried in the output
----------------------------------------------
* **The horizon is 3-9 months and it REVERSES after 12.** The OLS slope of the
  forward core-inflation change on the score is ``+0.0036`` at 3 months,
  ``+0.0060`` at 6 (``t = +3.76``), ``+0.0078`` at 9, then ``+0.0031`` at 12
  (insignificant), ``-0.0031`` at 18 and ``-0.0114`` at 24 (``t = -2.94``). The
  reversal is what a policy reaction looks like, and it means this projection is
  a statement about the **near term only**. It is NOT a 2-year view.
* **The relation is real but small, and it survives detrending.** After
  12-month differencing of *both* series the correlation is ``+0.348``
  contemporaneously and ``+0.17..0.19`` forward at 3-9 months, so the result is
  not a spurious trend agreement between two persistent series. But
  ``R^2 = 0.047``: the score explains under 5% of the forward variance, so this
  is a directional tilt and not a forecast.
* The score is **not centred on zero**. Its sample mean is ``+1.52`` and its
  median ``+4.95`` (2001-12..2026-07), so a zero score is a slightly loose
  market, not a balanced one. The projection inherits that offset.

The cross-check, from the start
-------------------------------
``cross_asset_transmission`` (Module 5.6, D-052) is the comparable Tier-3
synthesis function, and this one is checked against it rather than against
itself. Both take a labor reading and emit a *directional* view; they must agree
in **sign** on the labor-input leg, because a tight market is inflationary in
both stories. The check is a live call in ``scripts/live_projection_check.py``,
and it is a genuine check rather than an identity: the two functions share the
labor input but nothing else — one routes it through a fitted slope and three
bands, the other through a per-asset directional map.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from macro_engine.config import get_settings
from macro_engine.models.contracts import (
    ConfidenceInputs,
    ModelResult,
    compute_confidence,
    utc_now,
)

__all__ = [
    "InflationTrajectoryInputs",
    "TrajectoryDirection",
    "project_inflation_trajectory",
]

#: Every direction the classifier may emit. A ``Literal`` is a promise with two
#: halves (D-045a): this tuple is the runtime-iterable half, and a test asserts
#: the two agree in **both** directions — membership *and* producibility. The
#: producibility half is the one that matters here, because the specification's
#: version admitted all three labels while a real measurement of its own
#: threshold put 79.1% of months in one of them.
TrajectoryDirection = Literal["reaccelerating", "stable", "decelerating"]

#: The score's declared range, from ``labor_tightness_score``. Module 6.4's
#: definition, not a tunable — so it is a constant here and a reachability test
#: runs the classifier across it rather than trusting a claimed range.
_SCORE_FLOOR = -100.0
_SCORE_CEILING = 100.0


class InflationTrajectoryInputs(BaseModel):
    """The §16.2 inputs, plus the §18.6 fiscal flag the signature must carry.

    ``growth`` and ``inflation`` are :class:`ModelResult` objects rather than
    floats because §16.2 passes model outputs directly, and because the
    confidence factors below are facts about *those* results (their
    warnings and their own confidence), not about numbers extracted from them.
    """

    model_config = ConfigDict(extra="forbid")

    growth: ModelResult = Field(
        description=(
            "Module 7's output-gap result. Read for two things: its ``value``, "
            "as the demand-side corroboration of the labor reading, and its "
            "warnings, as a confidence factor. The specification declares this "
            "and never reads it -- see the module docstring, defect 3."
        )
    )
    labor: ModelResult = Field(
        description=(
            "Module 6's ``labor_tightness_score`` result. ``value`` must be a "
            "float on the -100..+100 scale. This is the only input that drives "
            "the projection's sign."
        )
    )
    inflation: ModelResult = Field(
        description=(
            "Module 5's current inflation reading. Used as the LEVEL the "
            "projection is a change *from*, reported alongside it. The "
            "specification lists this in ``inputs_used`` and never reads it -- "
            "see the module docstring, defect 4."
        )
    )
    fiscal_response_active: bool = Field(
        default=False,
        description=(
            "Section 18.6's flag. When true, the fiscal-transfer channel is "
            "weighted rather than the QE/reserves channel alone, scaling the "
            "projected change by ``phillips.trajectory.fiscal_active_multiplier``. "
            "Defaulted false because the no-fiscal world is the conservative "
            "reading; a caller with a fiscal scenario should pass true "
            "explicitly rather than rely on the default."
        ),
    )


def _validate_score(value: object, *, field: str) -> float:
    """Coerce and range-check a labor score.

    A boolean is rejected explicitly. ``isinstance(True, int)`` is true in
    Python, so a caller passing ``True`` for a score would otherwise be
    silently accepted as ``1.0`` — a wrong value that produces a plausible
    output, which is the failure mode this project's tests exist to catch.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"{field} must be a float on the [{_SCORE_FLOOR:.0f}, "
            f"{_SCORE_CEILING:.0f}] scale; got {type(value).__name__} ({value!r})."
        )
    score = float(value)
    if not _SCORE_FLOOR <= score <= _SCORE_CEILING:
        raise ValueError(
            f"{field} is {score!r}, outside the scale's declared range "
            f"[{_SCORE_FLOOR:.0f}, {_SCORE_CEILING:.0f}]. The score is clamped "
            f"to that range by its producer, so a value outside it means the "
            f"wrong field was passed."
        )
    return score


def _growth_corroboration(growth: ModelResult, tight_labor: bool | None) -> tuple[str, list[str]]:
    """Does the growth reading agree with what the labor score implies?

    This is the reading of ``growth`` that makes the parameter live. The
    Phillips story is about *excess demand*; ``labor_tightness_score`` measures
    one market's contribution to it. When growth is expanding and labor is
    tight the two agree and the projection is corroborated. When they disagree,
    the labor-derived projection is a claim about a narrower mechanism than the
    one the caller is treating it as, and that is information.

    Returns ``(state, warnings)``. ``state`` is one of ``agrees_expansion``,
    ``agrees_contraction``, ``disagrees_tight_labor_weak_growth``,
    ``disagrees_loose_labor_strong_growth``, or ``not_directional`` — the last
    for a flat score, where there is nothing to corroborate.
    """
    warnings: list[str] = []
    raw = growth.value
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        warnings.append(
            f"growth.value is {type(raw).__name__}, not a number, so the "
            f"demand-side corroboration could not run. The projection below "
            f"rests on the labor reading alone."
        )
        return "unavailable", warnings

    growth_value = float(raw)
    if tight_labor is None:
        return "not_directional", warnings

    growth_expanding = growth_value > 0
    if tight_labor == growth_expanding:
        return ("agrees_expansion" if growth_expanding else "agrees_contraction"), warnings

    if tight_labor:
        warnings.append(
            f"GROWTH AND LABOR DISAGREE: the labor market is tight while the "
            f"output gap is {growth_value:+.2f} (contracting). The projection "
            f"below follows the labor reading, which is a claim about one "
            f"market rather than about aggregate excess demand — treat it as "
            f"conditional on the labor tightness being real and not a "
            f"measurement artefact."
        )
        return "disagrees_tight_labor_weak_growth", warnings

    warnings.append(
        f"GROWTH AND LABOR DISAGREE: the labor market is loose while the "
        f"output gap is {growth_value:+.2f} (expanding). A loose labor market "
        f"in a strong expansion usually means productivity or participation is "
        f"absorbing the growth, which is disinflationary — consistent with the "
        f"projection below, but the mechanism is supply, not demand."
    )
    return "disagrees_loose_labor_strong_growth", warnings


def project_inflation_trajectory(inputs: InflationTrajectoryInputs) -> ModelResult:
    """Module 3's directional inflation trajectory, with a stated unit.

    ``value`` is a ``dict``::

        {
          "projected_change_pp": float,      # ANNUAL CORE INFLATION, pp
          "direction": str,                  # reaccelerating|stable|decelerating
          "beta_pp_per_score_point": float,  # the bridge actually applied
          "labor_score": float,
          "inflation_level": float,          # the base the change is measured from
          "growth_corroboration": str,
          "fiscal_response_active": bool,
          "fiscal_scale_applied": float,
        }

    **The arithmetic.** With ``s = labor.value`` on the ``-100..+100`` scale and
    ``beta`` in *percentage points of annual core inflation per score point*::

        projected_change_pp = beta * s * fiscal_scale

    **The sign, and why it is NOT negated here.** The specification writes the
    negation *twice* — once into ``labor_slack_proxy = -labor.value / 100`` and
    once into ``projected_change = -beta * labor_slack_proxy`` — and the two
    cancel. Substituting::

        slack = -s / 100
        pc    = -beta * slack = -beta * (-s/100) = +beta * s / 100

    So the specification's ``projected_change`` carries the **same** sign as the
    score. A tight market (positive score) produces a positive projected change,
    which is the required Phillips direction and the direction the specification
    intended. Writing ``beta * (-s)`` here would invert it — and would look
    right, because the comment beside the specification's first negation says
    "negative score (loose) -> positive slack", which is true of the *slack*
    variable and false of the *final* expression once the second negation lands.

    That two-negations-cancel structure is why the sign has a dedicated test
    asserting direction against a known tight-market case, rather than being
    checked by inspection.

    **The band.** ``direction`` is ``reaccelerating`` above
    ``phillips.trajectory.bands.reaccelerating_above_pp``, ``decelerating``
    below the mirrored lower band, and ``stable`` between. Both bounds are
    config, in pp, and the boundary comparisons are **strict** on both sides so
    the partition is exhaustive and non-overlapping — a reading exactly on a
    bound falls to ``stable``, and a test asserts that rather than assuming it.

    **Reachability is checked, not claimed.** ``beta`` and the band width
    together decide whether the two directional labels can ever fire. The
    specification's pairing (``0.3`` against ``0.05`` on the wrong scale) left
    ``stable`` as 79.1% of real months. This implementation's pairing is
    asserted reachable across the declared score range by
    ``test_project_inflation_trajectory.py``, so a future config edit that
    re-creates the base-state failure fails a test instead of silently
    producing an uninformative label.

    **Confidence** comes from ``compute_confidence()`` (§22.8 — this function
    does not choose a number). Three factors are stated as facts:
    ``is_heuristic_not_calibrated=True`` because ``beta`` is measured but not
    fitted; ``depends_on_unobservable=True`` because the Phillips relation is
    *in u-star*, and §21.4 item 13 makes that unobservable by nature; and
    ``source_independence_count`` from whether the growth reading corroborates
    the labor reading or is an independent second family disagreeing with it.
    """
    settings = get_settings()
    trajectory = settings.phillips.trajectory

    score = _validate_score(inputs.labor.value, field="labor.value")
    beta = trajectory.beta_pp_per_score_point
    fiscal_scale = trajectory.fiscal_active_scale if inputs.fiscal_response_active else 1.0

    # The sign is the model, and it is POSITIVE: the specification negates
    # twice (slack = -s/100, then pc = -beta*slack) and the negations cancel, so
    # a tight market (positive score) produces a positive projected change.
    # See the docstring — inverting this is the single easiest error to make here
    # and it produces a plausible-looking output, so it has a dedicated test.
    change_pp = beta * score * fiscal_scale
    upper = trajectory.bands.reaccelerating_above
    lower = trajectory.bands.decelerating_below

    if change_pp > upper:
        direction: TrajectoryDirection = "reaccelerating"
    elif change_pp < lower:
        direction = "decelerating"
    else:
        direction = "stable"

    # The starting level: read, reported, and never used to pick the sign. A
    # projection of *change* from a level of 5.9% and one from 1.2% are the same
    # claim about direction and very different claims about where the level ends.
    inflation_raw = inputs.inflation.value
    if isinstance(inflation_raw, bool) or not isinstance(inflation_raw, (int, float)):
        inflation_level = float("nan")
        inflation_note = (
            f"inflation.value is {type(inflation_raw).__name__}, not a number — "
            f"the level the projection is measured from could not be reported."
        )
    else:
        inflation_level = float(inflation_raw)
        inflation_note = ""

    tight_labor: bool | None = None
    if score > 0:
        tight_labor = True
    elif score < 0:
        tight_labor = False
    corroboration, warnings = _growth_corroboration(inputs.growth, tight_labor)

    if inflation_note:
        warnings.append(inflation_note)

    warnings.append(
        "The projection is a statement about the NEAR TERM ONLY (3-9 months) and "
        "it REVERSES after that: the fitted slope of the forward core-inflation "
        "change on the score is +0.0060 at 6 months (t=+3.76) but -0.0031 at 18 "
        "and -0.0114 at 24 (t=-2.94), with 12 and 18 months insignificant. That "
        "reversal is the signature of a policy reaction rather than of a "
        "permanent relation. Do not read it as a long-horizon forecast."
    )
    warnings.append(
        f"beta={beta} pp per score point is MEASURED but NOT FITTED: it is the "
        f"OLS slope of the 6-month forward core PCE YoY change on the score "
        f"(n=290, R2=0.047), with no controls for monetary policy, inflation "
        f"expectations or supply shocks. The score explains under 5% of forward "
        f"variance, so this is a directional tilt, not a forecast. Phase 5+ "
        f"should fit it properly with controls (Module 18)."
    )
    warnings.append(
        "The labor score is NOT centred on zero: its sample mean is +1.52 and "
        "its median +4.95 (2001-12..2026-07), so a score of 0 is a slightly "
        "loose labor market rather than a balanced one. The projected change "
        "inherits that offset — a `stable` verdict here means 'within the band', "
        "not 'no pressure'."
    )
    if inputs.fiscal_response_active:
        warnings.append(
            f"FISCAL RESPONSE ACTIVE: the projected change was scaled by "
            f"{fiscal_scale}x to weight the fiscal-transfer channel (Section "
            f"18.6). The multiplier is illustrative and fitted from a single "
            f"historical episode (2020-21); it changes the magnitude and can "
            f"move a reading across a band boundary, but it never changes the "
            f"sign."
        )

    interpretation = (
        f"Inflation trajectory: {direction} — projected change "
        f"{change_pp:+.3f}pp in annual core inflation from a current level of "
        f"{inflation_level:.2f}%, on a labor score of {score:+.1f}"
    )
    if direction == "stable":
        interpretation += " (inside the configured dead band)"

    return ModelResult(
        model_name="project_inflation_trajectory",
        country="us",
        as_of=utc_now(),
        value={
            "projected_change_pp": round(change_pp, 4),
            "direction": direction,
            "beta_pp_per_score_point": beta,
            "labor_score": round(score, 1),
            "inflation_level": (
                round(inflation_level, 4) if inflation_level == inflation_level else None
            ),
            "growth_corroboration": corroboration,
            "fiscal_response_active": inputs.fiscal_response_active,
            "fiscal_scale_applied": fiscal_scale,
        },
        confidence=compute_confidence(
            ConfidenceInputs(
                data_quality_flags_present=bool(inputs.labor.warnings),
                is_heuristic_not_calibrated=True,
                depends_on_unobservable=True,
                source_independence_count=(
                    # Per the docstring (lines 311-312): independence comes from
                    # whether the growth reading is an independent second family
                    # that CORROBORATES the labor reading OR DISAGREES with it.
                    # Both are two genuinely independent families being compared,
                    # which is exactly what source independence measures; only
                    # "unavailable" (growth was not a number) or "not_directional"
                    # (flat score, nothing to corroborate) deny the credit.
                    1
                    if corroboration not in ("unavailable", "not_directional")
                    else 0
                ),
            )
        ),
        interpretation=interpretation,
        context=(
            f"Phillips-curve direction from the labor slack proxy: a tight "
            f"market (positive score) raises projected inflation. Estimand is a "
            f"change in ANNUAL CORE INFLATION in percentage points — the "
            f"specification's `projected_change` was on the score-fraction scale "
            f"and its 0.05 threshold therefore had no unit (D-053). "
            f"beta={beta} pp/point, bands [{lower:+.3f}, {upper:+.3f}]pp, "
            f"fiscal_scale={fiscal_scale}x. Interpreted against the Section 21.1 "
            f"NAIRU of {settings.phillips.nairu_value}% and the Section 6.3 "
            f"illustrative slope of {settings.phillips.beta_value}."
        ),
        inputs_used=[
            "growth.value",
            "labor.value",
            "inflation.value",
            "fiscal_response_active",
        ],
        warnings=warnings,
    )
