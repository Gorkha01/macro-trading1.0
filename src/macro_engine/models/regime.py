"""Module 3 — the rule-based regime classifier, and its corrected state grid.

This is a Tier 3 function: it composes no new arithmetic, it takes two
already-derived quantities and places them in a labelled cell. Which is exactly
why the review of it is about **coverage and interaction** rather than about a
formula — and why the specification's version fails.

Three defects in the specification (Section 6.2), all silent
------------------------------------------------------------

**1. Three of the nine declared states are unreachable.** Section 6.2 declares

    REGIME_STATES = ["early_expansion", "mid_expansion", "late_expansion",
                     "slowdown", "recession", "recovery", "disinflation",
                     "reflation", "stagflation"]

and then writes a branch chain that can only ever produce six of them.
``slowdown``, ``recovery`` and ``reflation`` appear in the declared vocabulary,
carry distinct risk profiles in ``FACTOR_REGIME_MAP`` (Section 15, Module 11's
factor tilt engine — ``reflation`` is the only state with ``momentum`` AND
``value`` both positive, ``recovery`` the only one with ``value`` positive and
``quality`` negative), and are consumed by ``sector_rotation_prior`` — but no
point in the declared input plane reaches them. This is D-037's defect class
(a branch for a state the logic forbids), and it is worse here because the
unreachable states are the *informative* ones: every regime that says "growth
is contracting but not yet a recession" or "inflation is turning up with growth
still weak" is collapsed into another label. Enumerating the specification's
logic over a dense sweep of its own input plane returns exactly six states; see
``tests/models/test_regime.py::test_specification_form_cannot_reach_three_of_its_nine_states``,
which pins that claim so the correction cannot be silently reverted.

**2. The ``else`` branch is a whole economic zone wearing the wrong label.**
Working Section 6.2's five predicates out by hand, the fallthrough receives
``trend < 0`` with ``-1.5 <= gap < -0.5`` — *the entire* "below trend but not a
deep contraction" region while inflation is falling. That is the textbook
``slowdown``/``recovery`` zone, and every point in it is labelled
``early_expansion``. This is why ``slowdown`` and ``recovery`` are unreachable:
their territory is not merely unvisited, it is occupied by the catch-all. The
state grid here assigns that region to ``slowdown``, and to ``recovery`` when
the gap is closing.

Relatedly, the ``recession`` branch requires ``output_gap < -1.5`` **AND**
falling inflation, so a deep contraction with *rising* inflation is not a
recession either — it is claimed by the ``stagflation`` branch whenever the gap
is below -0.5, which it is. At ``gap = -3.0`` with rising inflation the
specification returns ``stagflation``; depth of contraction should decide the
recession, and the inflation axis should decide only which *kind* it is.

**3. Two inputs are declared and never read; the read one is not declared as
used.** ``inflation_yoy`` is declared in ``RegimeInputs``, listed in
``inputs_used``, and never read. ``unemployment_gap`` is likewise declared,
listed, and never read — and it is a second, *independent* measure of the same
thing ``output_gap`` measures (slack), which is the single most useful
corroboration available here. Both are now read: ``unemployment_gap``
corroborates the output-gap axis, and ``inflation_yoy`` provides the level that
makes the momentum reading interpretable. This is D-037's "inert input" class,
caught three times in one function.

What is deliberately NOT changed
--------------------------------

The specification's **two-axis structure** is kept. A regime classifier that
reads one composite score is less auditable, not more; the whole value of the
2-D grid is that a reader can see *which* axis produced the label, and Section
6.3's ``inflation_breadth_score`` is the module that already serves as the
composite. The nine states are kept — the task was to make the declared
vocabulary reachable, not to rename it.

The inflation axis is **momentum**, not level. ``inflation_trend_3m`` is the
3-month annualized change; ``disinflation`` means inflation decelerating, not
inflation below target. That distinction is the specification's own (Section
20.5's "NOT 1:1" caveat has the same shape) and is stated in the output because
a reader who assumes levels will read every label backwards.

The corroboration axis
----------------------

``unemployment_gap`` is ``u - u*``: positive means the labour market is *slacker*
than its natural rate, which **agrees** with a negative output gap. The two are
not redundant — they are measured from different surveys (BLS establishment vs
household, and a modelled ``u*`` against a modelled potential) — which is what
makes their agreement worth reporting. They are also *not* independent in the
sense Section 12 requires for a "corroborating family": both are ultimately
measures of slack, so agreement here narrows the measurement error on a single
concept rather than adding a second concept. The output says which it is.

Two adjacent quantities need opposite sign conventions
------------------------------------------------------

``output_gap`` and ``unemployment_gap`` point in **opposite directions**:
``+1.0`` output gap (overheating) and ``-0.5`` unemployment gap (tight labour
market) describe the same economy. The corroboration test must therefore compare
``output_gap`` against ``-unemployment_gap``, and getting it backwards makes a
clean corroboration read as a flat contradiction. This is a pairing-axis defect
of the D-031 unit class and it is asserted directly in the test suite and in the
live check, because the wrong pairing produces a perfectly plausible
``CONTRADICTED`` verdict rather than an error.
"""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

from macro_engine.config import get_settings
from macro_engine.models.contracts import (
    ConfidenceInputs,
    ModelResult,
    compute_confidence,
    utc_now,
)
from macro_engine.models.evidence_family import EvidenceSourceFamily

__all__ = [
    "REGIME_STATES",
    "REGIME_TENSIONS",
    "TRILEMMA_SEVERITIES",
    "GrowthAxis",
    "InflationAxis",
    "PolicyDirection",
    "RegimeInputs",
    "RegimeState",
    "RegimeTension",
    "TrilemmaInputs",
    "TrilemmaSeverity",
    "check_trilemma_tension",
    "classify_regime_rule_based",
    "regime_tension",
]

#: The nine states, as a closed vocabulary (D-029).
#:
#: This tuple and the :data:`RegimeState` Literal below are the same set; the
#: tuple exists because Pydantic's ``Literal`` is not iterable through ``typing``
#: at runtime, and the base-rate lookup, the coverage test and the docstring all
#: need to iterate the declared vocabulary. ``tests/models/test_regime.py``
#: asserts the two agree, so they cannot drift.
REGIME_STATES: tuple[str, ...] = (
    "early_expansion",
    "mid_expansion",
    "late_expansion",
    "slowdown",
    "recession",
    "recovery",
    "disinflation",
    "reflation",
    "stagflation",
)

#: The state vocabulary as a type. Section 6.2 declares these as a bare list of
#: strings and returns a bare ``str``; D-029 requires an enumerated field be
#: typed as ``Literal`` so a typo cannot fall through a comparison into a
#: permissive branch. ``value`` on the returned ``ModelResult`` is still the
#: outer union (Section 22.9) — this alias documents what it will *contain*.
RegimeState = Literal[
    "early_expansion",
    "mid_expansion",
    "late_expansion",
    "slowdown",
    "recession",
    "recovery",
    "disinflation",
    "reflation",
    "stagflation",
]

#: The three momentum buckets on the inflation axis.
InflationAxis = Literal["falling", "flat", "rising"]

#: Section 21's regime-tension flag: whether the published label rests on BOTH
#: axes or on one of them.
#:
#: The directive's requirement is that *the regime must not be a single-factor
#: switch.* The classifier has always read two axes, but a reading can land in a
#: cell where **one axis decides the label alone** — the clearest case being a
#: flat inflation momentum (inside the neutral band), where the state is chosen
#: on the growth axis and the inflation axis is not distinguishing anything. The
#: code warned about that in prose; this makes it a structured field a caller can
#: branch on, so a single-axis label cannot be consumed as if it were a two-axis
#: classification.
#:
#: ``NO_REGIME_TENSION``
#:     Both axes contributed. The label is a genuine two-axis partition.
#: ``REGIME_TENSION``
#:     The label was decided by **one** axis. Published rather than suppressed,
#:     because "the growth axis said late_expansion" is a weaker claim than "two
#:     axes agree on late_expansion", and a reader needs to know which they hold.
#:     The specific single-axis condition is named in ``regime_tension_reasons``.
REGIME_TENSIONS: tuple[str, ...] = (
    "NO_REGIME_TENSION",
    "REGIME_TENSION",
)

