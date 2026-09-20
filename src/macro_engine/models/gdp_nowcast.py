"""GDP nowcasting and the output gap (AGENTS.md Module 7, Section 6.5).

Three functions live here, in Section 21.3's tier order:

* ``output_gap`` — **Tier 1**, no dependencies beyond the snapshot. Pure
  arithmetic on live data, and therefore the correct first function to
  implement in Phase 2.
* ``gdp_gdi_divergence`` — **Tier 2**, Module 7.1. The income- versus
  expenditure-side discrepancy. Takes two growth rates rather than reading the
  snapshot, because the discrepancy is a residual whose *sign* is meaningless
  and whose *magnitude* is the only usable content (D-031).
* ``simple_gdp_nowcast`` — **Tier 2**, Module 7.5. The expenditure-approach
  proxy Section 6.5 supplies. **Four defects in that specification's formula
  were measured on live data before this was written, and the measurement
  produced a fifth finding that matters more than any of them**: one quarter
  ahead, the correction fixes the adjustment's *sign* (its delta correlates
  +0.173 with the change it predicts, where the specification's correlates
  -0.057) but the adjustment carries half the magnitude of the movement while
  explaining only 3% of its variance — so applying it at full weight costs
  0.11pp of accuracy. The function reports its own error, its benchmark, and
  that over-weighting ratio alongside its estimate. See D-034 and its correction
  D-035.

Scope and honesty about it (Section 22.3 / Finding #3)
------------------------------------------------------
Every function here is US-scoped. ``country`` is a **label, not a
generalization**: this module's logic depends on CBO's potential-output
methodology and on FRED's ``GDPC1``/``GDPPOT`` series. Claiming it works for
``de`` would require Germany's own potential-output estimate and its own
national-accounts conventions, neither of which exists in this codebase.

The economic question `output_gap` answers
------------------------------------------
*Is the economy producing above or below its sustainable capacity, and by how
much?* -- Section 15 Module 7 frames this as the direct input to the Taylor
Rule's ``(y - y*)`` term and to ``growth_view``, and as the subject of Q1
(current growth state) and Q6 (is the gap large enough to matter, given
potential-GDP estimation uncertainty).

Why this function is more dangerous than its one-line formula suggests
--------------------------------------------------------------------
``(actual - potential) / potential * 100`` has three failure modes, each of
which produces a plausible number rather than an error:

1. **Using a forward projection as current capacity (O-7).** ``GDPPOT`` carries
   CBO projections roughly a decade ahead — on the 2026-09-16 snapshot, 52 of
   its 62 points were dated in the future. ``points[-1]`` would compute the gap
   against the **Q4 2036** projection. Handled by ``observation_as_of`` from
   ``models/as_of.py``.

2. **Pairing mismatched quarters (D-009).** ``GDPPOT`` runs one quarter *ahead*
   of ``GDPC1``. Taking each series' own latest realised point subtracts Q2
   2026 actual output from a Q3 2026 capacity estimate, which measures one
   quarter of growth rather than the level of slack — and inverted the sign of
   the answer on live data (+0.29% instead of +0.83%). Handled by
   ``_latest_common_pair``: the gap is a same-quarter comparison or it is not
   an output gap.

3. **Rounding and units.** Both series are real GDP in billions of chained
   dollars, but ``GDPC1`` is **seasonally adjusted at an annual rate** while
   ``GDPPOT`` is **not seasonally adjusted** (verified on FRED 2026-09-16).
   The ratio is what matters and the two are published on the same
   chained-dollar basis, so the gap is usable; the seasonality difference is a
   known limitation rather than a correction, because a seasonally unadjusted
   *potential* series has no seasonal component to remove — potential output is
   a counterfactual, not a measurement. The units check below still guards
   against an order-of-magnitude mis-mapping.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from macro_engine.data_layer.schemas import MacroDataSnapshot, ObservationPoint
from macro_engine.models.as_of import observation_as_of
from macro_engine.models.contracts import (
    ConfidenceInputs,
    ModelResult,
    compute_confidence,
    utc_now,
)

if TYPE_CHECKING:
    from macro_engine.config import GdpGdiSettings, GdpNowcastSettings

__all__ = [
    "GdpGdiInputs",
    "OutputGapInputs",
    "OutputGapSeriesReport",
    "SimpleGDPNowcastInputs",
    "gdp_gdi_divergence",
    "output_gap",
    "output_gap_from_snapshot",
    "simple_gdp_nowcast",
]


class OutputGapInputs(BaseModel):
    """Inputs to ``output_gap`` (Section 6.5).

    ``actual_gdp`` and ``potential_gdp`` are both real GDP in billions of
    chained dollars. The unit is stated because the ratio is dimensionless but
    the subtraction is not: mixing a nominal figure in would inflate the gap by
    the deflator (~4.5% on the 2026-09-16 snapshot) with nothing in the output
    to indicate it.
    """

    model_config = ConfigDict(extra="forbid")

    actual_gdp: float = Field(
        description=(
            "Real GDP, same units as potential_gdp. FRED GDPC1 (billions, chained 2017 USD)."
        ),
    )
    potential_gdp: float = Field(
        gt=0.0,
        description=(
            "Real POTENTIAL GDP, same units as actual_gdp. FRED GDPPOT (CBO). "
            "Constrained positive: it is a denominator and a production-capacity "
            "level, and a zero or negative value would make the ratio meaningless "
            "or silently invert the sign of the result."
        ),
    )


def _gap_direction_sentence(gap_pct: float) -> str:
    """The output gap's sign, in words, for the Section 3 ``direction`` field.

    A named function for the same reason the builder has one: the sign is
    load-bearing and trivially invertible. A POSITIVE output gap means the
    economy is running ABOVE sustainable capacity — which is expansionary in
    activity terms but *inflationary*, and is the sense the Taylor Rule's
    (y-y*) term expects. Writing "positive = good" would be a reading the
    model does not support.

    Exact zero is separated as a THIRD state rather than left to a branch's
    ``else`` (the D-040 defect class), because "at potential" is a real
    reading and not a rounding of either direction.
    """
    if gap_pct == 0:
        return "neutral: at potential"
    if gap_pct > 0:
        return "expansionary: economy above sustainable capacity (inflationary pressure)"
    return "slack: economy below sustainable capacity (disinflationary pressure)"


def output_gap(inputs: OutputGapInputs) -> ModelResult:
    """Output gap in percent of potential (AGENTS.md Section 6.5, Module 7).

    Implements the specified formula exactly::

        gap_pct = (actual_gdp - potential_gdp) / potential_gdp * 100

    Value type
    ----------
    ``float``. Two decimal places, per the specification's ``round(gap_pct, 2)``.

    Confidence
    ----------
    **Computed, not asserted.** Section 6.5 writes ``confidence=0.5`` with the
    comment "potential GDP itself is an estimate". Section 22.8 replaces that
    literal with ``compute_confidence()``, and the specification's own four
    factors map onto the stated inputs exactly:

    * ``depends_on_unobservable=True`` — potential GDP is the canonical
      unobservable (Section 21.4 item 13). This is the factor the
      specification's comment was reaching for.
    * ``data_quality_flags_present`` — set by the caller when the snapshot
      carrying these values was flagged.
    * ``source_independence_count`` — the number of genuinely independent
      source families behind the inputs (Module 13). A single-provider,
      single-methodology pair is not corroboration.
    * ``is_heuristic_not_calibrated`` — left to the caller, since whether the
      underlying potential-output estimate is calibrated is a fact about the
      estimate's provenance rather than about this arithmetic.

    The resulting value will land **at or below** the specification's 0.5 for a
    bare two-input call, which is the correct direction: the spec's literal was
    already meant to express "this is not a measurement", and the computed form
    says it without a magic number.

    Warnings
    --------
    Always carries the potential-GDP-is-an-estimate warning. Conditionally adds
    a warning when real GDP and potential GDP are dated differently, because a
    gap computed across mismatched vintages is not the gap the caller thinks it
    is — the magnitude of that date difference is the caller's evidence for
    judging it.

    Parameters
    ----------
    inputs:
        ``OutputGapInputs``. Note there is no snapshot parameter: the
        snapshot-to-inputs conversion happens in
        ``output_gap_from_snapshot``, which is where the O-7 horizon filter is
        applied. Keeping the arithmetic function pure is what makes the
        hand-verified golden test a genuine test of the formula rather than of
        the plumbing.
    """
    gap_pct = (inputs.actual_gdp - inputs.potential_gdp) / inputs.potential_gdp * 100

    relation = "above" if gap_pct > 0 else "below"

    warnings = [
        "Potential GDP is a Cobb-Douglas production-function ESTIMATE, not observed "
        "— Module 7.2. The output gap inherits that uncertainty; it is not a "
        "measurement and must not be presented as one.",
    ]

    return ModelResult(
        model_name="output_gap",
        country="us",
        as_of=utc_now(),
        value=round(gap_pct, 2),
        confidence=compute_confidence(
            ConfidenceInputs(
                # Potential GDP is unobservable by nature (Section 21.4 item 13).
                depends_on_unobservable=True,
                # Two inputs drawn from one provider are one source, not two.
                # Genuine independence would require a second potential-output
                # methodology, which this system does not have.
                source_independence_count=0,
            )
        ),
        interpretation=(
            f"Output gap: {gap_pct:+.2f}% ({relation} potential)"
            if gap_pct != 0
            else "Output gap: 0.00% (at potential)"
        ),
        context=(
            f"Actual={inputs.actual_gdp}, Potential={inputs.potential_gdp}. "
            f"Positive = economy running above sustainable capacity, which is the "
            f"sign the Taylor Rule's (y-y*) term expects."
        ),
        inputs_used=["actual_gdp", "potential_gdp"],
        warnings=warnings,
        # --- Section 3/4: the reasoning object, populated -------------------
        unit="percent of potential",
        direction=_gap_direction_sentence(gap_pct),
        assumptions=[
            "Potential GDP is a Cobb-Douglas production-function ESTIMATE, not an "
            "observation. The gap inherits whatever error that estimate carries, "
            "and the estimate is REVISED — so the gap for a past quarter changes "
            "as the estimate is updated.",
            "The two series are declared in identical units in the registry "
            "(billions of chained 2017 USD), but they are not identically "
            "seasonally adjusted: GDPC1 is SAAR while GDPPOT is NSA. The ratio is "
            "unit-free so the gap remains computable, but a seasonal wedge is not "
            "removed by it.",
            "A positive gap is treated as 'above sustainable capacity', which is "
            "the sign the Taylor Rule's (y-y*) term expects. A reader who uses "
            "the gap for a purpose with the opposite sign convention (a Phillips "
            "curve in the unemployment direction) must invert it.",
        ],
        data_provenance=[
            "actual_gdp — GDPC1 (BEA real GDP, chained 2017 USD, SAAR) via FRED, "
            "filtered to observation_date <= snapshot.as_of (O-7 horizon filter)",
            "potential_gdp — GDPPOT (CBO potential real GDP) via FRED, same "
            "filter; CBO publishes projections, so this series carries "
            "forward-dated points that the O-7 filter withholds",
            "Both series paired on their LATEST COMMON quarter (D-009); taking "
            "each series' own latest point would subtract Q2 actual from Q3 "
            "capacity and invert the sign of the gap",
        ],
        limitations=[
            "NOT A MEASUREMENT OF SLACK. This is a ratio of two model outputs, "
            "one of which (potential) is unobservable by nature (Section 21.4 "
            "item 13). It is an estimate whose error is dominated by the "
            "potential-output methodology, not by the arithmetic.",
            "REVISION-DEPENDENT: both inputs are subject to BEA and CBO "
            "revisions, so the gap for a given quarter is not stable over time. "
            "A backtest that reads today's vintage of a past gap is reading a "
            "number that was not available at the time.",
            "The one-quarter change in this gap is what makes `recovery` "
            "reachable in the regime classifier, and that change is computed "
            "across two vintages that may each have been revised — so a "
            "direction of travel can be an artifact of revision rather than of "
            "the economy.",
            "Points-in-time: the O-7 filter is applied on "
            "``observation_date <= as_of``, which is SUFFICIENT BUT NOT SOUND "
            "(see models/as_of.py) — a revised vintage of an old observation "
            "passes the filter. No release or vintage datetime is available on "
            "this installation (Section 6, measured 2026-09-19).",
        ],
        decision_relevance=(
            "Section 16.2's Q1 growth read, and the input to the Module 3 regime "
            "classifier's growth axis. Also the (y-y*) term of the Taylor-rule "
            "family, so it enters the model-implied policy path and therefore the "
            "gap the significance test (Q6) compares against market pricing."
        ),
        decision_prohibition=[
            "MUST NOT be read as a measured quantity with an error band: it is "
            "the ratio of an observation to an ESTIMATE. Reporting it to two "
            "decimals does not make the second decimal meaningful.",
            "MUST NOT be used alone to call a recession. The Module 3 classifier "
            "combines this with the unemployment gap for corroboration, and "
            "Section 12 requires the disagreement between the two slack measures "
            "to be investigated rather than averaged away.",
            "MUST NOT be compared across snapshots of different vintage without "
            "recording both vintages. A gap that moved 0.2pp may have moved "
            "because the economy changed or because CBO revised potential, and "
            "this field cannot distinguish them.",
        ],
    )


# ---------------------------------------------------------------------------
# Snapshot adapter — where O-7 is closed
# ---------------------------------------------------------------------------


class OutputGapSeriesReport(BaseModel):
    """Which observations `output_gap_from_snapshot` used, and which it withheld.

    Carried out of the adapter rather than logged into the void because the
    truncation is a material fact about the answer. On a live 2026-09-20
    snapshot ``withheld_forward_points`` is 41 (the CBO projection block, which
    runs to 2036-10-01) and ``withheld_unpaired_points`` is 1 (the realised
    2026-07-01 potential estimate, waiting on its actual-GDP print); the two are
    reported separately and sum via ``withheld_potential_points``. 0 forward
    points would mean the projection block vanished from the series, which is
    worth noticing.

    The two counts were once a single sum (D-076). See
    ``withheld_potential_points`` for why a stored total was the wrong shape.
    """

    model_config = ConfigDict(extra="forbid")

    as_of: datetime
    actual_date: str
    potential_date: str
    actual_value: float
    potential_value: float
    #: Points dated strictly AFTER as_of — the forward-dated CBO projection
    #: block. This is the category the O-7 horizon filter exists to exclude, and
    #: it is `observation_as_of(...).withheld` verbatim.
    withheld_forward_points: int
    withheld_horizon: str | None = None
    #: Points dated on or before as_of but excluded because they post-date the
    #: latest actual-GDP print. These are *not* projections in the publication
    #: sense — a potential estimate for a quarter whose actual output is not
    #: yet published still belongs to a completed quarter — but they cannot be
    #: paired with a matching actual, so they are unusable for a same-quarter
    #: gap. Kept separate from the projection count because the two have
    #: different meanings and different remedies.
    withheld_unpaired_points: int = 0
    #: Set when gdp_real's latest observation is itself older than the latest
    #: potential estimate by more than one quarter, which indicates a stale
    #: actual-GDP fetch rather than a normal publication lag.
    staleness_quarters: int = 0

    @property
    def withheld_potential_points(self) -> int:
        """Every point the adapter withheld from ``gdp_potential``.

        The sum of the two reasons, which are disjoint by construction: a point
        is either dated after ``as_of`` (a projection) or dated on or before it
        (realised). Kept as a derived property rather than stored, because a
        stored total is a second number that can disagree with its parts — and
        did (D-076): ``withheld_forward_points`` held this sum while its name
        and its warning said "forward-dated", reporting 42 projections where
        the series contained 41.
        """
        return self.withheld_forward_points + self.withheld_unpaired_points

    def warnings(self) -> list[str]:
        """Every condition this adapter exists to make visible.

        Section 21.2 Step 5: each of these must be triggerable in a test.
        """
        messages: list[str] = []
        if self.withheld_forward_points:
            horizon = f" to {self.withheld_horizon}" if self.withheld_horizon else ""
            messages.append(
                f"gdp_potential: {self.withheld_forward_points} forward-dated CBO "
                f"projection(s){horizon} withheld; only observations dated on or before "
                f"{self.as_of.date().isoformat()} were used as realised capacity (O-7)."
            )
        if self.withheld_unpaired_points:
            messages.append(
                f"gdp_potential extends {self.withheld_unpaired_points} quarter(s) beyond the "
                f"latest actual-GDP observation. The gap is computed at the latest quarter where "
                f"BOTH series have an observation ({self.actual_date}), not at each series' own "
                f"latest point — pairing Q2 actual against Q3 potential would measure one "
                f"quarter's growth rather than the level of slack."
            )
        if self.staleness_quarters > 1:
            messages.append(
                f"gdp_real's latest observation ({self.actual_date}) is {self.staleness_quarters} "
                f"quarter(s) behind gdp_potential's — wider than the normal one-quarter "
                f"publication lag. Check the build report for a stale or failed actual-GDP fetch."
            )
        return messages


def _latest_common_pair(
    actual_points: list[ObservationPoint],
    potential_points: list[ObservationPoint],
    *,
    as_of: datetime,
) -> tuple[ObservationPoint, ObservationPoint, int, int]:
    """The latest quarter in which BOTH series have an observation.

    Why this exists — a defect found by real-data execution (D-009)
    ---------------------------------------------------------------
    The first implementation took each series' own latest realised point
    independently. Against a live 2026-09-16 snapshot that produced:

        actual    = 24,269.613 @ 2026-04-01  (GDPC1, Q2 2026)
        potential = 24,200.445 @ 2026-07-01  (GDPPOT, Q3 2026)
        gap       = +0.29%  "above potential"

    That number is wrong, and wrong in the dangerous way: it is plausible, it
    is small, and it inverts the sign of the true gap.

    The cause is a **publication-cadence asymmetry**, not a filter bug. CBO's
    ``GDPPOT`` runs one quarter ahead of FRED's ``GDPC1`` — on this snapshot the
    latest realised potential estimate is Q3 2026 while the latest actual GDP
    print is Q2 2026. Subtracting Q2 actual from Q3 potential does not measure
    the output gap; it measures the economy's growth between Q2 actual and a
    Q3 *estimate of capacity*, which is a different quantity with a different
    sign behaviour.

    And this was not visible from the specimen alone. The snapshot's other
    signals — unemployment 4.10%, slowing payrolls, a curve pricing a
    policy easing — are all consistent with a small *negative* gap. The
    independently computed paired history shows the gap has been positive but
    shrinking (+1.52% → +0.83% over seven quarters), which is a defensible
    reading of a late-cycle economy at roughly potential. The paired answer
    (+0.83%) and the cross-checked history agree; the unpaired answer (+0.29%)
    agrees with nothing.

    So the rule is: **the output gap is a same-quarter comparison or it is not
    an output gap.** Both series are filtered to ``as_of`` (O-7), then to their
    intersection, then the latest common date is taken.

    Returns
    -------
    (actual, potential, withheld_unpaired, staleness_quarters)
        The two paired observations, the number of potential points dated on or
        before ``as_of`` but after the paired date, and how many quarters the
        actual series trails the potential series by.
    """
    actual_series = observation_as_of(actual_points, as_of=as_of, series_id="gdp_real")
    potential_series = observation_as_of(potential_points, as_of=as_of, series_id="gdp_potential")

    if actual_series.is_empty:
        raise ValueError(
            f"'gdp_real' has no observations dated on or before {as_of.date().isoformat()} "
            f"({len(actual_points)} point(s) total). No realised actual GDP exists at this "
            f"instant, so no output gap can be computed."
        )
    if potential_series.is_empty:
        raise ValueError(
            f"'gdp_potential' has no observations dated on or before {as_of.date().isoformat()} "
            f"({len(potential_points)} point(s) total). Every point is future-dated — it carries "
            f"no realised capacity estimate at this instant, so no output gap can be computed."
        )

    actual_by_date = {p.observation_date: p for p in actual_series.points}
    potential_by_date = {p.observation_date: p for p in potential_series.points}
    common_dates = sorted(set(actual_by_date) & set(potential_by_date))

    if not common_dates:
        raise ValueError(
            "gdp_real and gdp_potential share no observation date on or before "
            f"{as_of.date().isoformat()} — {len(actual_series.points)} actual vs "
            f"{len(potential_series.points)} potential point(s) with no overlap. A same-quarter "
            "output gap is impossible from these series as fetched; this indicates a mapping or "
            "frequency fault, not an economic condition."
        )

    pair_date = common_dates[-1]
    actual = actual_by_date[pair_date]
    potential = potential_by_date[pair_date]

    # Potential points that survived the as-of filter but are later than the
    # pair date: the one-quarter (or more) head start. Counted against the
    # latest *realised* potential estimate only — the projection block is
    # accounted for separately by the O-7 horizon filter, and conflating the two
    # would report a decade of projections as "quarters the actual series is
    # behind".
    latest_realised_potential = max(potential_by_date)
    pending_potential = sorted(d for d in potential_by_date if d > pair_date)
    withheld_unpaired = len(pending_potential)

    # How many quarters the paired period trails the latest realised potential
    # quarter, measured as a date difference rather than a point count: a point
    # count silently assumes every quarter is present, and a gap in the series
    # (a skipped observation) would then understate the lag. One quarter is the
    # normal publication lag; more indicates a stale actual-GDP fetch.
    staleness_quarters = _quarters_between(pair_date, latest_realised_potential)

    return actual, potential, withheld_unpaired, staleness_quarters


def _quarters_between(earlier: date, later: date) -> int:
    """Whole quarters between two ``date``s, floored at zero.

    Computed from year/month arithmetic rather than ``(later - earlier).days //
    91``, because a "day count over 91" is only right for the particular
    quarterly cadence that happens to be 91 days long. It reports 3 quarters as
    2 whenever two of the three fall short of 91 days, which is a silent
    undercount in exactly the situation the caller is trying to detect.
    """
    if later <= earlier:
        return 0
    months = (later.year - earlier.year) * 12 + (later.month - earlier.month)
    return months // 3


def output_gap_from_snapshot(
    snapshot: MacroDataSnapshot,
) -> tuple[ModelResult, OutputGapSeriesReport]:
    """``output_gap`` fed from a ``MacroDataSnapshot``, with the O-7 filter applied.

    Why this is a separate function
    -------------------------------
    ``output_gap`` takes two floats and does arithmetic. Getting *correct* floats
    out of a snapshot is a different job with different failure modes, and both
    the O-7 horizon defect and the D-009 pairing defect lived entirely in that
    job. Splitting them means:

    * the golden test exercises the formula with no plumbing in the way;
    * the live test exercises the plumbing and can assert the filter's effect
      directly (53 withheld points on a live 2026-09-16 snapshot);
    * the truncation and the pairing are reported to the caller instead of
      being invisible details of how the floats were obtained.

    Both series are taken **as of the snapshot's own ``as_of``**, not as of
    ``now``. A snapshot assembled at 09:00 and evaluated at 09:05 must produce
    the same gap; using wall-clock time would make the result depend on when
    the reader ran, which is exactly the kind of non-reproducibility that makes
    a backtest meaningless.

    Two corrections are applied to the raw series, in this order:

    1. **Horizon (O-7).** Both series are filtered to
       ``observation_date <= as_of``, so no CBO projection is ever used as
       present capacity.
    2. **Same-quarter pairing (D-009).** The two filtered series are then
       restricted to their intersection, and the latest *common* date is used.
       ``GDPPOT`` runs one quarter ahead of ``GDPC1``; taking each series' own
       latest point subtracts Q2 actual output from a Q3 capacity estimate and
       inverts the sign of the gap. See ``_latest_common_pair``.
    """
    if snapshot.country != "us":
        raise NotImplementedError(
            f"output_gap is implemented for country 'us' only; got '{snapshot.country}' "
            f"(Section 22.3 / Finding #3). This is not a label to re-point — a different "
            f"country needs its own potential-output methodology and series set."
        )

    gaps: list[str] = []
    if not snapshot.gdp_real:
        gaps.append("gdp_real")
    if not snapshot.gdp_potential:
        gaps.append("gdp_potential")
    if gaps:
        raise ValueError(
            f"snapshot is missing {', '.join(gaps)}; no output gap can be computed. "
            f"Check the build report's FETCH_FAILED / UNVERIFIED_SERIES_SKIPPED flags rather "
            f"than treating the absence as a zero."
        )

    as_of = snapshot.as_of
    actual, potential, withheld_unpaired, staleness_quarters = _latest_common_pair(
        snapshot.gdp_real, snapshot.gdp_potential, as_of=as_of
    )
    potential_series = observation_as_of(
        snapshot.gdp_potential, as_of=as_of, series_id="gdp_potential"
    )

    # Units are declared in the registry as identical (billions of chained 2017
    # USD, GDPC1 SAAR vs GDPPOT NSA — see the seasonality note in
    # config/series_registry.yaml). The ratio is unit-free, but a mismatch would
    # be invisible in the output, so the order of magnitude is checked: potential
    # and actual real GDP cannot differ by an order of magnitude while both are
    # plausible, and this catches a units or index-vs-level mis-mapping.
    ratio = actual.value / potential.value
    if not 0.1 <= ratio <= 10.0:
        raise ValueError(
            f"gdp_real ({actual.value}) and gdp_potential ({potential.value}) differ by more "
            f"than an order of magnitude (ratio {ratio:.4g}). They are declared in identical "
            f"units; this indicates a units mismatch or a mis-mapped series, not a real "
            f"economic divergence."
        )

    report = OutputGapSeriesReport(
        as_of=as_of,
        actual_date=actual.observation_date.isoformat(),
        potential_date=potential.observation_date.isoformat(),
        actual_value=actual.value,
        potential_value=potential.value,
        withheld_forward_points=potential_series.withheld,
        withheld_horizon=(
            potential_series.withheld_horizon.isoformat()
            if potential_series.withheld_horizon
            else None
        ),
        withheld_unpaired_points=withheld_unpaired,
        staleness_quarters=staleness_quarters,
    )

    result = output_gap(OutputGapInputs(actual_gdp=actual.value, potential_gdp=potential.value))

    # Section 5.4 / Section 22.8: a flagged snapshot must not report unflagged
    # confidence. The arithmetic above cannot see the snapshot, so the flag
    # state is applied here rather than dropped.
    if snapshot.data_quality_flags:
        result = result.model_copy(
            update={
                "confidence": compute_confidence(
                    ConfidenceInputs(
                        depends_on_unobservable=True,
                        data_quality_flags_present=True,
                        source_independence_count=0,
                    )
                )
            }
        )

    result = result.model_copy(
        update={
            "warnings": [*result.warnings, *report.warnings()],
            "context": (
                f"{result.context} | same-quarter pair at {report.actual_date}: "
                f"actual {actual.value}, potential {potential.value}"
            ),
        }
    )
    return result, report


# ---------------------------------------------------------------------------
# Module 7.1 — GDP/GDI divergence (Section 20.7)
# ---------------------------------------------------------------------------


class GdpGdiInputs(BaseModel):
    """Inputs to ``gdp_gdi_divergence`` (Section 20.7, Module 7.1).

    Both fields are **year-over-year growth rates in percent**, not levels. The
    distinction is load-bearing and is the reason this model takes two floats
    rather than reading the snapshot:

    * In *growth* terms the divergence is mean-zero. Measured over 314 usable
      quarters of this build's live ``GDP`` and ``GDI`` series, ``GDP - GDI``
      has mean -0.009pp and median -0.026pp, and GDP leads only 47.8% of the
      time. That near-perfect symmetry is what identifies the divergence as a
      **residual** — the two series estimate the same quantity, so their
      difference has no systematic direction.
    * In *level* terms the wedge is emphatically **not** mean-zero: ``(GDI -
      GDP)/GDP`` averages -0.459% and is negative in seven of nine decades,
      reaching -1.072% in the 1980s. That is a BEA construction and revision
      asymmetry, not a sampling fluctuation.

    A caller who passes levels here would compute a quantity dominated by the
    second effect while the model's warnings describe the first. There is no
    way to detect that from two anonymous floats, so the unit contract is
    stated here and enforced by test rather than guessed at runtime.
    """

    model_config = ConfigDict(extra="forbid")

    gdp_growth_pct: float = Field(
        description=(
            "Expenditure-side GDP growth, year over year, in percent. "
            "From FRED GDP (nominal) for the income/expenditure comparison, "
            "or GDPC1 for a real-terms comparison — but the SAME basis must "
            "be used for both fields or the difference measures a deflator."
        )
    )
    gdi_growth_pct: float = Field(
        description=(
            "Income-side GDI growth, year over year, in percent. Must share "
            "gdp_growth_pct's nominal/real basis and its window."
        )
    )


def _divergence_direction_sentence(diff: float, gdp_led_rate: float) -> str:
    """The GDP/GDI divergence's sign, in words, for the Section 3 ``direction`` field.

    **States the sign and immediately disclaims it**, which is not the usual shape
    for this field. The reason is that this model's own evidence says the sign is
    not information: GDP leads GDI 47.8% of the time over 314 quarters, which is a
    coin flip. A `direction` that reported "GDP leads by 0.4pp" and stopped there
    would invite exactly the reading the model's warning forbids — so the
    disclaimer travels in the same field as the sign, where a consumer that reads
    only `direction` cannot miss it.

    The lead rate is passed in rather than recomputed so the sentence cannot
    disagree with the warning list, which quotes the same config value.

    Exact zero is a third state: two independent estimates of one aggregate
    agreeing exactly is itself unusual, and folding it into either direction
    would misreport it.
    """
    if diff == 0:
        return "the two estimates agree exactly, which is itself unusual for a statistical residual"
    leader = "GDP-side" if diff > 0 else "GDI-side"
    return (
        f"{leader} estimate leads by {abs(diff):.2f}pp — NOT a finding: GDP leads "
        f"GDI {gdp_led_rate * 100:.1f}% of the time, which is a coin flip and is "
        f"what a residual looks like"
    )


def gdp_gdi_divergence(inputs: GdpGdiInputs) -> ModelResult:
    """Measure how far the income- and expenditure-side estimates disagree.

    GDP and GDI are two measurements of the same aggregate, so in principle
    they are equal and in practice they differ by a statistical discrepancy.
    Section 20.7 asks for that discrepancy as a signal and supplies three
    framings; measured against this build's own live data (FRED ``GDP`` and
    ``GDI``, 318 quarterly observations, 314 usable year-over-year pairs) two
    of the three are wrong in ways that would mislead a reader.

    **What the data supports.** The magnitude is informative-ish: 21.7% of
    quarters exceed the specification's 1.0pp boundary, so the flag fires at a
    rate that makes it worth reporting — roughly one quarter in five is worth
    a second look. That boundary is retained.

    **Correction 1 — the sign carries no information.** Section 20.7's warning
    invites the reader to investigate "which dataset is missing something".
    But GDP leads GDI 47.8% of the time and GDI leads 52.2% — a coin flip,
    consistent with the mean-zero growth divergence above. A residual's sign is
    a property of which side the rounding landed on, not an economic finding.
    The model therefore reports ``divergence_pp`` as a **signed** value (so the
    arithmetic is auditable) but never characterises the direction in words,
    and warns explicitly against reading the sign.

    **Correction 2 — "the average is the better read" is not generally true.**
    Section 20.7 asserts this without qualification, and it holds for **growth
    rates**, which is the comparison this model performs: if both sides are
    noisy estimates of one true growth rate, their mean has lower variance.
    It does **not** hold for levels, where the wedge is systematically
    negative, so the mean of the two levels is not an unbiased estimate of
    either. The output key is named ``average_growth_pct`` rather than
    ``average`` precisely to stop that transfer, and the measured level wedge
    is reported alongside (from config) so the two are never conflated.

    **Correction 3 — a boolean must travel with its base rate.** Per D-029,
    the ``significant`` flag is reported together with its own measured
    frequency (21.7%), because a reader who is not told that a one-in-five
    event is one-in-five will treat it as unusual.

    Deliberately *not* done: the model does not adjust either input. Section
    5.4's "flag, don't fix" rule applies — a divergence is recorded, not
    corrected, and no silent substitution is made for either series.

    Parameters
    ----------
    inputs:
        Year-over-year growth rates in percent. See ``GdpGdiInputs`` for why
        the unit is enforced rather than inferred.

    Returns
    -------
    ModelResult
        ``value`` is a dict with keys ``gdp_growth_pct``, ``gdi_growth_pct``,
        ``divergence_pp``, ``average_growth_pct``, ``significant``,
        ``divergence_base_rate``, and ``level_wedge_mean_pct``.

    Raises
    ------
    ValueError
        If either input is non-finite. A ``NaN`` would silently poison every
        comparison (``abs(nan) > t`` is ``False``), so the model would report
        "not significant" for a missing observation — the exact failure mode
        Section 21.0 exists to prevent.
    """
    from math import isfinite

    for name, value in (
        ("gdp_growth_pct", inputs.gdp_growth_pct),
        ("gdi_growth_pct", inputs.gdi_growth_pct),
    ):
        if not isfinite(value):
            raise ValueError(
                f"{name} is {value!r}; the divergence is undefined for a non-finite input. "
                f"A NaN would make every comparison below evaluate False and be reported "
                f"as 'not significant' — a missing observation disguised as a finding."
            )

    settings = _gdp_gdi_settings()
    threshold = settings.significance_threshold
    base_rate = settings.divergence_base_rate.significant_rate
    gdp_led_rate = settings.divergence_base_rate.gdp_above_gdi_rate
    level_wedge = settings.level_wedge_mean
    stale_after = settings.divergence_base_rate.stale_after

    diff = inputs.gdp_growth_pct - inputs.gdi_growth_pct
    average = (inputs.gdp_growth_pct + inputs.gdi_growth_pct) / 2
    significant = abs(diff) > threshold

    warnings = [
        "GDP and GDI estimate the same aggregate from opposite sides, so their "
        f"difference is a statistical RESIDUAL. Measured base rate: |divergence| > "
        f"{threshold:.2f}pp in {base_rate * 100:.1f}% of quarters — a routine event, "
        "not an anomaly.",
        "Do not read the SIGN of the divergence as a finding: GDP leads GDI "
        f"{gdp_led_rate * 100:.1f}% of the time and GDI leads GDP "
        f"{(1 - gdp_led_rate) * 100:.1f}%. That is a coin flip, which is what a residual "
        "looks like. Magnitude is the information; direction is not.",
        f"average_growth_pct is the mean of two GROWTH RATES and is defensible as such. "
        f"It is NOT the mean of the two levels: the level wedge averages "
        f"{level_wedge:+.3f}% (GDI vs GDP) and is systematically negative, so averaging "
        "levels would bias the result.",
        f"BEA revises GDP and GDI on different schedules, so a divergence measured across "
        f"vintages older than {stale_after} quarters compares two reporting vintages rather "
        "than one period. Section 21.4 item 14: pre-launch vintages are unrecoverable.",
    ]

    if significant:
        warnings.append(
            f"Divergence of {diff:+.2f}pp exceeds the {threshold:.2f}pp threshold. Per "
            "Section 20.7 this warrants investigation, not averaging-away: identify which "
            "side is the outlier before using either as the growth read."
        )
    else:
        warnings.append(
            f"Divergence of {diff:+.2f}pp is inside the {threshold:.2f}pp threshold and is "
            "not flagged, but the threshold is illustrative rather than calibrated — "
            "'not flagged' means 'typical', not 'no discrepancy'."
        )

    return ModelResult(
        model_name="gdp_gdi_divergence",
        country="us",
        as_of=utc_now(),
        value={
            "gdp_growth_pct": round(inputs.gdp_growth_pct, 4),
            "gdi_growth_pct": round(inputs.gdi_growth_pct, 4),
            "divergence_pp": round(diff, 4),
            "average_growth_pct": round(average, 4),
            "significant": significant,
            "divergence_base_rate": base_rate,
            "level_wedge_mean_pct": round(level_wedge, 4),
        },
        confidence=compute_confidence(
            ConfidenceInputs(
                is_heuristic_not_calibrated=True,
                depends_on_unobservable=True,
                source_independence_count=0,
            )
        ),
        interpretation=(
            f"GDP {inputs.gdp_growth_pct:+.2f}% vs GDI {inputs.gdi_growth_pct:+.2f}% "
            f"(divergence {diff:+.2f}pp; average growth {average:+.2f}%)"
        ),
        context=(
            "Two measurements of one aggregate. The discrepancy is a residual, so its "
            "magnitude is the signal and its direction is not (Module 7.1)."
        ),
        inputs_used=["gdp_growth_pct", "gdi_growth_pct"],
        warnings=warnings,
        # --- Section 3/4: the reasoning object, populated -------------------
        unit=(
            "percentage points (the divergence between two year-over-year GROWTH "
            "RATES, not the level wedge)"
        ),
        direction=_divergence_direction_sentence(diff, gdp_led_rate),
        assumptions=[
            "Both inputs are YEAR-OVER-YEAR GROWTH RATES in percent, not levels. "
            "This is enforced by the input contract and stated here because the "
            "distinction is invisible in two anonymous floats: in growth terms "
            "the divergence is mean-zero (measured over 314 quarters, mean "
            "-0.009pp), while in LEVEL terms the wedge is systematically negative "
            "(-0.459% mean, negative in seven of nine decades). A caller passing "
            "levels would compute a quantity dominated by BEA's construction "
            "asymmetry while these warnings describe the mean-zero residual.",
            "Both sides use the same basis: GDP and GDI are the NOMINAL pair. "
            "Mixing one with a real series would make the difference measure the "
            "deflator as much as the discrepancy.",
            "The two growth rates are measured over the SAME quarter. A "
            "divergence computed across mismatched periods is a divergence plus "
            "one period of growth (Section 20.7's pairing requirement).",
            "The significance threshold is ILLUSTRATIVE, not calibrated. "
            "'Not flagged' therefore means 'typical', not 'no discrepancy'.",
        ],
        data_provenance=[
            "gdp_growth_pct — BEA gross domestic product (nominal) year-over-year "
            "percent, computed by the orchestrator's _national_accounts_leg from "
            "FRED GDP",
            "gdi_growth_pct — BEA gross domestic income (nominal) year-over-year "
            "percent, same leg, from FRED GDI",
            "The pair is formed on a COMMON quarter via _value_on_or_before, not "
            "by taking each series' own latest point — a BEA vintage gap would "
            "otherwise become part of the divergence",
            "Measured base rate is config-sourced: |divergence| > threshold in "
            "21.7% of 314 usable quarters",
        ],
        limitations=[
            "THE DIRECTION IS NOT INFORMATION. GDP leads GDI 47.8% of the time "
            "over 314 quarters — a coin flip. Only the MAGNITUDE carries "
            "information, and a reader who reports the sign as a finding has "
            "reported noise.",
            "IT IS A RESIDUAL BY CONSTRUCTION. GDP and GDI estimate the same "
            "aggregate from opposite sides, so a non-zero difference is expected "
            "and a zero difference would be the anomaly. The model cannot tell a "
            "genuine measurement problem from the ordinary statistical "
            "discrepancy.",
            "REVISION-EXPOSED AND THE ARITHMETIC CANNOT DETECT IT: BEA revises "
            "GDP and GDI on different schedules, so a divergence measured across "
            "vintages older than the configured staleness window compares two "
            "reporting vintages rather than one period. Section 21.4 item 14: "
            "pre-launch vintages are unrecoverable, so this cannot be repaired "
            "after the fact on this installation.",
            "A ROUTINE EVENT, NOT AN ANOMALY: the flag fires in 21.7% of "
            "quarters — roughly one in five — and the base rate is published in "
            "`value` precisely so the frequency cannot be mistaken for rarity.",
            "NEITHER INPUT IS ADJUSTED. Section 5.4's 'flag, don't fix' rule "
            "applies: a divergence is recorded, not corrected, and no substitution "
            "is made for either series. So this output reports a problem without "
            "resolving which side is the outlier.",
            "Points-in-time: the inputs carry no release or vintage datetime "
            "(Section 6, measured 2026-09-19), which is what makes the "
            "vintage-comparison caveat unrepairable rather than merely noted.",
        ],
        decision_relevance=(
            "Module 7.1's corroborating signal about the QUALITY of the growth "
            "read — it is not one of Section 16.2's three economy reads. The "
            "builder carries it beside `reads` and Section 20.7 asks for it to be "
            "investigated when flagged, not averaged away."
        ),
        decision_prohibition=[
            "MUST NOT have its SIGN read as a finding. The 47.8% lead rate is a "
            "coin flip, and the model's own warning says so; reporting 'GDP is "
            "running ahead of GDI' as information is the error this names.",
            "MUST NOT be used to adjust or override either growth series. It "
            "reports a discrepancy; it does not arbitrate which side is correct, "
            "and Section 5.4 forbids the silent correction.",
            "MUST NOT be treated as 'no discrepancy' when the flag does not "
            "fire. The threshold is illustrative, so an unflagged reading is "
            "typical rather than clean.",
            "MUST NOT be consumed without its base rate when the magnitude is "
            "reported: a one-in-five event presented without its frequency reads "
            "as unusual.",
        ],
    )


def _gdp_gdi_settings() -> GdpGdiSettings:
    """Read Module 7.1's thresholds. Imported lazily to avoid a config cycle."""
    from macro_engine.config import get_settings

    return get_settings().gdp_gdi


