"""Module 5.4 — the PPI stage-of-processing pipeline signal.

Three stages of the producer price index are published, in the order the real
economy passes costs along: **crude** (raw materials), **intermediate**
(partly processed goods), and **final demand** (finished goods sold to
businesses and consumers). Module 5.4's claim is that when the earlier stage
rises faster than the later ones, cost pressure is *queued* upstream and will
arrive downstream later. When the ordering is reversed, pressure is being
absorbed or is already passing through.

The claim is directionally sound and the specification's test for it is not
-------------------------------------------------------------------------
The specification tests the ordering with a single chained comparison::

    upstream_building = (crude > intermediate > final)

Measured on this build's own three live series — ``WPSID62`` (unprocessed goods
for intermediate demand) as crude, ``WPSID61`` (processed goods for intermediate
demand) as intermediate, and ``PPIFIS`` (final demand) — that strict ordering
holds in **57 of 190 usable months (30.0%, 2010-11 through 2026-08)**. The
looser two-stage comparison ``crude > final`` holds in **84 of 190 (44.2%)**.

Neither is a signal. Both are coin flips, and the strict form is *worse* than a
coin flip. That does not make the economic reasoning wrong; it makes the boolean
uninformative on its own, because a three-way ordering on three independently
noisy year-over-year rates inherits the noise of all three. The corrected
function therefore keeps the flag — it is what the specification asks for and it
is not false — but reports the gradient's **own measured base rate** alongside
it, so the reader is told how often the pattern fires before acting on it. A
boolean delivered without its base rate invites exactly the over-reading that
Section 5.4's "flag, don't fix" discipline exists to prevent. See **D-029**.

What the specification's sample also gets wrong
-----------------------------------------------
1. **Two free ``str`` fields with their permitted values in a comment.**
   ``corporate_margin_trend`` and ``demand_condition`` are declared ``str``, with
   ``# "expanding" | "stable" | "compressing"`` beside them. A caller passing
   ``"Compressing"``, ``"compress"``, or ``"tight"`` gets no error: the value
   falls through every equality test and lands in the ``else`` branch as
   ``"fuller"`` pass-through — an optimistic answer manufactured by a typo.
   This is the same defect class as a misspelled keyword that ``extra="forbid"``
   catches, in a form ``extra="forbid"`` cannot reach, because the field *is*
   provided and *is* a string. Fixed here with ``Literal``, which makes an
   unrecognised value a construction-time error naming the permitted set.

2. **``confidence=0.4``.** Section 22.8 makes ``compute_confidence()`` the only
   confidence producer. Replaced.

3. **``corporate_margin_trend`` is a human assessment, not a series.** Section
   21.4 item 10 lists it in the Loophole Ledger for exactly this reason: there
   is no free margin series this system can read. It is an *input the caller
   supplies from judgement*, so its reliability is not the same as a fetched
   observation's and the output must say so. The other four inputs are published
   series. Treating a judgement call and four observations as equally solid is
   the substitution Section 21.0 rule 4 forbids.

4. **The ordering test has no dead band.** ``>`` is strict, so a month in which
   all three stages grow at exactly 2.0% reports "no clear upstream gradient",
   and one in which they differ by 0.01pp reports that pressure is building.
   Both statements are technically true and neither is useful. A tolerance makes
   the *reporting* honest without changing the underlying comparison. The band
   reports WHICH ordering it contains (``building_within_tolerance`` when the
   strict ordering holds inside the band, ``flat_within_tolerance`` when it does
   not), so a banded month never appears to deny a build the boolean asserts.

Stage-to-series mapping, stated once
------------------------------------
The specification names three stages and no symbols. This build's mapping is::

    crude         -> WPSID62  (PPI: unprocessed goods for intermediate demand)
    intermediate  -> WPSID61  (PPI: processed goods for intermediate demand)
    final demand  -> PPIFIS   (PPI: final demand)

``PPICRM``, the obvious-looking "crude materials for further processing" series,
was **discontinued by BLS in 2015-12** and cannot be used. ``WPSID62`` is the
live crude-stage equivalent. The mapping is recorded in
``config/series_registry.yaml`` and exercised live in
``scripts/live_labor_check.py``.

Units note: the three indices have **different base years** (1982=100 for both
``WPSID*`` series, Nov 2009=100 for ``PPIFIS``). That is immaterial here because
every input is a *year-over-year percent change of its own index* — a base-year
convention cancels in a same-series ratio. It would matter immediately if the
levels were compared across stages, which is why the levels are never combined.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field

from macro_engine.config import get_settings
from macro_engine.models.contracts import (
    ConfidenceInputs,
    FiniteInputs,
    ModelResult,
    compute_confidence,
    utc_now,
)

__all__ = [
    "MarginTrend",
    "PPIPipelineInputs",
    "PipelinePassThrough",
    "ppi_pipeline_signal",
]

# The permitted values, as types rather than comments. ``Literal`` is what makes
# a typo a construction-time error instead of a silent fall-through to the
# optimistic branch.
MarginTrend = Literal["expanding", "stable", "compressing"]
DemandCondition = Literal["strong", "neutral", "weak"]

# Pass-through is reported as one of these. Deliberately only two states: the
# specification's binary, kept because inventing a middle state would imply a
# precision the margin input cannot support (it is a human assessment).
PipelinePassThrough = Literal["muted", "fuller"]


class PPIPipelineInputs(FiniteInputs):
    """Inputs to ``ppi_pipeline_signal`` (Module 5.4).

    The three percentages are year-over-year growth rates of the three stage
    indices, **at the same observation date**. Passing each stage's own latest
    reading is the pairing defect D-009 describes: ``PPIFIS`` begins in 2009-11
    while the ``WPSID*`` series reach back to 1947, so the common window is
    bounded by the youngest series and a caller who does not align on a common
    date can difference stages that are not contemporaneous.

    D-139: inherits ``FiniteInputs``. Measured before the fix,
    ``ppi_pipeline_signal(crude_stage_yoy_pct=nan)`` published
    ``upstream_pressure_building=False`` with ``stage_spread_pp=nan`` — a
    confident "no upstream cost pressure" verdict from a comparison that never
    ran, because every ``nan`` comparison is ``False`` (D-078's class).
    """

    model_config = ConfigDict(extra="forbid")

    crude_stage_yoy_pct: float = Field(
        description=(
            "Year-over-year percent change in the crude-stage index "
            "(registry: WPSID62, unprocessed goods for intermediate demand)."
        ),
    )
    intermediate_stage_yoy_pct: float = Field(
        description=(
            "Year-over-year percent change in the intermediate-stage index "
            "(registry: WPSID61, processed goods for intermediate demand)."
        ),
    )
    final_demand_yoy_pct: float = Field(
        description=("Year-over-year percent change in the final-demand index (registry: PPIFIS)."),
    )
    corporate_margin_trend: MarginTrend = Field(
        description=(
            "Human assessment (Section 21.4 item 10 — no free series exists). "
            "Constrained to the specification's three literals: an unrecognised "
            "value would otherwise fall through to the optimistic branch."
        ),
    )
    demand_condition: DemandCondition = Field(
        description=(
            "Human assessment of demand conditions. Constrained to the "
            "specification's three literals, for the same reason as "
            "''corporate_margin_trend''."
        ),
    )


def ppi_pipeline_signal(inputs: PPIPipelineInputs) -> ModelResult:
    """Report the PPI stage gradient and the expected pass-through. ``value``: ``dict``.

    ``value`` is a dict with these keys:

    ``upstream_pressure_building``
        ``bool`` — the specification's strict ordering test, reported as-is.
    ``gradient_direction``
        ``str`` — a restatement of the same comparison in five states, so it is
        never in conflict with ``upstream_pressure_building``. ``building_upstream``
        and ``passing_through_downstream`` are the two monotonic orderings at a
        separation larger than the dead band; ``non_monotonic`` is a genuine
        three-way scramble (``crude > final > intermediate`` and its reverses);
        and the two **within-band** states exist precisely so a ``True`` boolean
        is never paired with a direction that reads as a denial:

        * ``building_within_tolerance`` — the strict ordering HOLDS but both
          adjacent gaps are inside the dead band (e.g. ``2.06 > 2.05 > 2.04``).
          The boolean is ``True`` and says so.
        * ``flat_within_tolerance`` — the stages are inside the band and the
          ordering is not strict (e.g. ``2.0, 2.0, 2.0`` or ``2.0, 2.04, 2.02``).
          The boolean is ``False``.

        The invariant the earlier three-state version broke:
        ``gradient_direction == "building_upstream"`` ⟺
        ``upstream_pressure_building is True`` **is false** — the biconditional
        is the WRONG invariant once a dead band exists, because the band can
        hold on a strictly-descending ordering. What is true, and what this
        five-state version guarantees, is the one-directional implication
        ``upstream_pressure_building is True`` ⟹ the direction is one of the two
        *building* states (never ``no*``/``flat*``/``passing*``/``non_monotonic``).
    ``expected_pass_through``
        ``"muted" | "fuller"`` — the specification's binary.
    ``base_rate_strict_descending``
        ``float`` — measured share of months in which the strict ordering held
        (30.0% on this build). See D-029.
    ``base_rate_crude_above_final``
        ``float`` — measured share for the looser two-stage form (44.2%).
    ``stage_spread_pp``
        ``float`` — ``crude - final``, the headline size of the gradient.

    Hand calculation. Take the live readings at 2026-08-01: crude ``+13.06%``,
    intermediate ``+11.53%``, final demand ``+5.41%``::

        strict descending  13.06 > 11.53 > 5.41         -> True
        stage spread       13.06 - 5.41                 -> +7.65pp
        demand_condition   "neutral"   (neither strong nor weak)
        margin_trend       "expanding" (not compressing)
        pass_through       -> "fuller"

    And the reversed case, which is the one the wording is easy to get wrong:
    crude ``+1.00%``, intermediate ``+2.00%``, final ``+3.00%``::

        strict descending  1.00 > 2.00                  -> False (first test fails)
        stage spread       1.00 - 3.00                  -> -2.00pp
        pass_through       depends only on the two assessments, NOT on the gradient

    ``pass_through`` is a function of ``demand_condition`` and
    ``corporate_margin_trend`` alone. A rising gradient with weak demand still
    reports ``"muted"``, because margin absorption is what breaks the link — the
    specification is explicit that pass-through is not 1:1, and it would defeat
    the point of the model to let the gradient override the absorption term.

    ``confidence`` comes from ``compute_confidence()`` and carries
    ``is_heuristic_not_calibrated=True`` (the margin and demand fields are
    judgements, and the ordering test is not calibrated) and
    ``depends_on_unobservable=True`` (the margin trend is not directly observed
    by this system at all — Section 21.4 item 10).
    """
    settings = get_settings()
    base_rate = settings.inflation.pipeline_base_rate

    crude = inputs.crude_stage_yoy_pct
    intermediate = inputs.intermediate_stage_yoy_pct
    final = inputs.final_demand_yoy_pct

    # The specification's test, reported unchanged so a caller comparing against
    # the spec sees the same boolean it would have computed.
    upstream_building = crude > intermediate > final
    stage_spread = crude - final

    # A three-state restatement using a dead band. The sum of absolute adjacent
    # gaps is the right width to compare against, because a gradient only exists
    # if the stages are separated; when all three sit within the tolerance of
    # each other there is no ordering to speak of.
    #
    # The band is a REPORTING fact, not a re-decision of the boolean. The
    # boolean keeps the specification's strict test (`crude > intermediate >
    # final`); the direction says where the stages sit. Those two must not
    # contradict: the earlier version returned the bare "no_clear_gradient" for
    # every within-band reading, which paired a `True` boolean with a direction
    # that reads as "there is no gradient" — the exact contradiction D-009's
    # cross-field identity forbids. The band now reports WHICH ordering it is
    # inside, so a strictly-descending-but-tight month says
    # "building_within_tolerance" rather than denying the build.
    tolerance = settings.inflation.pipeline_gradient_tolerance
    within_band = abs(crude - intermediate) <= tolerance and abs(intermediate - final) <= tolerance
    if within_band:
        gradient_direction = (
            "building_within_tolerance" if upstream_building else "flat_within_tolerance"
        )
    elif upstream_building:
        gradient_direction = "building_upstream"
    elif crude < intermediate < final:
        gradient_direction = "passing_through_downstream"
    else:
        gradient_direction = "non_monotonic"

    # Pass-through depends on the two assessments only. See the docstring.
    absorbing = inputs.demand_condition == "weak" or inputs.corporate_margin_trend == "compressing"
    pass_through: PipelinePassThrough = "muted" if absorbing else "fuller"

    direction_text = (
        "Upstream cost pressure building" if upstream_building else "No clear upstream gradient"
    )

    warnings = [
        "PPI is NOT a 1:1 CPI predictor — margin absorption breaks the link "
        "(Module 5.4). The pass-through label reports which way absorption "
        "points; it is not a magnitude and must not be read as one.",
        f"The stage gradient's own base rate: the strict ordering "
        f"crude > intermediate > final held in "
        f"{base_rate.strict_descending_rate:.1%} of the 190 months this build "
        f"can measure (2010-11 through 2026-08), and the looser crude > final "
        f"held in {base_rate.crude_above_final_rate:.1%}. A reading of "
        f"'building' is therefore NOT evidence of an unusual state — it is the "
        f"less common of two near-coin-flip outcomes. See D-029.",
        "``corporate_margin_trend`` is a HUMAN ASSESSMENT, not an observation "
        "(Section 21.4 item 10). No free margin series exists for this system to "
        "read, so one of the five inputs — and one of the two that decides "
        "pass-through — carries judgement reliability rather than series "
        "reliability. The four price stages are published data; this field is "
        "not, and the two are not interchangeable.",
        "Stage-to-series mapping is a this-build choice, not a BLS identity: "
        "crude = WPSID62, intermediate = WPSID61, final demand = PPIFIS. "
        "'Crude' here means unprocessed goods FOR INTERMEDIATE DEMAND, which is "
        "the closest live equivalent to the crude stage — the explicit "
        "'crude materials for further processing' index (PPICRM) was "
        "discontinued by BLS after 2015-12 and is unusable.",
        # The band is a reporting fact, and when it fires the two adjacent gaps
        # are at or below the input's own precision. Saying so plainly is the
        # point of the band; the earlier bare "no clear gradient" wording
        # reported a strictly-ordered month as if there were no ordering.
        f"A {tolerance:.2f}pp dead band separates the stages: when both adjacent "
        f"gaps sit inside it the direction names the ordering only at the "
        f"band's resolution, because a separation at the inputs' own 2dp "
        f"precision cannot support a stronger claim than the ordering itself. "
        f"``upstream_pressure_building`` still reports the specification's "
        f"strict test unchanged.",
    ]

    # The within-band BUILD is the case the earlier version mislabelled: a
    # strictly-descending month whose gaps are tiny took the bare
    # "no clear gradient" and so appeared to deny a build the boolean asserted.
    # Naming it here is what keeps the two fields from contradicting.
    if gradient_direction == "building_within_tolerance":
        warnings.append(
            "The stages are strictly ordered the building way (crude > "
            "intermediate > final) but both adjacent gaps are inside the "
            f"{tolerance:.2f}pp dead band. The ordering is real and the boolean "
            "says so; the SEPARATION is at the inputs' reporting precision, so "
            "treat the gradient as a rounding-level ordering rather than a "
            "measured build."
        )

    # A judgement call that contradicts the price data is worth naming: the
    # stages say pressure is arriving while the caller says margins are
    # expanding, which is the combination where the two inputs disagree about
    # the same question.
    if upstream_building and inputs.corporate_margin_trend == "expanding":
        warnings.append(
            "The price stages show pressure building upstream while the margin "
            "assessment says margins are EXPANDING. Those pull in opposite "
            "directions: building upstream costs with expanding margins implies "
            "the margin call expects costs to be passed on fully, or expects "
            "the gradient to reverse. Reconcile before relying on either."
        )

    # The reversed ordering is the informative case for downstream CPI: costs
    # are already reaching finished goods rather than queued behind them.
    if gradient_direction == "passing_through_downstream":
        warnings.append(
            "The gradient is inverted (crude < intermediate < final demand), so "
            "cost pressure is arriving downstream rather than queued behind it. "
            "For inflation this is the more immediately relevant ordering — the "
            "pressure is already in finished-goods prices — and it is the case "
            "Module 5.4's wording describes least directly."
        )

    if gradient_direction == "non_monotonic":
        warnings.append(
            "The three stages are not monotonically ordered (one stage breaks "
            "the sequence). This is the most common outcome — the strict "
            "test is False and the inverted order is not satisfied either — and "
            "it means the pipeline is not transmitting in one consistent "
            "direction this month. Treat a non-monotonic reading as 'no signal' "
            "rather than resolving it by ignoring whichever stage disagrees."
        )

    if gradient_direction == "flat_within_tolerance":
        warnings.append(
            f"The three stages sit within the {tolerance:.2f}pp dead band of one "
            f"another without a strict ordering: the cheapest and dearest stages "
            f"are {stage_spread:+.2f}pp apart. There is no directional gradient "
            f"to read this month, and the boolean is False. This is a genuine "
            f"'no gradient', distinct from the within-band case where the "
            f"ordering DOES hold — the direction names which of the two it is so "
            f"the boolean and the label cannot appear to disagree."
        )

    if abs(stage_spread) <= tolerance:
        warnings.append(
            f"Crude and final demand are within {tolerance:.2f}pp of each other "
            f"({stage_spread:+.2f}pp), so there is effectively no gradient "
            f"between the ends of the pipeline regardless of where the "
            f"intermediate stage sits."
        )

    return ModelResult(
        model_name="ppi_pipeline_signal",
        country="us",
        as_of=utc_now(),
        value={
            "upstream_pressure_building": upstream_building,
            "gradient_direction": gradient_direction,
            "expected_pass_through": pass_through,
            "base_rate_strict_descending": base_rate.strict_descending_rate,
            "base_rate_crude_above_final": base_rate.crude_above_final_rate,
            "stage_spread_pp": round(stage_spread, 2),
        },
        confidence=compute_confidence(
            ConfidenceInputs(
                is_heuristic_not_calibrated=True,
                depends_on_unobservable=True,
            ),
        ),
        interpretation=(
            f"{direction_text}; expected pass-through to CPI: {pass_through} "
            f"(crude {crude:+.2f}%, intermediate {intermediate:+.2f}%, final "
            f"demand {final:+.2f}%, spread {stage_spread:+.2f}pp)"
        ),
        context=(
            f"Crude > Intermediate > Final Demand gradient signals pressure "
            f"moving downstream (Module 5.4). Measured base rate for that "
            f"ordering is {base_rate.strict_descending_rate:.1%}, so the flag is "
            f"reported with its own frequency rather than as a rare event. "
            f"Pass-through is driven by demand_condition="
            f"'{inputs.demand_condition}' and corporate_margin_trend="
            f"'{inputs.corporate_margin_trend}' alone, not by the gradient."
        ),
        inputs_used=[
            "crude_stage_yoy_pct",
            "intermediate_stage_yoy_pct",
            "final_demand_yoy_pct",
            "corporate_margin_trend",
            "demand_condition",
        ],
        warnings=warnings,
    )