#: The tension vocabulary as a type, for the same D-029 reason as the others: a
#: bare ``str`` would let a typo fall through a branch that reports *safety*.
RegimeTension = Literal["NO_REGIME_TENSION", "REGIME_TENSION"]

#: The three buckets on the growth axis, in the order the bands partition it.
#:
#: **There is no ``at_trend`` member, deliberately.** An earlier version declared
#: one, and ``_growth_axis`` never returned it — a published contract advertising
#: a value the function cannot produce, which is the same "declared but
#: unreachable" defect class as the state grid itself (D-037, D-045). The
#: near-trend strip is *not* a fourth bucket: it is a sub-split of
#: ``above_trend`` on ``|gap| <= momentum_band`` that the state selection
#: performs, and ``above_trend`` is already the honest name for "at or above the
#: near-trend boundary". A caller reading the axis can tell where the reading
#: landed without a fourth name for it.
GrowthAxis = Literal["deep_contraction", "contraction", "above_trend"]


class RegimeInputs(BaseModel):
    """The two axes the classifier reads, plus the corroborating slack measure.

    All three growth/inflation quantities are already-derived outputs of other
    models — this function composes, it does not compute. Section 21.1's input
    table marks ``regime_state`` DERIVED from ``classify_regime_rule_based()``,
    and the two axes come from ``output_gap`` (Module 7, Tier 1) and
    ``inflation_breadth_score``/CPI momentum (Module 5, Tier 2).

    **``unemployment_gap`` is now read.** Section 6.2 declares it, lists it in
    ``inputs_used``, and never reads it — the D-037 inert-input class. It is
    required here rather than optional because making it optional would let a
    caller silently drop the only corroboration the classifier has, and the
    whole point of a synthesis function is that it composes what is available.
    A caller genuinely without ``u*`` should pass a gap it has flagged, not
    omit the field.
    """

    model_config = ConfigDict(extra="forbid")

    output_gap: float = Field(
        description=(
            "Output gap, percent of potential: (actual - potential) / potential * 100. "
            "NEGATIVE means the economy is below potential. From Module 7's `output_gap`."
        ),
    )
    inflation_yoy: float = Field(
        description=(
            "Headline inflation, percent year-over-year. This is the LEVEL, and it is "
            "read: it is what makes the momentum reading on the second axis "
            "interpretable (2% falling is a different situation from 8% falling)."
        ),
    )
    inflation_trend_3m: float = Field(
        description=(
            "Inflation MOMENTUM: the 3-month annualized change in the price level, "
            "percent. NEGATIVE means inflation is DECELERATING, not that it is low. "
            "This axis decides disinflation vs reflation, so the sign convention is "
            "load-bearing — a reader who assumes levels reads every label backwards."
        ),
    )
    unemployment_gap: float = Field(
        description=(
            "Unemployment gap, u - u*, in percentage points. POSITIVE means the labour "
            "market is slacker than its natural rate, which AGREES with a NEGATIVE "
            "output gap. u* is UNOBSERVABLE (Section 21.4 item 13), so this input "
            "propagates that unobservability into the confidence."
        ),
    )
    output_gap_change: float | None = Field(
        default=None,
        description=(
            "Change in the output gap since the previous period, in pp. OPTIONAL, and "
            "the only way `recovery` becomes reachable: a regime name that describes a "
            "DIRECTION of travel (activity climbing back toward potential) cannot be "
            "decided from a single level. When supplied and negative, a contracting "
            "economy with falling inflation is `recovery` rather than `slowdown`; when "
            "None, the direction is unknown and the state is `slowdown`, with a "
            "warning saying why."
        ),
    )
    data_quality_flags_present: bool = Field(
        default=False,
        description="True if any input carried a Section 5.4 data-quality flag.",
    )

    @property
    def slack_corroborated(self) -> bool:
        """Whether the two slack measures agree in SIGN.

        ``output_gap`` and ``unemployment_gap`` point in **opposite**
        directions: ``+1.0`` output gap and ``-0.5`` unemployment gap are the
        same economy. So the comparison is ``output_gap`` against
        ``-unemployment_gap``.

        Getting this backwards makes a clean corroboration read as a flat
        contradiction, and the wrong answer is a plausible ``CONTRADICTED``
        verdict rather than an exception — a pairing-axis defect of the D-031
        class. Asserted directly in the tests and recomputed by the live check.

        A gap of exactly zero on either axis is treated as **no evidence**, not
        as agreement: ``0.0 * anything`` is zero, so a naive product-of-signs
        test would count a degenerate reading as corroboration.
        """
        if self.output_gap == 0.0 or self.unemployment_gap == 0.0:
            return False
        return (self.output_gap < 0.0) == (self.unemployment_gap > 0.0)


def _inflation_axis(trend: float, neutral_band: float) -> InflationAxis:
    """Bucket inflation momentum into falling / flat / rising.

    Section 6.2 writes bare ``< 0`` / ``> 0`` tests with no ``== 0`` case, so a
    momentum reading of exactly ``0.0`` — plausible, since it is computed from
    rounded published indices — is classified by whichever branch's ``else``
    catches it rather than by a rule. This makes the flat case explicit, in the
    same shape as D-040's correction to ``qe_qt_stance``.

    ``abs(trend) <= neutral_band`` is inclusive, so the band is closed and two
    adjacent buckets cannot both reject a boundary value.
    """
    if trend > neutral_band:
        return "rising"
    if trend < -neutral_band:
        return "falling"
    return "flat"


def _growth_axis(gap: float, settings_recession: float, settings_weak: float) -> GrowthAxis:
    """Bucket the output gap into the three bands the state grid partitions.

    The bands are **half-open and exhaustive by construction**: ``<`` on each
    threshold means a value exactly on a boundary is assigned by the first test
    that admits it, and the three tests together partition the whole real line
    with no gap between them. The final bucket is a bare fallthrough *because*
    the two tests above it are its entire complement — that is a property of the
    band count, not of a guard. An earlier version of this docstring claimed a
    ``>= settings_late`` test that the signature does not even receive a
    threshold for; the claim described a guard the code never had.

    A value exactly on ``settings_weak`` is therefore ``above_trend``, not
    ``contraction``: the boundary belongs to the upper band. This is pinned by a
    test that sits exactly on each configured threshold, so a change of
    comparison operator is observable rather than silently shifting every
    boundary reading into the neighbouring state.
    """
    if gap < settings_recession:
        return "deep_contraction"
    if gap < settings_weak:
        return "contraction"
    return "above_trend"