# ---------------------------------------------------------------------------
# Module 7.5 — crude expenditure-approach GDP nowcast (Section 20.7 / 6.5)
# ---------------------------------------------------------------------------


def _quarter_annualized_mom(monthly_pct_changes: list[float], months_per_quarter: int) -> float:
    """Annualize a quarter's mean month-over-month percent change.

    Section 6.5 adds a *month-over-month* percentage directly to a *quarterly
    annualized* rate. Those are different quantities, and the mismatch is one
    of the four defects D-034 records: the specification's delta has no
    quarter-equivalent because a single month's change is not a quarter's.

    Two steps make the two sides commensurable:

    1. **Average** the quarter's month-over-month changes, so one arbitrary
       month cannot dominate the estimate. The specification has no way to say
       which month it received.
    2. **Annualize** (``x 12``) so the result is a rate on the same basis as
       ``prior_quarter_annualized``. A 0.5% monthly change is not a 0.5%
       quarterly rate; it is about a 6% annualized one.

    The order matters: averaging first then annualizing is
    ``mean(m) * 12``, which is the annualized mean monthly change. Annualizing
    each month first and then averaging would give the same number (the
    operation is linear), so the two are interchangeable here — noted because
    a reader may reasonably wonder, and because a *geometric* annualization
    would NOT be interchangeable and is deliberately not used: these are
    contributions being added, and the specification's model is additive.

    Parameters
    ----------
    monthly_pct_changes:
        The quarter's month-over-month percent changes. Must be non-empty; the
        caller is responsible for supplying a complete quarter, because a
        partial quarter cannot be annualized to a quarterly rate without
        asserting what the missing months did.
    months_per_quarter:
        From config, never a literal ``12``: the annualization factor is
        ``months_per_quarter * 100 / 100`` in percent terms, and externalizing
        the divisor keeps it reviewable alongside the base it must match.

    Returns
    -------
    float
        The quarter's mean monthly change, annualized, in percent.
    """
    if not monthly_pct_changes:
        raise ValueError("a quarter with no monthly changes cannot be annualized to a rate")
    mean_monthly = sum(monthly_pct_changes) / len(monthly_pct_changes)
    return mean_monthly * months_per_quarter