def _select_state(
    growth: GrowthAxis,
    inflation: InflationAxis,
    *,
    gap: float,
    momentum_band: float,
    gap_change: float | None,
) -> RegimeState:
    """The state grid: nine reachable cells over two axes.

    Every one of the declared nine states is produced by at least one cell, and
    the grid is total — no cell is empty and no input falls outside it. That
    totality is the correction to the specification, which could reach six.

    Read by the bucket pair, the grid is:

    ========================  ==============  ==============  ================
    growth axis               falling         flat            rising
    ========================  ==============  ==============  ================
    ``above_trend``,          disinflation    reflation       late_expansion
    gap > band
    ``above_trend``,          early_expansion mid_expansion   reflation
    -band <= gap <= band
    ``contraction``           recovery¹/      slowdown        stagflation
                              slowdown
    ``deep_contraction``      recession       recession       recession
    ========================  ==============  ==============  ================

    ¹ ``contraction`` + ``falling`` is ``recovery`` when
    ``output_gap_change > 0`` and ``slowdown`` otherwise — see below.

    Note ``above_trend`` is a single growth bucket — it covers
    ``gap >= weak_growth_gap``, which includes the near-trend strip as well as
    genuine expansions — and the state selection splits it a second time on
    ``|gap| <= momentum_band`` and then once more on the sign of the gap within
    that band. The three-row presentation above is the *cell* grid (which cell a
    reading lands in), not the growth-axis vocabulary, which has three members.
    An earlier version of this docstring described four growth buckets including
    an ``at_trend`` the code never produced; see :data:`GrowthAxis`.

    Three deliberate asymmetries, each a substantive judgement rather than a
    filling-in of a table:

    * **Depth beats direction.** ``deep_contraction`` returns ``recession``
      regardless of the inflation axis. A 3% negative output gap is a
      recession whether inflation is rising or falling — the specification
      returned ``early_expansion`` for the rising case, which is the sharpest
      single error in this function.
    * **``contraction`` maps to ``slowdown`` for both non-rising cases.** Below
      trend but not contracting: the economy is slowing, and whether inflation
      is falling or flat does not distinguish the state. Rising inflation here
      is ``stagflation`` — the specification's own pairing, kept.
    * **``above_trend`` with falling inflation is ``disinflation``; with rising
      inflation it is ``late_expansion``.** Both are the specification's own
      pairings, kept.

    The three states the specification declared and could not reach are placed
    where the mechanism each names requires:

    * ``early_expansion`` — inside the near-trend band and still **below
      potential** (``-band <= gap < 0``), with inflation not rising. This is
      Section 6.2's own definition (``mid_expansion`` requires ``gap > 0``),
      read against the band rather than a bare zero so a revision of a few
      basis points does not flip the label. The specification put this state in
      its ``else``, which its earlier branches made unreachable.
    * ``reflation`` — inflation momentum has stopped falling (``flat`` or
      ``rising``) while growth is at or above trend. Section 15's
      ``FACTOR_REGIME_MAP`` gives it ``value`` and ``momentum`` both positive,
      which is exactly this pairing, and it is the mirror of ``disinflation``
      across the momentum axis.
    * ``recovery`` — **reachable only when ``gap_change`` is supplied.** A
      ``recovery`` is by definition a phase in which activity is *climbing back*
      toward potential, and a level cannot show a direction of travel. Its cell
      is ``contraction`` with falling inflation — the same cell ``slowdown``
      occupies — so the two are separated by the sign of ``gap_change``: a
      contracting economy whose gap is *narrowing* (``gap_change > 0``) is
      recovering; one whose gap is *widening* (``gap_change <= 0``) or whose
      direction is unknown (``gap_change is None``) is slowing. Deciding it any
      other way would assert a turning point the function has not observed,
      which is the failure mode Section 1.1 warns about for lagging data.

    Because two of these three depend on a band or an optional input, the
    function emits a warning whenever the reading lands in a cell whose state
    was decided by an assumption rather than by a measurement. A reader is
    therefore never left believing the vocabulary is fully exercised when it is
    not.
    """
    if growth == "deep_contraction":
        return "recession"
    if growth == "contraction":
        if inflation == "rising":
            return "stagflation"
        # Falling or flat momentum below trend. Split slowdown from recovery on
        # the DIRECTION of the gap, which is the only thing that distinguishes
        # them: recovery needs the gap to be closing.
        if inflation == "falling" and gap_change is not None and gap_change > 0.0:
            return "recovery"
        return "slowdown"
    # growth == "above_trend": this bucket spans the near-trend strip up to a
    # full-bore expansion, so it is split once more on the gap itself.
    if abs(gap) <= momentum_band:
        # AT TREND: the gap is inside the hysteresis band. Which state this is
        # depends on WHERE in the band, and the sign is the only thing that
        # separates an economy still climbing into trend from one that has
        # settled onto it — Section 6.2's own distinction between
        # `early_expansion` and `mid_expansion`, kept, but read against the
        # band rather than against a bare zero so it survives a revision.
        if inflation == "rising":
            # At trend with inflation turning up: reflation, not expansion.
            return "reflation"
        if gap < 0.0:
            # Below potential but inside the band, inflation not rising:
            # activity is climbing back toward trend. This is the state the
            # specification declared and could not reach.
            return "early_expansion"
        return "mid_expansion"
    # Genuinely above the near-trend band.
    if inflation == "rising":
        return "late_expansion"
    if inflation == "falling":
        return "disinflation"
    return "reflation"


def _thresholds_calibrated() -> bool:
    """Whether the regime bands carry a calibrated status rather than a literal.

    Read from config rather than hardcoded so that calibrating the bands flips
    the confidence penalty off by itself. The closest available confidence
    factor is ``is_heuristic_not_calibrated`` — Section 22.8's four factors have
    no entry for "the bands are illustrative but the structure is sound", and
    these bands are Section 6.2's own literals.

    Uses the module-level ``get_settings`` rather than importing it locally.
    Both spellings work at runtime, but a local import binds the name *inside*
    this function and so cannot be redirected by patching the module attribute —
    which makes the confidence factor untestable, and made the first version of
    this file's tests pass against the real config while believing they were
    running against a synthetic one.
    """
    settings = get_settings().regime
    return all(
        leaf.calibration_status != "uncalibrated_illustrative"
        for leaf in (
            settings.recession_output_gap_max,
            settings.weak_growth_output_gap_max,
            settings.late_expansion_output_gap_min,
            settings.disinflation_output_gap_max,
            settings.neutral_inflation_trend_band_pp,
            settings.growth_momentum_band_pp,
        )
    )


def regime_tension(
    growth: GrowthAxis,
    inflation: InflationAxis,
    *,
    inflation_trend_3m: float,
    neutral_band: float,
) -> tuple[RegimeTension, list[str]]:
    """Whether the regime label rests on BOTH axes or on one (Section 21).

    The directive's requirement: *the regime must not be a single-factor switch;
    flag ``REGIME_TENSION``.* The classifier reads two axes and always has, so
    the requirement is **not** "read two axes" — it is "say when one of them did
    not actually distinguish anything". Two conditions produce a single-axis
    label, and both are measured facts about the reading rather than guesses:

    **1. Flat inflation momentum.** ``|inflation_trend_3m| <= neutral_band``
    means the inflation axis is inside its neutral band, so it did not separate
    ``falling`` from ``rising`` — the state was chosen on the growth axis alone.
    This is the condition the classifier has warned about in prose since it was
    written; here it becomes structured.

    **2. Inflation momentum exactly at the band edge is NOT flat.** The test is
    ``<=``, matching ``_inflation_axis``'s own boundary so the two cannot
    disagree about whether a reading was neutral.

    Returns the flag and the list of reasons, both published on the result. An
    empty reason list with ``REGIME_TENSION`` would be an unexplainable flag, so
    the two are computed together and cannot diverge.
    """
    reasons: list[str] = []

    if abs(inflation_trend_3m) <= neutral_band:
        reasons.append(
            f"inflation momentum {inflation_trend_3m:+.2f}pp is inside the "
            f"+/-{neutral_band:.2f}pp neutral band, so the inflation axis read "
            f"'{inflation}' and did not distinguish a direction — the state was "
            f"chosen on the growth axis ('{growth}') ALONE"
        )

    if growth == "deep_contraction":
        # Depth beats direction by design (see _select_state): the inflation axis
        # is not consulted at all for a deep contraction, so the label is
        # single-axis even when momentum is two-sided.
        reasons.append(
            "growth is 'deep_contraction', for which the classifier returns "
            "'recession' regardless of the inflation axis by design — the "
            "inflation reading was not consulted"
        )

    return ("REGIME_TENSION" if reasons else "NO_REGIME_TENSION"), reasons