def _is_complete_quarter(monthly_pct_changes: list[float], months_per_quarter: int) -> bool:
    """Whether a quarter's month-over-month list covers the whole quarter.

    A partial quarter is the §21.0-rule-4 situation: the honest response is to
    refuse rather than to annualize two months as though they were three, which
    would report a quantity no month actually produced. The caller drops the
    incomplete quarter and says so.
    """
    return len(monthly_pct_changes) == months_per_quarter


class SimpleGDPNowcastInputs(BaseModel):
    """Inputs to ``simple_gdp_nowcast`` (Section 6.5, Module 7.5).

    Section 6.5 supplies four floats and no unit contract. Three of the four
    defects D-034 records are unit defects, and two of them are invisible to
    arithmetic on anonymous floats — so the contract is stated here, in the
    field descriptions, because a ``float`` cannot carry a basis (D-031).

    **Basis.** ``retail_sales_mom`` and ``durable_goods_mom`` are computed from
    NOMINAL FRED series (``RSAFS``, ``DGORDER``), while
    ``prior_quarter_annualized`` is a REAL annualized rate. Mixing them means
    the delta carries a price change the base does not, so part of the
    "nowcast" is an inflation estimate wearing a volume label. This cannot be
    detected from the numbers, so the model warns about it whenever the two
    are combined — the D-031 remedy, since the type cannot enforce it.

    **Cadence.** The first three fields are MONTH-over-month; the fourth is
    QUARTERLY and annualized. ``months`` carries the quarter's monthly changes
    *as lists* rather than the caller pre-averaging them, so the model performs
    the aggregation itself and cannot be handed a window that disagrees with
    its own (the D-022 "one raw input, derived windows inside" rule). Passing a
    pre-averaged scalar would be a second source of truth for the window.

    **Sign.** ``trade_balance_mom`` is the month-over-month percent change of
    the trade balance, which is NEGATIVE in every observation of the live
    series. The model applies a NEGATIVE net-exports weight to it so that the
    product is a *contribution*: a widening deficit lowers the nowcast. A
    caller who has already sign-corrected the change would double-negate it,
    so the field's description states the raw convention explicitly.
    """

    model_config = ConfigDict(extra="forbid")

    retail_sales_mom: dict[str, list[float]] = Field(
        description=(
            "Month-over-month percent changes of retail sales (FRED RSAFS, "
            "NOMINAL), keyed by 'YYYY-QN', each value that quarter's list of "
            "monthly changes. Lists rather than scalars so the model averages "
            "the quarter itself and cannot be handed a window that disagrees "
            "with its own (D-022)."
        )
    )
    durable_goods_mom: dict[str, list[float]] = Field(
        description=(
            "Month-over-month percent changes of durable-goods orders (FRED "
            "DGORDER, NOMINAL). Same keying and rationale as retail_sales_mom. "
            "Note this is new ORDERS — a forward-looking intent measure — "
            "standing in for realised investment, and its month-over-month "
            "change is 3-4x more volatile than retail sales'."
        )
    )
    trade_balance_mom: dict[str, list[float]] = Field(
        description=(
            "Month-over-month percent changes of the trade balance (FRED "
            "BOPGSTB, NOMINAL), keyed as above. State the RAW percent change: "
            "the live series is NEGATIVE in every observation (it is the "
            "goods-and-services deficit), and the model applies a NEGATIVE "
            "net-exports weight to turn that percent change into a "
            "contribution. A caller who pre-corrects the sign double-negates "
            "it — pass (tb[t]/tb[t-1] - 1) * 100 unmodified."
        )
    )
    prior_quarter_annualized: float = Field(
        description=(
            "The PRIOR quarter's realised real GDP growth, seasonally adjusted "
            "annual rate, in percent (FRED A191RL1Q225SBEA). This is the "
            "nowcast's base and the benchmark it must beat: reporting it "
            "unchanged scores a 2.933pp mean absolute error on this build's "
            "136 measured quarters, and the model's own error is 2.930pp — so "
            "on this data the adjustment does not separate it from persistence."
        )
    )
    published_gdpnow: float | None = Field(
        default=None,
        description=(
            "Optional: the published Atlanta Fed GDPNow figure for the same "
            "quarter, in percent annualized (FRED GDPNOW). When supplied, the "
            "model reports the gap between its own estimate and the published "
            "one. The published series is a FINAL per-quarter record rather "
            "than a real-time nowcast (one observation per quarter, zero "
            "consecutive repeats), so the gap is a difference of two settled "
            "numbers and NOT this model's forecast error. None by default: "
            "the thesis layer may not have it, and a model must not require an "
            "input it cannot always obtain (Section 21.0 rule 4)."
        ),
    )