def classify_regime_rule_based(inputs: RegimeInputs) -> ModelResult:
    """Place the economy in one of nine regime cells, from two measured axes.

    ``value`` is a ``dict`` carrying the state **and** the evidence that
    produced it. The state alone is not enough to act on: Section 12's
    "divergence is information" principle means a reader must be able to see
    which axis chose the label and whether the two slack measures agreed. So the
    dict publishes the state, both bucketed axes, the raw values, the
    corroboration verdict, and the base rate — the frequency at which this state
    actually occurs (D-029). A regime that fires in 80% of periods is not a
    regime, and a reader cannot know that from the label.

    Confidence comes from ``compute_confidence()`` and **not** from the
    specification's hardcoded ``confidence=0.5`` (Section 22.8). The factors
    that go into it are facts about this computation:

    * ``is_heuristic_not_calibrated`` — the six bands are Section 6.2's own
      illustrative literals, so this reads ``True`` today and would read
      ``False`` if a phase calibrated them.
    * ``depends_on_unobservable`` — the output gap is measured against
      **potential**, which is unobservable by nature (Section 21.4 item 13), and
      ``unemployment_gap`` is measured against an unobservable ``u*``. Two of
      the three inputs inherit model-dependent quantities.
    * ``source_independence_count`` — **0, deliberately**. ``output_gap`` and
      ``unemployment_gap`` are two surveys of one concept (slack), not two
      independent concepts. Agreement between them narrows the measurement
      error on slack; it does not supply a second, disjoint family of evidence.
      Claiming 1 here would be exactly the "signal count mistaken for source
      independence" error Section 12 warns about.
    """
    settings = get_settings().regime

    band = settings.neutral_inflation_band
    inflation = _inflation_axis(inputs.inflation_trend_3m, band)
    growth = _growth_axis(inputs.output_gap, settings.recession_gap, settings.weak_growth_gap)
    state = _select_state(
        growth,
        inflation,
        gap=inputs.output_gap,
        momentum_band=settings.growth_momentum_band,
        gap_change=inputs.output_gap_change,
    )

    # Section 21: flag a label that rests on one axis. Computed from the same
    # readings the state was chosen from, so the flag and the label cannot
    # disagree about which axis was decisive.
    tension, tension_reasons = regime_tension(
        growth,
        inflation,
        inflation_trend_3m=inputs.inflation_trend_3m,
        neutral_band=band,
    )

    # --- the base rate (D-029) -------------------------------------------
    base_rates = settings.base_rates
    state_base_rate: float | None = None
    if base_rates.measured:
        state_base_rate = base_rates.rate_map[state]

    warnings: list[str] = [
        "Rule-based only — a deterministic partition of two thresholds, NOT a "
        "probabilistic regime estimate. Section 6.2 defers the Markov-switching "
        "model (statsmodels.tsa.regime_switching) to Phase 5+, and until it "
        "replaces this, the confidence is a statement about the INPUTS, not about "
        "the probability that the label is correct.",
        "The inflation axis is MOMENTUM (3-month annualized change), not the level: "
        "'disinflation' means inflation is DECELERATING, possibly from 8% toward 6%, "
        "not that inflation is low. Reading the label as a level inverts its meaning.",
    ]

    if base_rates.measured:
        assert state_base_rate is not None  # narrowing; measured implies a rate
        warnings.append(
            f"The state is a CATEGORICAL from threshold comparisons on two axes. Over "
            f"{base_rates.observations_measured} measured observations this state "
            f"occurred in {state_base_rate:.1%} of them, which is the frequency a "
            f"reader needs before treating the label as notable (D-029)."
        )
        # The axis base rate, disclosed because it is what makes the state base
        # rates interpretable. A near-constant axis makes every state that needs
        # a non-constant reading rare by CONSTRUCTION rather than by economic
        # fact -- and a reader looking at a rare label cannot tell the two apart
        # without this number.
        warnings.append(
            f"INFLATION-AXIS BASE RATE: over the same {base_rates.observations_measured} "
            f"observations the inflation axis read 'rising' in "
            f"{settings.rising_inflation_base_rate:.1%} of them. The axis is defined on "
            f"the SIGN of a 3-month ANNUALIZED change -- a month-over-month measure -- "
            f"and the price level falls in only a small minority of months, so 'rising' "
            f"is closer to a constant than to a finding. Any state requiring a "
            f"non-rising axis ('disinflation', 'early_expansion', 'slowdown', "
            f"'recovery') is therefore rare BY CONSTRUCTION, not by economic fact. "
            f"Measured alternatives over the same window give a genuinely two-sided "
            f"axis -- see OPEN_ISSUES O-23."
        )
    else:
        warnings.append(
            "NO BASE RATE AVAILABLE: the published state frequencies have not been "
            "measured on live data yet (regime.base_rates.observations_measured is 0). "
            "Without the frequency the label cannot be judged unusual, and it also "
            "means no live run has yet demonstrated that every declared state is "
            "reachable — the correction to Section 6.2 rests on the unit tests alone."
        )

    if not inputs.slack_corroborated:
        if inputs.output_gap == 0.0 or inputs.unemployment_gap == 0.0:
            warnings.append(
                f"SLACK CORROBORATION ABSENT: one of the two slack measures is exactly "
                f"zero (output_gap={inputs.output_gap:+.2f}, "
                f"unemployment_gap={inputs.unemployment_gap:+.2f}), so it carries no "
                f"sign and cannot corroborate the other. This is reported as no "
                f"evidence, not as agreement — a product-of-signs test would count it "
                f"as corroboration."
            )
        else:
            warnings.append(
                f"SLACK MEASURES DISAGREE: the output gap ({inputs.output_gap:+.2f}%) "
                f"says "
                f"{'below' if inputs.output_gap < 0 else 'above'} potential while the "
                f"unemployment gap ({inputs.unemployment_gap:+.2f}pp) says the labour "
                f"market is "
                f"{'slack' if inputs.unemployment_gap > 0 else 'tight'}. These should "
                f"point the same way; when they do not, the regime label rests on one "
                f"measurement of a single unobservable concept and should be treated as "
                f"weaker than its confidence suggests. Section 12: divergence is "
                f"information — investigate before acting."
            )

    if tension == "REGIME_TENSION":
        warnings.append(
            "REGIME_TENSION (Section 21): this label was decided by ONE axis, not "
            "two, so it is a weaker claim than a two-axis classification. Reasons: "
            + "; ".join(tension_reasons)
            + ". Do not consume the state as if both axes agreed on it."
        )

    if abs(inputs.inflation_trend_3m) <= band:
        warnings.append(
            f"Inflation momentum is FLAT ({inputs.inflation_trend_3m:+.2f}pp, inside the "
            f"+/-{band:.2f}pp neutral band), so the inflation axis is not distinguishing "
            f"anything on this reading. The state was chosen on the growth axis alone. "
            f"Section 6.2's bare `> 0` / `< 0` tests have no `== 0` case, so a reading of "
            f"exactly zero fell through to whichever branch's `else` caught it; the band "
            f"makes the flat case explicit rather than incidental."
        )

    if abs(inputs.output_gap) <= settings.growth_momentum_band:
        warnings.append(
            f"The output gap is AT TREND ({inputs.output_gap:+.2f}%, inside the "
            f"+/-{settings.growth_momentum_band:.2f}pp band), so the label is stable "
            f"under a revision of a few basis points. Section 6.2 splits "
            f"`mid_expansion` from `early_expansion` on the raw SIGN of the gap, so a "
            f"gap oscillating around zero flips the regime label every period without "
            f"the economy changing."
        )

    if state == "recession":
        warnings.append(
            "RECESSION is a severe label returned by a threshold comparison on a "
            "REVISED, model-dependent output gap that is itself measured against an "
            "unobservable potential. Section 1.1's lagging-data point applies directly: "
            "the official dating of a recession arrives long after it begins, and this "
            "label can be produced by a gap estimate revision alone."
        )

    if growth == "contraction" and inflation == "falling" and inputs.output_gap_change is None:
        # The one cell where `recovery` is decided: it needs the DIRECTION of the
        # gap, which the caller did not supply.
        warnings.append(
            "SLOWDOWN, NOT RECOVERY — the distinction was not decidable. This reading "
            "(below trend, inflation decelerating) is the cell where `recovery` and "
            "`slowdown` coincide, and they are separated only by whether the output gap "
            "is CLOSING or WIDENING. No `output_gap_change` was supplied, so the "
            "direction of travel is unknown and the less assertive label was returned. "
            "Supply `output_gap_change` to make `recovery` reachable; the three states "
            "`slowdown`, `recovery` and `reflation` are the ones Section 6.2 declared "
            "but its logic could never produce."
        )

    confidence = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=inputs.data_quality_flags_present,
            is_heuristic_not_calibrated=not _thresholds_calibrated(),
            # Two surveys of ONE concept (slack), not two independent concepts.
            source_independence_count=0,
            # The output gap is measured against unobservable potential, and
            # unemployment_gap against unobservable u*.
            depends_on_unobservable=True,
        )
    )

    base_rate_display = (
        f"{state_base_rate:.1%}" if state_base_rate is not None else "not yet measured"
    )
    # Published for the same reason the state base rate is: a reader cannot judge
    # whether `rising` is a finding or a near-constant without it, and a config
    # leaf that no code path reads is a mutation that cannot be killed.
    axis_base_rate = settings.rising_inflation_base_rate if base_rates.measured else None
    return ModelResult(
        model_name="classify_regime_rule_based",
        country="us",
        as_of=utc_now(),
        value={
            "state": state,
            "growth_axis": growth,
            "inflation_axis": inflation,
            "output_gap_pct": round(inputs.output_gap, 4),
            "unemployment_gap_pp": round(inputs.unemployment_gap, 4),
            "inflation_yoy_pct": round(inputs.inflation_yoy, 4),
            "inflation_trend_3m_pp": round(inputs.inflation_trend_3m, 4),
            "slack_corroborated": inputs.slack_corroborated,
            "state_base_rate": state_base_rate,
            "rising_inflation_base_rate": axis_base_rate,
            # Section 21: whether BOTH axes decided the label. A consumer that
            # treats the state as a two-axis classification reads this first.
            "regime_tension": tension,
            "regime_tension_reasons": tension_reasons,
        },
        confidence=confidence,
        interpretation=(
            f"Rule-based regime: {state} — output gap {inputs.output_gap:+.2f}% "
            f"({growth}), inflation momentum {inputs.inflation_trend_3m:+.2f}pp "
            f"({inflation}) at a level of {inputs.inflation_yoy:.2f}% YoY"
        ),
        context=(
            f"Two-axis partition. Growth: {growth}. Inflation momentum: {inflation} "
            f"(neutral band +/-{band:.2f}pp). Slack corroboration: "
            f"{'agrees' if inputs.slack_corroborated else 'does not agree'}. "
            f"State frequency: {base_rate_display}."
        ),
        inputs_used=[
            "output_gap",
            "inflation_yoy",
            "inflation_trend_3m",
            "unemployment_gap",
        ],
        warnings=warnings,
        # --- Section 3/4: the reasoning object, populated -------------------
        unit="categorical (regime state label)",
        direction=(
            f"growth axis: {growth}; inflation momentum axis: {inflation} "
            f"(the state '{state}' is the joint read of the two)"
        ),
        assumptions=[
            "The two axes are a SUFFICIENT summary of the macro state: the state "
            "grid partitions growth x inflation momentum and nothing else enters "
            "the label. An economy distinguished by a third dimension (credit, "
            "fiscal, external) is not expressible in this grid.",
            "The output gap is computed against POTENTIAL, which is unobservable "
            "by nature (Section 21.4 item 13); the label inherits whatever error "
            "the potential estimate carries.",
            "u* is unobservable (Section 21.4 item 13). It is taken from "
            "settings.phillips.nairu.value, CBO's published estimate, and is "
            "treated as a constant rather than as an estimate with its own error "
            "band.",
            "Thresholds are Section 6.2's illustrative literals, not estimated "
            "from data (see `limitations`).",
        ],
        data_provenance=[
            "output_gap — computed upstream by output_gap_from_snapshot and passed "
            "in; not re-derived here (passing it is what keeps one implementation)",
            "inflation_yoy — CPIAUCSL (BLS headline CPI via FRED) year-over-year percent",
            "inflation_trend_3m — CPIAUCSL 3-month annualized momentum, "
            "computed upstream by the orchestrator's _inflation_momentum_3m",
            "unemployment_gap — UNRATE (BLS) minus u* from settings.phillips.nairu.value",
        ],
        # Empty because this function receives floats, not dated observations.
        # Stated here rather than left to be inferred from the empty dict: the
        # vintage of each input is knowable one layer up, in the orchestrator,
        # which holds the ObservationPoints. Leaving it empty is a consequence
        # of the signature, and a consumer should read it that way.
        limitations=[
            "RULE-BASED, NOT PROBABILISTIC: this partitions two thresholds; it "
            "does not estimate a regime probability. Section 6.2 defers the "
            "Markov-switching model (statsmodels.tsa.regime_switching) to Phase "
            "5+, and until it replaces this the output is a label, not a "
            "likelihood.",
            "The inflation axis is MOMENTUM (3-month annualized change), NOT the "
            "level: 'disinflation' means inflation is DECELERATING — possibly "
            "from 8% toward 6% — not that inflation is low. Reading the label as "
            "a level inverts its meaning.",
            "`output_gap_change` is optional and, when absent, `recovery` is "
            "unreachable: the three states `slowdown`, `recovery` and "
            "`reflation` were declared by Section 6.2 but its logic could never "
            "produce all three. A caller that omits the argument cannot receive "
            "`recovery`, by construction rather than by data.",
            "The inflation axis is defined on the SIGN of a 3-month annualized "
            "change, a month-over-month measure. The price level falls in only a "
            "small minority of months, so 'rising' is closer to a constant than "
            "to a finding, and every state requiring a non-rising axis is rare "
            "BY CONSTRUCTION rather than by economic fact (see OPEN_ISSUES "
            "O-23). The measured axis base rate is published in `value`.",
            "Points-in-time: observation dates are NOT supplied by this "
            "function's inputs (it receives floats). The point-in-time filter "
            "upstream is SUFFICIENT BUT NOT SOUND (see models/as_of.py), and no "
            "release or vintage datetime is available on this installation "
            "(Section 6, measured 2026-09-19) — so an as-of-correct run cannot "
            "prove it did not use a revision.",
        ],
        decision_relevance=(
            "Section 16.2's Q1 fourth read (Module 3) and Section 16.4's "
            "`regime` field on the published MacroThesis. Read by `_regime_view` "
            "in the builder; carried into the thesis as the `state` label plus "
            "its base rate. Downstream it qualifies how a reader should weight "
            "every other view on the thesis — it is context, not a signal that "
            "selects an instrument."
        ),
        decision_prohibition=[
            "MUST NOT be read as a probability, a likelihood, or a forecast. It "
            "is a deterministic partition of two thresholds (Section 6.2).",
            "MUST NOT be treated as a two-axis classification when "
            "`value['regime_tension'] == 'REGIME_TENSION'`: in that case ONE "
            "axis decided the label (Section 21) and the published reasons say "
            "which. Consuming it as if both axes agreed is the error the flag "
            "exists to prevent.",
            "MUST NOT be used alone to stand a thesis down. The significance "
            "test is Q6 (Section 16.3), and Section 16.3's order puts the reads "
            "before it. A missing or surprising regime is information, not a "
            "gate.",
            "MUST NOT be consumed without the state base rate when it is "
            "available: a regime that fires in 80% of periods is not a regime, "
            "and the label cannot be judged unusual without its frequency "
            "(D-029).",
        ],
    )


# =============================================================================
# Module 1 — the trilemma check (Section 15.20-A, Section 18.1, Section 18.7)
# =============================================================================

#: The four severities, as a closed vocabulary (D-029).
#:
#: The tuple and the :data:`TrilemmaSeverity` Literal below are the same set;
#: the tuple exists because ``Literal`` is not iterable at runtime and the
#: coverage test needs to iterate the declared vocabulary. The assertion at the
#: bottom of this module pins the two together, so they cannot drift.
TRILEMMA_SEVERITIES: tuple[str, ...] = (
    "CRITICAL_PEG_STRESS",
    "TRILEMMA_VIOLATION",
    "TRILEMMA_TENSION",
    "NO_TENSION",
)

#: The severity vocabulary as a type. Section 15.20-A returns a bare ``str``
#: from a chain of comparisons; D-029 requires an enumerated field be typed as
#: ``Literal`` so a typo cannot fall through a comparison into a permissive
#: branch. Here that matters more than usual, because the severities are
#: *ordered in urgency* and the fallthrough in the specification's chain is the
#: branch that **reports safety** — a severity string that matches no branch
#: would be read by a caller as "no problem" rather than as a bug.
TrilemmaSeverity = Literal[
    "CRITICAL_PEG_STRESS",
    "TRILEMMA_VIOLATION",
    "TRILEMMA_TENSION",
    "NO_TENSION",
]

#: The two directions a policy can need. A bare ``str`` in the specification
#: would let ``"easing "`` (trailing space) or ``"Easing"`` compare unequal to
#: every real direction and register as a conflict against everything — the
#: D-029 enumerated-field class, and here the failure is a **false alarm**
#: rather than a silent pass, which is why it is typed rather than validated.
PolicyDirection = Literal["easing", "tightening"]