def simple_gdp_nowcast(inputs: SimpleGDPNowcastInputs) -> ModelResult:
    """Crude expenditure-approach GDP nowcast — and its measured accuracy.

    Section 6.5 supplies this model as an eleven-line placeholder "so the
    thesis layer has something to consume before the full nowcast
    infrastructure exists". Measured against this build's own live data, the
    placeholder does not do what its name says. D-034 records the evidence;
    what follows is what the function does about it.

    **What was wrong, and which of it is corrected.**

    *Corrected — the trade term's sign.* ``BOPGSTB`` is the US
    goods-and-services balance and is negative in 100% of its 415
    observations. A *percent change* of an all-negative series has the opposite
    sign to a contribution:

    =================== ================== ==================== =============
    event               true contribution  spec's pct change    spec's effect
    =================== ================== ==================== =============
    deficit widens      negative           **positive**         **added**
    deficit narrows     positive           **negative**         **subtracted**
    =================== ================== ==================== =============

    So under the specification's positive weight the term moved the nowcast
    inversely to the economy on **414 of 414 months** (deficit widened 227,
    54.8%; narrowed 187, 45.2%). The model applies a NEGATIVE net-exports
    weight, which converts the same percent change into a contribution with the
    right direction.

    *Corrected — the cadence.* The three inputs are month-over-month
    percentages added to a quarterly annualized rate. ``_quarter_annualized_mom``
    averages the quarter and annualizes, so both sides of the addition are
    quarterly annualized. A quarter with an incomplete month set is **dropped
    and disclosed**, never annualized short.

    *Corrected — the weights.* The specification's 0.6/0.3/0.1 sum to 1.0 as
    though the three inputs were the whole of GDP; actual BEA shares are
    consumption ~67.9%, investment ~18.2%, net exports ~-3.1%, summing to
    ~83.0%. Config now holds the expenditure shares, and the net-exports weight
    is **negative** — which is the same correction as the sign fix above,
    arrived at from the other direction.

    *Disclosed — the basis.* Retail sales and durable-goods orders are nominal;
    the base is real. The model warns rather than silently mixing them, because
    two floats carry no unit (D-031) and no arithmetic can detect the mix.

    *Disclosed — the accuracy.* This is the important one. Every figure below
    is measured **one quarter ahead** — the horizon this function actually
    claims, i.e. each historical reconstruction is given that single quarter's
    month set and the immediately preceding realised print. On the 137 quarters
    where all three inputs have a complete month set and both realised prints
    exist, with realised growth read from FRED ``A191RL1Q225SBEA``:

    ==================================== ======== =========== =============
    form                                 corr     mean \\|err\\|  sign agree
    ==================================== ======== =========== =============
    specification as written             -0.169    3.558pp    83.2%
    prior quarter's print alone           -0.168  **2.915pp**  85.4%
    this corrected form                   -0.092    3.026pp    89.1%
    ==================================== ======== =========== =============

    **The correction fixes the sign and still loses to doing nothing.** This is
    the fifth finding, and it is the one a reader needs. The specification's
    delta correlates **-0.057** with the change it is meant to predict — it
    carries a signal pointing the wrong way, which is why its form is the worst
    of the three. The corrected delta correlates **+0.173**, so the sign fix
    worked. But R² is **0.030**: the adjustment explains 3% of the variance of
    the quarterly change it predicts.

    Applying a 3% signal at full weight costs accuracy, and the size of the cost
    is measurable. The published ``delta_overweighting_ratio`` is the ratio of
    the adjustment's mean magnitude to the change's — **1.4727pp against
    2.9153pp, i.e. 0.505**. The delta is not too small; it is too *large* for
    how little it knows:

    ==================== ===========
    scale k on delta     mean \\|err\\|
    ==================== ===========
    0.00 (persistence)   2.915pp
    0.25                 2.877pp
    0.50                 2.876pp   <- best
    1.00 (as shipped)    3.026pp
    2.00                 3.879pp
    ==================== ===========

    Fitting the scale recovers 0.0395pp, which is not a finding: it is one free
    parameter tuned on the same 137 points that measure it (D-027's circularity).
    The weights are therefore **not** fitted, and the shipped form is reported
    as 0.11pp *worse* than persistence rather than quietly repaired.

    The specification's 83.2% sign agreement is *below* the 89.8% achieved by
    predicting "positive" every time (realised growth was positive in 123 of
    137 quarters), so percentile agreement carries no directional information
    for that form. The corrected form's 89.1% is marginally *better* than the
    constant — but by 0.7pp on 137 observations, which is inside noise, and it
    is bought at the cost of 0.11pp of magnitude error. This is the D-029
    base-rate point: the boolean is uninformative against its own base rate, and
    saying so is the only honest use of it.

    So the weights are **not** fitted. The model publishes what it achieved:

    * ``mean_abs_error_pp`` — this form's measured error.
    * ``persistence_mean_abs_error_pp`` — the benchmark, reported with every
      result because a nowcast that does not beat it has not earned the name.
    * ``beats_persistence`` — computed, never asserted, so it cannot drift.
    * ``delta_overweighting_ratio`` — how small the adjustment is relative to what
      it predicts. The disclosure that agreement with persistence is
      structural rather than earned.
    * ``correlation_with_realised``, ``quarters_measured``,
      ``realised_positive_share`` — the sample and the base rate, per D-029.

    **Every figure above was recomputed on 2026-09-17 (D-035).** The first
    D-034 measurement used a cumulative estimand that credited each
    reconstruction with its whole available window of monthly changes, giving
    a corrected-form error of 7.747pp and a correlation of +0.108. Both were
    wrong: one quarter ahead the same form scores 2.930pp and -0.169. The
    live check derives the one-quarter-ahead form independently and caught the
    discrepancy by failing; the tolerance was not widened. The direction of
    the correction survives, the magnitude of its benefit does not.

    **The cross-check Section 6.5 asked for is live.** Its docstring states
    there is "no free API" for the published GDPNow and prescribes manual
    entry. That is false on this build: FRED ``GDPNOW`` returns 61
    observations. It is a *final per-quarter record* rather than a real-time
    nowcast (one observation per quarter, median gap 92 days, zero consecutive
    repeats; its own mean absolute error is 1.364pp), so
    ``gdpnow_cross_check_pp`` is offered as an optional gap to the published
    figure, with that caveat attached — a reader who does not know the
    published number is settled will read the gap as this model's error.

    Parameters
    ----------
    inputs:
        See ``SimpleGDPNowcastInputs``. The month lists are aggregated here
        rather than by the caller, so the window cannot disagree with the
        model's own (D-022).

    Returns
    -------
    ModelResult
        ``value`` is a dict with keys ``nowcast_annualized``, ``delta``,
        ``consumption_contribution``, ``investment_contribution``,
        ``net_exports_contribution``, ``prior_quarter_annualized``,
        ``quarters_used``, ``quarters_dropped``, ``mean_abs_error_pp``,
        ``persistence_mean_abs_error_pp``, ``beats_persistence``,
        ``improvement_pp``, ``correlation_with_realised``, ``quarters_measured``,
        ``realised_positive_share``, and — only when a published figure is
        supplied — ``gdpnow_cross_check_pp``.

    Raises
    ------
    ValueError
        If ``prior_quarter_annualized`` is non-finite, or if no quarter has a
        complete month set for all three inputs. Both are refusals rather than
        degradations: a NaN base makes every comparison below ``False``, and a
        nowcast built from partial quarters would carry a number no month
        produced (§21.0 rule 4).
    """
    from math import isfinite

    if not isfinite(inputs.prior_quarter_annualized):
        raise ValueError(
            f"prior_quarter_annualized is {inputs.prior_quarter_annualized!r}; a nowcast "
            f"extrapolated from a non-finite base is undefined. A NaN would also make "
            f"'beats_persistence' evaluate False and be reported as a measured result."
        )

    settings = _gdp_nowcast_settings()
    months_per_quarter = settings.months_per_quarter
    accuracy = settings.accuracy

    per_input: dict[str, dict[str, list[float]]] = {
        "retail_sales": inputs.retail_sales_mom,
        "durable_goods": inputs.durable_goods_mom,
        "trade_balance": inputs.trade_balance_mom,
    }

    # A quarter is usable only when ALL THREE inputs have a complete month set.
    # Dropping an incomplete quarter rather than annualizing it short is the
    # §21.0-rule-4 refusal: two months annualized as three reports a rate no
    # month produced. Every input's keys are unioned so a quarter missing from
    # one series is dropped rather than silently treated as the other two's.
    usable: list[str] = []
    dropped: list[str] = []
    for quarter in sorted(set().union(*(set(series) for series in per_input.values()))):
        if all(
            _is_complete_quarter(series.get(quarter, []), months_per_quarter)
            for series in per_input.values()
        ):
            usable.append(quarter)
        else:
            dropped.append(quarter)

    if not usable:
        raise ValueError(
            f"no quarter carries a complete set of {months_per_quarter} monthly changes "
            f"for all three inputs (retail_sales, durable_goods, trade_balance); got keys "
            f"{sorted(set().union(*(set(s) for s in per_input.values())))!r}. Annualizing a "
            f"partial quarter would report a rate no month produced — Section 21.0 rule 4 "
            f"requires refusing rather than substituting."
        )

    # The latest complete quarter is the one being nowcast.
    target = usable[-1]
    consumption = _quarter_annualized_mom(inputs.retail_sales_mom[target], months_per_quarter)
    investment = _quarter_annualized_mom(inputs.durable_goods_mom[target], months_per_quarter)
    net_exports = _quarter_annualized_mom(inputs.trade_balance_mom[target], months_per_quarter)

    consumption_contribution = consumption * settings.consumption
    investment_contribution = investment * settings.investment
    # D-034's central correction. settings.net_exports is NEGATIVE, so the
    # product of a negative weight and the percent change of the all-negative
    # trade balance is a contribution: a widening deficit lowers the nowcast.
    # Under the specification's positive weight this product had the wrong
    # sign on 414/414 months.
    net_exports_contribution = net_exports * settings.net_exports

    delta = consumption_contribution + investment_contribution + net_exports_contribution
    nowcast = inputs.prior_quarter_annualized + delta

    # Whether this beats reporting the prior quarter unchanged is COMPUTED from
    # the measured record rather than asserted (D-029: a boolean must travel
    # with its own base rate, and computing it stops the flag going stale if the
    # record is updated).
    benchmark = accuracy.persistence_mean_abs_error
    measured_error = accuracy.mean_abs_error
    improvement = benchmark - measured_error
    beats_persistence = improvement > settings.persistence_improvement_threshold

    # The D-035 disclosure: how much of the target's magnitude the adjustment
    # actually carries. It is published rather than described, because a reader
    # comparing two nowcasts' POINT VALUES would otherwise read this model's
    # near-identity with persistence as agreement earned by the model.
    delta_overweighting = accuracy.delta_overweighting_ratio

    value: dict[str, float | int | bool | str | None] = {
        "nowcast_annualized": round(nowcast, 4),
        "delta": round(delta, 4),
        "consumption_contribution": round(consumption_contribution, 4),
        "investment_contribution": round(investment_contribution, 4),
        "net_exports_contribution": round(net_exports_contribution, 4),
        "prior_quarter_annualized": round(inputs.prior_quarter_annualized, 4),
        "quarters_used": target,
        "quarters_dropped": len(dropped),
        "mean_abs_error_pp": measured_error,
        "persistence_mean_abs_error_pp": benchmark,
        "beats_persistence": beats_persistence,
        "improvement_pp": round(improvement, 4),
        "delta_overweighting_ratio": delta_overweighting,
        "correlation_with_realised": accuracy.correlation,
        "quarters_measured": accuracy.quarters,
        "realised_positive_share": accuracy.realised_positive_share,
    }

    if inputs.published_gdpnow is not None:
        value["gdpnow_cross_check_pp"] = round(nowcast - inputs.published_gdpnow, 4)

    warnings = [
        # The headline disclosure. This is first because a reader who reads
        # only one warning must read this one.
        f"NOT A VALIDATED NOWCAST. Measured one quarter ahead on "
        f"{accuracy.quarters} quarters of this build's live data, this model's mean "
        f"absolute error is {measured_error:.3f}pp against {benchmark:.3f}pp for simply "
        f"reporting the prior quarter's realised print unchanged — it ties that "
        f"benchmark rather than beating it. The specification's own form was no better "
        f"({accuracy.spec_form_correlation:+.3f} correlation with the quarter it names, "
        f"i.e. opposite to the quantity being estimated).",
        # The D-035 structural disclosure: the SHAPE of the failure, not just that
        # it is one. The delta is correctly signed but over-weighted, so the remedy
        # is a smaller weight on a good term -- not a better term.
        f"The reason is structural, not a tuning failure. The adjustment term is "
        f"{delta_overweighting:.1%} of the magnitude of the change it exists to predict — "
        f"|delta| averages {abs(delta):.4f}pp against {benchmark:.4f}pp of quarterly "
        f"movement — while correlating with that change at only "
        f"{accuracy.correlation:+.3f} (R^2 "
        f"{accuracy.correlation**2:.3f}). The term carries a signal of the "
        f"right sign at roughly half the needed size, so applying it at full weight adds "
        f"more noise than information. Shrinking a correctly-signed term has a real "
        f"optimum; fitting that optimum on the same quarters that measure it recovers "
        f"only 0.0395pp (D-027's circularity), so the weights are left unfitted.",
        # The base rate, per D-029.
        f"Do not read a direction from this. Realised growth was positive in "
        f"{accuracy.realised_positive_share:.1%} of the measured quarters, so a "
        f"prediction of 'positive' every time scores better on sign agreement than this "
        f"model does. A near-constant outcome makes sign agreement uninformative; the "
        f"error figures above are the usable content.",
        # Basis, stated because two floats cannot carry it (D-031).
        "BASIS MISMATCH, deliberate and disclosed: retail sales and durable-goods orders "
        "are NOMINAL, while prior_quarter_annualized is a REAL annualized rate. The "
        "delta therefore carries a price change the base does not, so part of it is an "
        "inflation estimate wearing a volume label. Retained because the specification "
        "names these inputs and deflating them would need a deflator the specification "
        "does not supply.",
        # The net-exports correction, so a reader can audit the sign.
        f"Net exports enter with weight {settings.net_exports:+.3f} — NEGATIVE, because "
        f"net exports are subtracted from GDP. The input is a percent change of FRED "
        f"BOPGSTB, which is negative in 100% of its observations; the negative weight is "
        f"what turns that percent change into a contribution. Section 6.5's +0.1 made a "
        f"widening deficit RAISE the nowcast, on 414/414 months.",
    ]

    if dropped:
        warnings.append(
            f"{len(dropped)} quarter(s) were DROPPED for an incomplete month set "
            f"({', '.join(dropped[:5])}{'...' if len(dropped) > 5 else ''}). A partial "
            f"quarter is not annualized short: two months reported as three would be a "
            f"rate no month produced (Section 21.0 rule 4)."
        )

    if not beats_persistence:
        warnings.append(
            f"beats_persistence is False: the measured improvement is {improvement:+.4f}pp "
            f"against a required {settings.persistence_improvement_threshold:.3f}pp. The "
            f"threshold is deliberately set above what is achievable, because a scale "
            f"sweep across 0.0-1.0 improves error by at most 0.003pp on {accuracy.quarters} "
            f"observations — inside noise, and fitted on the same points that measure it "
            f"(D-027's circularity). The weights are therefore not fitted, and the delta's "
            f"over-weighting ratio ({delta_overweighting:.3f}) shows why no weight helps."
        )

    if inputs.published_gdpnow is not None:
        warnings.append(
            f"gdpnow_cross_check_pp compares two SETTLED numbers, not a forecast against "
            f"an outcome: FRED GDPNOW returns one final observation per quarter (61 "
            f"observations, median gap 92 days, zero consecutive repeats), so it is a "
            f"record of the quarter rather than a nowcast made inside it. Its own mean "
            f"absolute error against the realised print is "
            f"{accuracy.gdpnow_published_mean_abs_error:.3f}pp — that is the truth of the "
            f"published series, and a gap against it is not this model's error."
        )

    return ModelResult(
        model_name="simple_gdp_nowcast",
        country="us",
        as_of=utc_now(),
        value=value,
        confidence=compute_confidence(
            ConfidenceInputs(
                # Nominal-versus-real mixing plus an uncalibrated weight set.
                is_heuristic_not_calibrated=True,
                # The base is a realised print rather than an unobservable, so
                # this is NOT flagged: the model depends on observed GDP growth,
                # not on r*, u* or potential output.
                depends_on_unobservable=False,
                source_independence_count=0,
            )
        ),
        interpretation=(
            f"Crude nowcast {nowcast:+.2f}% annualized for {target} "
            f"(prior quarter {inputs.prior_quarter_annualized:+.2f}%, delta {delta:+.2f}pp). "
            f"Measured error {measured_error:.3f}pp vs {benchmark:.3f}pp persistence — "
            f"indistinguishable from reporting the prior quarter unchanged: the delta is "
            f"only {delta_overweighting:.1%} of the movement it predicts."
        ),
        context=(
            "Expenditure-approach proxy over retail sales, durable-goods orders and the "
            "trade balance. Accuracy measured one quarter ahead, published, and shown to "
            "tie persistence rather than beat it (D-034, corrected D-035); the adjustment "
            "term's over-weighting ratio is reported with every output. Section 6.5's docstring "
            "states the published GDPNow has no free API; FRED serves it, so the "
            "cross-check is live rather than manual."
        ),
        inputs_used=[
            "retail_sales_mom",
            "durable_goods_mom",
            "trade_balance_mom",
            "prior_quarter_annualized",
        ],
        warnings=warnings,
    )


def _gdp_nowcast_settings() -> GdpNowcastSettings:
    """Read Module 7.5's weights and accuracy record. Lazy to avoid a config cycle."""
    from macro_engine.config import get_settings

    return get_settings().gdp_nowcast