class TrilemmaInputs(BaseModel):
    """The structural classification of a currency regime, plus its reserves trend.

    The first three fields are **not measured from a series — they are
    classifications of institutional structure**, supplied by the caller. Section
    21.1 names no route for any of them, and none can exist: "does this country
    operate a fixed or managed exchange rate" is a legal-institutional fact, not
    an observation in a time series. They are manual by construction, which is a
    disclosed limitation (O-28) and is **priced into the confidence** — a
    misclassified peg makes every downstream severity wrong at once, and no
    series exists that could disagree with the caller.

    ``country`` is required and **guarded**: this build implements ``us`` only
    (Section 22.3), and for the United States ``has_fixed_or_managed_fx`` is
    always ``False`` — so the function can only ever return ``NO_TENSION`` for
    the one country it supports. See the function docstring; this is a
    structural consequence of the honest scope, not an oversight.

    ``reserves_trend_pct_change_3mo`` and ``reserves_trend_pct_change_1mo`` are
    **fractions, not percentages** — ``-0.0725`` is Black Wednesday's month.
    The units are load-bearing and are the reason both fields carry the suffix
    ``pct_change`` while still being fractions: the same name could hold
    ``-7.25`` under the other convention and every threshold comparison would
    invert. The docstring states the convention; the tests pin it.
    """

    model_config = ConfigDict(extra="forbid")

    country: str = Field(
        description='ISO-3166 alpha-2 lowercase. Only "us" is implemented (Section 22.3).',
    )
    has_fixed_or_managed_fx: bool = Field(
        description=(
            "MANUAL CLASSIFICATION, not a series. True if the currency operates a "
            "fixed or heavily managed exchange rate. For 'us' this is structurally "
            "False — the dollar floats."
        ),
    )
    has_free_capital_movement: bool = Field(
        description=(
            "MANUAL CLASSIFICATION, not a series. True if capital moves freely across the border."
        ),
    )
    claims_monetary_independence: bool = Field(
        description=(
            "MANUAL CLASSIFICATION, not a series. True if the central bank sets policy "
            "for domestic objectives rather than pegging to another currency."
        ),
    )
    domestic_policy_direction_needed: PolicyDirection | None = Field(
        default=None,
        description=(
            "What DOMESTIC conditions call for: 'easing' or 'tightening'. None means "
            "unassessed. Compared against peg_defense_direction_required; a mismatch is "
            "the direction conflict."
        ),
    )
    peg_defense_direction_required: PolicyDirection | None = Field(
        default=None,
        description=(
            "What DEFENDING THE PEG requires: 'tightening' to support a weak currency, "
            "'easing' to resist appreciation. None means unassessed."
        ),
    )
    reserves_trend_pct_change_3mo: float | None = Field(
        default=None,
        description=(
            "FRACTION (not percent): the 3-month change in total reserves excluding "
            "gold, e.g. -0.0537 for -5.37%. NEGATIVE means reserves are DEPLETING. "
            "This is the specification's measure; it is a TREND, and it LAGS."
        ),
    )
    reserves_trend_pct_change_1mo: float | None = Field(
        default=None,
        description=(
            "FRACTION (not percent): the 1-month change in total reserves excluding "
            "gold, e.g. -0.0725 for -7.25%. NEGATIVE means reserves are DEPLETING. "
            "NOT in Section 15.20-A — added because the 3-month trend misses the "
            "crisis month of the specification's own worked example (D-048)."
        ),
    )
    data_quality_flags_present: bool = Field(
        default=False,
        description="True if any input carried a Section 5.4 data-quality flag.",
    )

    @property
    def all_three(self) -> bool:
        """Whether the currency claims all three trilemma legs simultaneously.

        The trilemma says this is *impossible* — so a caller asserting it is
        either describing a pegged regime that is not really independent, or a
        regime that is not really pegged. Either way it is a contradiction worth
        flagging, which is why this is the first branch rather than an error.

        A currency claiming *fewer* than three legs has no trilemma tension: it
        has simply chosen its two, which is what the trilemma tells it to do.
        """
        return (
            self.has_fixed_or_managed_fx
            and self.has_free_capital_movement
            and self.claims_monetary_independence
        )

    @property
    def direction_conflict(self) -> bool:
        """Whether domestic needs and peg-defense needs point OPPOSITE ways.

        This is the mechanism Section 18.1 names: the BoE had to tighten to
        defend sterling while the domestic economy (in the ERM recession) needed
        easing. **Both directions must be supplied** — an unassessed direction is
        not a conflict, because "we don't know what the peg requires" is not the
        same as "the peg requires the opposite". Treating ``None`` as a conflict
        would make every unassessed input escalate, which is the opposite of
        evidence.

        The comparison is on **strings that must first be unequal to each other**;
        a caller who passes the same direction twice has *agreement*, which is the
        calm case, so the test is inequality rather than membership in a set.
        """
        return (
            self.domestic_policy_direction_needed is not None
            and self.peg_defense_direction_required is not None
            and self.domestic_policy_direction_needed != self.peg_defense_direction_required
        )


def _depletion_severity(
    *,
    all_three: bool,
    direction_conflict: bool,
    trend_3mo: float | None,
    break_1mo: float | None,
    depletion_threshold: float,
    break_threshold: float,
) -> tuple[TrilemmaSeverity, bool, bool]:
    """Place the reading in one of four cells, and report which reserves tests fired.

    The specification's chain is reproduced here with its three defects
    corrected; each correction is a comment on the branch it changes.

    Returns the severity plus the two booleans, so the caller can publish *why*
    without re-deriving them (a second derivation is a second place to get it
    wrong — D-040).
    """
    # CORRECTION 1 — the specification writes
    #
    #     reserves_depleting = (inputs.reserves_trend_pct_change_3mo or 0) < -0.10
    #
    # and `or 0` is a trap: a caller who supplies NO reserves figure is treated
    # as having a reserves change of exactly zero, which is *not* depleting, so
    # the absent input silently counts as evidence of calm. That is the
    # missing-data-as-a-value class. Here an absent measure is absent: it can
    # neither fire nor suppress a branch, and the caller gets a warning saying
    # the escalation was not available.
    depleted_3mo = trend_3mo is not None and trend_3mo < depletion_threshold
    # CORRECTION 2 — the added 1-month measure (D-048). The specified 3-month
    # trend does not fire on Black Wednesday's own month: at 1992-09 the UK's
    # 3-month change is -5.37%, inside the -10% threshold, and the breach first
    # appears the following month. A crisis detector that reports "no tension"
    # during the crisis is not a detector, so the acute 1-month break is tested
    # separately. The two are NOT nested — the Korean 1997 episode breaches each
    # without the other — which is why the acute branch tests the 1-month
    # measure rather than "either".
    broke_1mo = break_1mo is not None and break_1mo < break_threshold

    if all_three and direction_conflict and (depleted_3mo or broke_1mo):
        # CORRECTION 3 — the specification reaches this branch only via
        # `reserves_depleting`. Both measures are admitted here because they are
        # complementary evidence of the same failure at two horizons, and the
        # branch is the same branch either way: a currency defending a peg in
        # the wrong direction while burning reserves IS in critical stress,
        # whether the burn is acute or sustained.
        return "CRITICAL_PEG_STRESS", depleted_3mo, broke_1mo
    if all_three and direction_conflict:
        return "TRILEMMA_VIOLATION", depleted_3mo, broke_1mo
    if all_three:
        return "TRILEMMA_TENSION", depleted_3mo, broke_1mo
    return "NO_TENSION", depleted_3mo, broke_1mo


def _trilemma_thresholds_calibrated() -> bool:
    """Whether BOTH reserves thresholds carry a calibrated status.

    ``all`` rather than ``any``: the escalation rule reads both, so it is only
    as calibrated as its weakest threshold. Read from config so that calibrating
    either one is reflected without a code change, and using the module-level
    ``get_settings`` binding so a test can redirect it (see
    ``_thresholds_calibrated`` for why the local-import spelling is wrong).

    The reference episode is deliberately **not** included: it is a fixture, not
    a parameter, and a fixture's status says nothing about whether the rule is
    calibrated.
    """
    settings = get_settings().regime.trilemma
    return all(
        leaf.calibration_status != "uncalibrated_illustrative"
        for leaf in (
            settings.reserves_depletion_threshold_3mo,
            settings.reserves_break_threshold_1mo,
        )
    )


def _trilemma_base_rates() -> dict[str, float] | None:
    """The measured firing frequency of each reserves test, or ``None`` if unmeasured.

    D-029: a categorical returned by a threshold comparison must travel with the
    frequency at which the comparison fires. It matters more here than for a
    regime label, because the 3-month test fires on **10.6% of all months**
    measured — so "reserves are depleting" is a *precondition*, not a crisis
    signal, and a reader who does not know that will treat the escalation as far
    rarer than it is.

    Returns ``None`` (and the caller discloses its absence) if the base rates
    have not been written into config, rather than returning ``{}`` which reads
    as "measured, and zero".
    """
    settings = get_settings().regime.trilemma
    rates = settings.base_rates
    if not rates.measured:
        return None
    return {
        "depletion_3mo": float(rates.depletion_3mo_base_rate.value),
        "break_1mo": float(rates.break_1mo_base_rate.value),
    }


def check_trilemma_tension(inputs: TrilemmaInputs) -> ModelResult:
    """Flag a pegged currency that is claiming all three trilemma legs at once.

    The trilemma (Module 1, Section 15's Module 1 entry): a currency can have a
    **fixed exchange rate**, **free capital movement**, and **independent
    monetary policy** — but only two of the three. A regime that claims all three
    is asserting something impossible, and the way the impossibility asserts
    itself is the mechanism this function detects: domestic conditions call for
    one policy direction, defending the peg requires the other, and the reserves
    that reconcile them are finite.

    Four severities, escalating with evidence
    -----------------------------------------

    * ``NO_TENSION`` — the currency does not claim all three legs. It picked
      its two, as the trilemma requires.
    * ``TRILEMMA_TENSION`` — all three claimed. Structurally impossible, but no
      evidence of an active conflict yet.
    * ``TRILEMMA_VIOLATION`` — all three claimed **and** domestic needs oppose
      peg-defense needs. This is the operational conflict: the central bank is
      being asked to move rates two ways at once.
    * ``CRITICAL_PEG_STRESS`` — the above **and** reserves are burning. This is
      the exact Black Wednesday (Section 18.1) and Asian Crisis (Section 18.7)
      setup, and it is the severe label.

    Two corrections to the specification's chain
    ---------------------------------------------

    **1. The confidences are computed, not hardcoded.** Section 15.20-A returns
    ``0.7 / 0.6 / 0.4 / 0.8`` as literals. Section 22.8 makes
    ``compute_confidence()`` the only producer of a confidence value, so those
    four numbers are refused. What replaces them is honest and, importantly,
    **different in shape**: the specification's numbers *rise* to 0.8 for
    ``NO_TENSION`` and *fall* to 0.4 for ``TRILEMMA_TENSION``, which reads as a
    probability that the label is right — but no model here estimates that, and
    the function's own inputs are three manual classifications. The computed
    confidence reflects the inputs (manual, uncalibrated, no independent family)
    and is therefore *low and roughly flat across severities*, which is the
    truthful statement: severity is about the world, confidence is about the
    measurement, and this measurement is structurally weak.

    **2. The 3-month trend misses its own worked example.** The specified test
    ``reserves_trend_pct_change_3mo < -0.10`` does **not** fire on 1992-09 —
    the UK's 3-month change that month is ``-5.37%`` — while a 1-month measure
    reads ``-7.25%``, the steepest month in 1992-93. Both are tested and the
    acute one makes the check contemporaneous. The two are complementary rather
    than redundant: on Korea in 1997 the 3-month test fires in September (early
    warning, ``-10.80%``) while the 1-month test fires in November (acute phase,
    ``-20.04%``).

    Scope — this is a non-US function on a US-only build
    ---------------------------------------------------

    Section 22.3 makes Phases 0-4 **US-only**, and ``has_fixed_or_managed_fx``
    for the United States is structurally ``False``. So ``all_three`` is ``False``
    for every admissible US input and the function can only ever return
    ``NO_TENSION``. That is not a defect to hide: it is the honest consequence of
    the scope, and it is why the function carries a **country guard that raises**
    rather than silently labelling. A caller who passes ``"gb"`` gets an explicit
    ``NotImplementedError`` naming the reason; the live check validates the
    *logic* against the UK's fixed 1992 history and Korea's 1997 history as
    **fixtures**, which is a different act from supporting those countries as
    thesis countries. See DECISIONS D-048.
    """
    if inputs.country != "us":
        raise NotImplementedError(
            f"check_trilemma_tension is implemented for country 'us' only; got "
            f"'{inputs.country}' (Section 22.3 / Finding #3). The trilemma is a "
            f"STRUCTURAL property of a currency regime, and a different country needs "
            f"its own verified reserves series and its own central-bank reaction "
            f"function before this can be run on it — it is not a label to re-point. "
            f"The UK and Korean episodes are used as FIXTURES in the live check, which "
            f"is a different act from supporting those countries (D-048)."
        )

    settings = get_settings().regime.trilemma

    all_three = inputs.all_three
    direction_conflict = inputs.direction_conflict
    severity, depleted_3mo, broke_1mo = _depletion_severity(
        all_three=all_three,
        direction_conflict=direction_conflict,
        trend_3mo=inputs.reserves_trend_pct_change_3mo,
        break_1mo=inputs.reserves_trend_pct_change_1mo,
        depletion_threshold=settings.depletion_3mo,
        break_threshold=settings.break_1mo,
    )

    base_rates = _trilemma_base_rates()

    warnings: list[str] = [
        "The three trilemma legs (has_fixed_or_managed_fx, has_free_capital_movement, "
        "claims_monetary_independence) are MANUAL CLASSIFICATIONS of a country's "
        "institutional structure, not series. Section 21.1 names no route for any of "
        "them and none can exist — 'does this country manage its exchange rate' is a "
        "legal-institutional fact, not an observation. A misclassified peg makes every "
        "severity here wrong at once, and no data can disagree with the caller (O-28).",
        "This is a STRUCTURAL check, not a probability. It reports that a configuration "
        "is impossible or is under stress; it does not estimate the probability that the "
        "peg breaks, and it carries no timing. The trilemma says the configuration "
        "cannot persist — it says nothing about when it ends.",
    ]

    if not all_three:
        warnings.append(
            f"NO TRILEMMA TENSION BY CONSTRUCTION: this currency does not claim all "
            f"three legs (fixed_or_managed_fx={inputs.has_fixed_or_managed_fx}, "
            f"free_capital={inputs.has_free_capital_movement}, "
            f"claims_independence={inputs.claims_monetary_independence}). A currency "
            f"that claims two or fewer has simply chosen its two, which is what the "
            f"trilemma instructs — so the check has no tension to report and the "
            f"severity is 'NO_TENSION' regardless of any other input. A reader who "
            f"expects this function to warn about a floating currency is reading the "
            f"wrong function: there is no peg to defend."
        )

    if all_three and not direction_conflict:
        if (
            inputs.domestic_policy_direction_needed is None
            or inputs.peg_defense_direction_required is None
        ):
            missing = [
                name
                for name in (
                    "domestic_policy_direction_needed",
                    "peg_defense_direction_required",
                )
                if getattr(inputs, name) is None
            ]
            warnings.append(
                f"DIRECTION CONFLICT NOT ASSESSABLE: this currency claims all three "
                f"trilemma legs, which is structurally impossible, but the escalation to "
                f"'TRILEMMA_VIOLATION' needs BOTH policy directions and {', '.join(missing)} "
                f"was not supplied. An unassessed direction is NOT a conflict — treating "
                f"it as one would escalate every incomplete input, which is the opposite "
                f"of evidence. Supply both directions to make the violation branch "
                f"reachable."
            )
        else:
            warnings.append(
                f"DIRECTIONS AGREE, ALL THREE LEGS CLAIMED: domestic policy needs "
                f"'{inputs.domestic_policy_direction_needed}' and peg defense needs "
                f"'{inputs.peg_defense_direction_required}', the same direction, so there "
                f"is no operational conflict TODAY. The structural impossibility is still "
                f"present — a regime claiming all three legs is one shock away from an "
                f"impossible position, and the conflict typically appears exactly when a "
                f"shock arrives (Section 18.1: the ERM looked workable until German "
                f"unification put the Bundesbank and the BoE on opposite sides)."
            )

    if all_three and direction_conflict and not (depleted_3mo or broke_1mo):
        warnings.append(
            f"RESERVES NOT TRENDING DOWN, BUT THE CONFLICT IS LIVE: domestic policy "
            f"needs '{inputs.domestic_policy_direction_needed}' while peg defense needs "
            f"'{inputs.peg_defense_direction_required}'. Reserves can only reconcile this "
            f"for a bounded time, and the absence of depletion so far is NOT evidence "
            f"that the position is sustainable — it is evidence that the intervention "
            f"has not begun in earnest. The reserves series "
            f"(reserves_trend_pct_change_3mo={inputs.reserves_trend_pct_change_3mo}, "
            f"reserves_trend_pct_change_1mo={inputs.reserves_trend_pct_change_1mo}) is "
            f"also published at MONTHLY frequency and lags the market: the "
            f"specification's Black Wednesday observation is a 10%->15% rate hike "
            f"reversed within a day, which no monthly reserves figure can resolve "
            f"(Section 18.1)."
        )

    if all_three and direction_conflict and not depleted_3mo and broke_1mo:
        warnings.append(
            "ACUTE BREAK WITHOUT A SUSTAINED TREND: the 1-month reserves change "
            f"({inputs.reserves_trend_pct_change_1mo}) breaches its threshold while the "
            f"3-month trend ({inputs.reserves_trend_pct_change_3mo}) does not. This is "
            "the sharper reading of the two and the one the specification's own test "
            "MISSES — on Black Wednesday's month the UK's 3-month change is -5.37%, "
            "inside the -10% threshold, while the 1-month change is -7.25%. A "
            "1-month-only breach may also be a single large intervention that is then "
            "reversed, so it is evidence of an acute episode rather than of depletion "
            "(D-048)."
        )

    if all_three and direction_conflict and depleted_3mo and not broke_1mo:
        warnings.append(
            "SUSTAINED DEPLETION WITHOUT AN ACUTE BREAK: the 3-month trend "
            f"({inputs.reserves_trend_pct_change_3mo}) breaches its threshold while the "
            f"1-month change ({inputs.reserves_trend_pct_change_1mo}) does not. The trend "
            "test is the EARLIER warning of the two — on Korea the 3-month test fires in "
            "1997-09 (-10.80% against a 1-month reading of only -2.30%), roughly two "
            "months before the acute phase, when the 1-month test reaches -20.04%. "
            "Tension escalating over months is the pattern to act on rather than the "
            "absence of a spike (D-048)."
        )

    if inputs.reserves_trend_pct_change_3mo is None:
        warnings.append(
            "RESERVES TREND ABSENT: no 3-month reserves change was supplied, so the "
            "sustained-depletion branch could not fire. This is NOT recorded as a "
            "reserves change of zero — Section 15.20-A writes "
            "`(reserves_trend_pct_change_3mo or 0)`, which silently converts an absent "
            "input into evidence of calm. An absent measure is absent: it can neither "
            "fire nor suppress an escalation, and the severity may be understated as a "
            "result."
        )

    if base_rates is not None:
        warnings.append(
            f"BASE RATES (D-029): measured over live history, the specified 3-month "
            f"threshold fires in {base_rates['depletion_3mo']:.1%} of all months and the "
            f"added 1-month threshold in {base_rates['break_1mo']:.1%}. A 3-month rule "
            f"that fires on roughly a tenth of months is a PRECONDITION, not a crisis "
            f"signal — the escalation to 'CRITICAL_PEG_STRESS' requires it to coincide "
            f"with all three claimed legs AND a direction conflict."
        )
        warnings.append(
            "BASE-RATE CAVEAT: those frequencies are measured on the UK's and Korea's "
            "reserves history, because the US has no peg to measure. They are the "
            "frequency of the TEST firing, not the frequency of a peg crisis — the "
            "2016-09/10/11 breaches are BREXIT, an earlier-than-expected-exit episode, "
            "not a peg defense. Which of the two readings is correct is not something "
            "these thresholds decide."
        )
    else:
        warnings.append(
            "NO BASE RATE AVAILABLE: the reserves thresholds' firing frequencies have "
            "not been measured and written to config "
            "(regime.trilemma.base_rates.measured is false). Without them a reader "
            "cannot tell a precondition from a crisis signal — and the measured value "
            "makes clear the 3-month test is the former."
        )

    if severity == "CRITICAL_PEG_STRESS":
        warnings.append(
            "CRITICAL_PEG_STRESS matches the Black Wednesday (Section 18.1) and Asian "
            "Crisis (Section 18.7) setup: all three trilemma legs claimed, domestic "
            "policy needing the opposite direction from peg defense, and reserves "
            "burning. Treat any thesis expressed through this currency with extreme "
            "caution, and note Section 18.7's rule that MULTIPLE failing checks "
            "override a favourable statistical signal. Section 1.1 applies: this system "
            "reasons, it does not execute — no position is implied."
        )

    if severity != "NO_TENSION":
        warnings.append(
            "This function is a NON-US check on a US-only build (Section 22.3). It "
            "cannot return anything but 'NO_TENSION' for 'us', because the dollar's "
            "exchange rate is not fixed or managed. A non-'NO_TENSION' severity here "
            "therefore cannot have come from the supported-country path, and any caller "
            "seeing one should verify which country was passed."
        )

    confidence = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=inputs.data_quality_flags_present,
            # The two thresholds are Section 15.20-A's literals plus one fitted
            # assumption, none calibrated against realized outcomes.
            is_heuristic_not_calibrated=not _trilemma_thresholds_calibrated(),
            # NOT a call to count_independent_families(). This function consumes
            # three manual classifications and up to two reserves observations,
            # so there is no list of tagged ModelResults to count — the trilemma
            # legs are not a family in the Section 15.19-D sense, because they
            # are not measured evidence at all. Claiming a family here would be
            # the D-027 circularity error: the function would credit itself with
            # evidence its own caller supplied as an assertion.
            source_independence_count=0,
            # Whether a currency claims all three legs is unobservable in the
            # series sense — it is an institutional classification the caller
            # supplies, and no data can contradict it.
            depends_on_unobservable=True,
        )
    )

    reserves_horizons = [
        name
        for name in (
            "reserves_trend_pct_change_1mo",
            "reserves_trend_pct_change_3mo",
        )
        if getattr(inputs, name) is not None
    ]
    inputs_used = [
        "has_fixed_or_managed_fx",
        "has_free_capital_movement",
        "claims_monetary_independence",
        *(
            name
            for name in (
                "domestic_policy_direction_needed",
                "peg_defense_direction_required",
            )
            if getattr(inputs, name) is not None
        ),
        *reserves_horizons,
    ]

    legs_clause = (
        "all three legs claimed (impossible configuration)"
        if all_three
        else "fewer than three legs claimed"
    )
    return ModelResult(
        model_name="check_trilemma_tension",
        country="us",
        as_of=utc_now(),
        value={
            "severity": severity,
            "all_three_legs_claimed": all_three,
            "direction_conflict": direction_conflict,
            "reserves_depleting_3mo": depleted_3mo,
            "reserves_breaking_1mo": broke_1mo,
            "reserves_trend_pct_change_3mo": inputs.reserves_trend_pct_change_3mo,
            "reserves_trend_pct_change_1mo": inputs.reserves_trend_pct_change_1mo,
            "depletion_threshold_3mo": settings.depletion_3mo,
            "break_threshold_1mo": settings.break_1mo,
            "base_rates": base_rates,
        },
        confidence=confidence,
        interpretation=(
            f"Trilemma status: {severity} — {legs_clause}"
            f"{', policy directions CONFLICT' if direction_conflict else ''}"
            f"{', reserves depleting (3mo)' if depleted_3mo else ''}"
            f"{', acute reserves break (1mo)' if broke_1mo else ''}"
        ),
        context=(
            f"Module 1 (Section 15.20-A), implementing Section 18.1's Black Wednesday "
            f"detection rule and Section 18.7's Asian Crisis mechanism. "
            f"fixed_fx={inputs.has_fixed_or_managed_fx}, "
            f"free_capital={inputs.has_free_capital_movement}, "
            f"claims_independence={inputs.claims_monetary_independence}. "
            f"Severity is about the WORLD; confidence is about the MEASUREMENT and is "
            f"low here because the inputs are manual classifications."
        ),
        inputs_used=inputs_used,
        warnings=warnings,
        source_family=EvidenceSourceFamily.MANUAL_ASSESSMENT,
    )


# D-045a: the declared vocabulary and the runtime tuple must be the same set in
# BOTH directions — every member returned is declared, and every declared member
# is producible. `test_specification_form_cannot_reach_three_of_its_nine_states`
# established the pattern for the regime states; these assert it for the
# severities, where an undeclared severity would be read by a caller as calm.
assert set(get_args(TrilemmaSeverity)) == set(TRILEMMA_SEVERITIES)
assert set(get_args(PolicyDirection)) == {"easing", "tightening"}
