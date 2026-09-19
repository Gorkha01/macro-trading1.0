"""Module 5.3 — inflation sub-measure convergence (Section 15.19-C).

AGENTS.md Section 15.19-C, corrected by D-047 and integrated with Section
15.19-D by D-046.

What the function is for
------------------------
``inflation_breadth_score`` (Module 6.3) answers a yes/no question: do the
available measures point the same way? This asks the graded version — *how
strongly*, on a HIGH/MEDIUM/LOW/CONFLICTED scale — and, critically, **whether
the agreement is real or manufactured by counting one release several times.**

That second question is Section 15.19-D's, and it is the reason this module
depends on ``models.evidence``. Headline CPI, core CPI, trimmed-mean CPI (in its
Cleveland Fed form) and the Atlanta Fed sticky-price measures are all ultimately
built from **the BLS CPI survey**; five of them agreeing is one observation
reported five times. The Dallas Fed trimmed-mean PCE is a separate production
process, core PCE is a separate BEA release, and a TIPS breakeven would be
market pricing. ``count_independent_families`` is what tells those apart, and
**this function is its first caller** — the obligation Section 15.19-D places on
every convergence classifier in the system.

Four corrections to Section 15.19-C are implemented here
-------------------------------------------------------
Each is measured rather than argued, and each is recorded in DECISIONS as
**D-047**.

**1. The conflict gate examined two measures and ignored the rest.** The
specification sets ``CONFLICTED`` when ``headline_cpi_direction *
core_cpi_direction < 0`` and never looks at anything else. So a month in which
headline and core agree while three of the four remaining measures oppose is
reported as convergence. Measured over 522 real months, that happens **14 times
(2.7%), 7 of which the specification's logic calls HIGH**. A genuine conflict is
not a property of two particular members — it is a property of **how the whole
set splits** — so the corrected gate also fires when the losing side carries at
least ``deep_conflict_share_threshold`` of the measures.

**2. The classifier could not see that it was reporting the base state.**
Measured over the same 522 months, a three-measure sign test returns **HIGH in
86.6% of months** and the six-measure form in **89.5%**. The cause is not the
thresholds: the price *level* rises in 87.8% (headline), 90.7% (core) and 97.9%
(core PCE) of months, so unanimity-positive is the **base state rather than a
finding**. This is O-23's pathology — a near-constant axis — one layer up. The
function therefore publishes ``base_rates`` in ``value`` and warns with the
measured share, so a reader seeing HIGH can tell construction from economics.
It does **not** silently retune the specification's 0.8/0.6 thresholds: that
would be a specification decision, and the disclosure is the honest half.

**3. The two thresholds are degenerate below five measures.** The attainable
agreement fractions at ``n`` measures are the multiples of ``1/n``, so at the
specification's own Phase 1 configuration (n=3) ``>= 0.8`` requires
**unanimity** and ``0.6 <= frac < 0.8`` is the single value **2/3** — a knife
edge, not a band. ``value`` publishes the attainable-fraction count and a warning
fires when the configured thresholds do not separate it.

**4. Three of the six measures were recorded as unreachable and two are not.**
Section 21.1 marks ``supercore_direction`` BLOCKED (correctly — O-8 establishes
there is no valid BLS construction) and ``trimmed_mean_direction`` /
``median_cpi_direction`` BLOCKED → MANUAL. **Two of those three are live on
FRED**: Dallas Fed's ``PCETRIM1M158SFRBDAL`` and Cleveland Fed's
``MEDCPIM157SFRBCLE``. They were never found because the route that finds them
was never searched — the O-21 defect class, third occurrence. The classifier
therefore runs at **six measures**, and the ``supercore`` slot is filled by the
Atlanta Fed's **sticky-price CPI**, which is a *different measure* and is named
as such rather than substituted silently (Section 21.1 rule 4's prohibition is
about mislabelling, and the O-8 incident is the canonical example).

A units trap, recorded because it is silent
-------------------------------------------
The five CPI-derived inputs reach this function as **month-over-month percent
changes**. ``PCETRIM1M158SFRBDAL`` is published as a **percent change at an
annual rate** — roughly twelve times larger for the same month. The function
consumes only the **sign** of each measure, so the scale is irrelevant here; but
a caller that later adds magnitude handling has a factor-of-twelve hazard sitting
in one of six symmetric-looking inputs. The input model's docstring says so.
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
from macro_engine.models.evidence import (
    count_independent_families,
    tag_evidence_source,
)
from macro_engine.models.evidence_family import EvidenceSourceFamily as _Family

__all__ = [
    "CONVERGENCE_CLASSES",
    "InflationConvergenceInputs",
    "InflationConvergenceVerdict",
    "inflation_convergence_classifier",
]

# The published vocabulary. Declared as a tuple so it is iterable at runtime,
# with the Literal derived from it — the tuple-plus-Literal idiom Section 21.0
# requires, because a `Literal` a test cannot enumerate is a `Literal` whose
# dead members cannot be detected (D-045a).
CONVERGENCE_CLASSES: tuple[str, ...] = ("HIGH", "MEDIUM", "LOW", "CONFLICTED")

ConvergenceClass = Literal["HIGH", "MEDIUM", "LOW", "CONFLICTED"]

# A direction reading. 0 is a legitimate value — a m/m change of exactly zero is
# a flat reading, not missing data — and it is NOT pooled with the up/down
# counts. Pooling it would let a measure that said "nothing happened" count as
# corroboration for whichever side happened to be larger.
Direction = Literal[-1, 0, 1]


class InflationConvergenceVerdict(BaseModel):
    """The published ``value`` of the classifier.

    Every field exists so the *classification* can be audited rather than
    trusted, which is the same reason ``EvidenceTally`` publishes its
    membership: a bare label tells a reader nothing about how it was reached.

    * ``classification`` — the verdict, from ``CONVERGENCE_CLASSES``.
    * ``agreeing`` / ``opposing`` / ``flat`` — the split, so the arithmetic is
      visible. ``flat`` is reported separately because a flat reading is
      *absence of evidence*, not evidence for the majority side.
    * ``measures_used`` — **the denominator that matters for reading the rest.**
      Three is the specification's Phase 1 configuration; six is what this build
      can run. A ``frac_agreeing`` of 0.67 means something different at each.
    * ``frac_agreeing`` — the majority share, i.e. what the thresholds test.
    * ``attainable_fracs`` — the fractions reachable at ``measures_used``. The
      degeneracy disclosure (correction 3): when the configured thresholds fall
      on the same attainable value, the band they open has no width.
    * ``independent_families`` — Section 15.19-D's count, **not** the signal
      count. Two genuinely independent families agreeing is worth more than five
      that share one release.
    * ``family_names`` — which families, because "2" is not auditable.
    * ``bands_available`` — the bands the independent-family count actually
      permits. A reading can satisfy the agreement fraction and still not earn
      its band; this is where that shows up instead of being silently ignored.
    * ``base_rates`` — measured frequencies of each class over 522 real months,
      carried so a reader can tell a finding from the base state (D-029).
    """

    model_config = ConfigDict(extra="forbid")

    classification: ConvergenceClass
    agreeing: int = Field(ge=0)
    opposing: int = Field(ge=0)
    flat: int = Field(ge=0)
    measures_used: int = Field(ge=1)
    frac_agreeing: float = Field(ge=0.0, le=1.0)
    attainable_fracs: list[float]
    independent_families: int = Field(ge=0)
    family_names: list[str]
    bands_available: list[str]
    base_rates: dict[str, float]


class InflationConvergenceInputs(BaseModel):
    """Section 15.19-C's measure readings, as **directions**.

    **Unit contract, and it is not uniform — read this before adding a field.**
    The three ``*_cpi`` / ``*_pce`` fields are the **sign of a month-over-month
    percent change**. ``trimmed_mean_pce_direction`` corresponds in reality to
    FRED ``PCETRIM1M158SFRBDAL``, which is published as a **percent change at an
    annual rate** — for the same month its magnitude is roughly twelve times
    larger than the others'. Only the sign is consumed today, so this is
    currently harmless; it is stated because the next person to use these
    numbers as magnitudes will otherwise introduce a factor-of-twelve error
    across one of six symmetric-looking inputs.

    ``supercore_direction`` is **absent by design**, not by omission. Section
    21.1 blocks it and O-8 establishes why: there is no valid BLS construction,
    and "CPI less shelter" is a *different measure* that was once mislabelled as
    supercore. The Atlanta Fed's sticky-price index occupies the slot under its
    **own** name (``sticky_price_cpi_direction``) rather than being substituted
    silently, because Section 21.1 rule 4 forbids exactly that substitution.

    ``flat`` readings (direction ``0``) are accepted and counted separately from
    both sides. A m/m change of exactly zero is a real observation, not missing
    data, and it is not corroboration for either direction.
    """

    model_config = ConfigDict(extra="forbid")

    # --- the specification's Phase 1 three ---
    headline_cpi_direction: Direction = Field(
        description="Sign of headline CPI m/m percent (BLS survey).",
    )
    core_cpi_direction: Direction = Field(
        description="Sign of core CPI m/m percent (BLS survey).",
    )
    core_pce_direction: Direction = Field(
        description="Sign of core PCE m/m percent (BEA release).",
    )

    # --- the three Section 21.1 called unreachable; two are live (D-047) ---
    median_cpi_direction: Direction | None = Field(
        default=None,
        description=(
            "Sign of Cleveland Fed median CPI m/m percent "
            "(FRED MEDCPIM157SFRBCLE — BLS-survey-derived)."
        ),
    )
    trimmed_mean_direction: Direction | None = Field(
        default=None,
        description=(
            "Sign of Dallas Fed trimmed-mean PCE (FRED PCETRIM1M158SFRBDAL — a "
            "separate production process from the CPI survey). ANNUAL-RATE "
            "units: sign only."
        ),
    )
    sticky_price_cpi_direction: Direction | None = Field(
        default=None,
        description=(
            "Sign of Atlanta Fed sticky-price core CPI m/m percent "
            "(FRED CORESTICKM157SFRBATL). Occupies the role of a "
            "slow-moving core measure — NOT supercore, which is BLOCKED."
        ),
    )

    @property
    def all_directions(self) -> list[int]:
        """Every supplied measure's direction, in a fixed, documented order."""
        return [
            self.headline_cpi_direction,
            self.core_cpi_direction,
            self.core_pce_direction,
            *[
                d
                for d in (
                    self.median_cpi_direction,
                    self.trimmed_mean_direction,
                    self.sticky_price_cpi_direction,
                )
                if d is not None
            ],
        ]


# Which family each input belongs to. This mapping is the *evidence* half of the
# classifier: getting it wrong is how a fabricated convergence is produced, so
# it is declared once, next to the inputs, rather than inferred.
#
# Note `median_cpi_direction` is tagged BLS_CPI even though the Cleveland Fed
# computes it: the production process it depends on is the BLS CPI survey, and
# a CPI redesign corrupts it exactly as it corrupts headline and core. A
# publisher's name is not an independence boundary; a production process is.
_INPUT_FAMILIES: tuple[tuple[str, _Family], ...] = (
    ("headline_cpi_direction", _Family.BLS_CPI),
    ("core_cpi_direction", _Family.BLS_CPI),
    ("median_cpi_direction", _Family.BLS_CPI),
    ("sticky_price_cpi_direction", _Family.BLS_CPI),
    ("core_pce_direction", _Family.BEA_PCE),
    ("trimmed_mean_direction", _Family.DALLAS_FED),
)


def _attainable_fracs(n: int) -> list[float]:
    """The agreement fractions actually reachable with ``n`` measures.

    The set is the multiples of ``1/n``, and *that* is the whole point: a
    threshold pair is only a band structure if distinct attainable fractions
    fall on either side of each threshold. At n=3 they do not.
    """
    if n <= 0:  # pragma: no cover - guarded by Field(ge=1) on measures_used
        return []
    return sorted({round(k / n, 6) for k in range(n + 1)})


def _tagged_measures(
    inputs: InflationConvergenceInputs, as_of_directions: list[int]
) -> tuple[list[ModelResult], int]:
    """Build one ``ModelResult`` per supplied measure, tagged by family.

    Each measure becomes its own result so ``count_independent_families`` can do
    its job: the count it returns is over *these* objects, and the tagging is
    what stops four CPI-derived readings from counting as four votes.

    Returns the results and the count of measures they represent.
    """
    supplied = set(inputs.model_dump(exclude_none=True))
    results: list[ModelResult] = []
    for field_name, family in _INPUT_FAMILIES:
        if field_name not in supplied:
            continue
        direction = getattr(inputs, field_name)
        if direction is None:  # pragma: no cover - excluded by `supplied`
            continue
        if direction > 0:
            reading = "up"
        elif direction < 0:
            reading = "down"
        else:
            reading = "flat"
        result = ModelResult(
            model_name=f"inflation_measure::{field_name}",
            country="us",
            as_of=utc_now(),
            value=int(direction),
            # The per-measure confidence is not meaningful on its own — these
            # are readings, not models. compute_confidence() is used rather than
            # a literal so Section 22.8 holds; `is_heuristic_not_calibrated` is
            # False because reading a sign off a published series is not a
            # heuristic, and the confidence is never surfaced to a caller.
            confidence=compute_confidence(ConfidenceInputs()),
            interpretation=f"{field_name} reads {reading}",
            context="A single sub-measure reading, tagged for Module 13's family census.",
            inputs_used=[field_name],
        )
        results.append(tag_evidence_source(result, family))
    assert len(results) == len(as_of_directions), (
        f"tagged {len(results)} measures but {len(as_of_directions)} directions were "
        "supplied — the family map and _all_directions have diverged"
    )
    return results, len(results)


def _classify(
    *,
    agreeing: int,
    opposing: int,
    headline: int,
    core: int,
    total: int,
    deep_conflict_share: float,
) -> ConvergenceClass:
    """Apply the corrected Section 15.19-C decision rule.

    Two gates produce ``CONFLICTED``, and the second is the correction:

    1. **The specification's pair gate** — headline and core directly oppose.
       Retained, because a headline/core split is the single most informative
       conflict signal available: those two are the measures a reader is most
       likely to be looking at.
    2. **The whole-set gate (correction 1)** — the losing side carries at least
       ``deep_conflict_share`` of the measures. This catches the case the pair
       gate misses: headline and core agree while several others oppose. It is
       checked *after* the pair gate only in the sense that both are OR'd; the
       order in the code carries no priority because either is sufficient.

    The bands then test the agreeing fraction. Note that ``agreeing`` counts one
    side, so ``frac_agreeing`` here is the majority share, matching the
    specification's own arithmetic.
    """
    losing = min(agreeing, opposing)
    if headline * core < 0:
        return "CONFLICTED"
    # The conflict test is written with `losing` on the left, which is what makes
    # the all-flat case safe *without* a special case: `losing` is 0 when nothing
    # moves, and `0 >= share * total` is False for every `total > 0` because
    # `share` is positive. A month in which nothing moved is therefore LOW, i.e.
    # absence of evidence, not conflict.
    #
    # `total > 0` is retained only against a zero denominator; it cannot occur
    # through the public API (three fields are required) but the helper is
    # callable in isolation and `_classify` should not divide by zero.
    #
    # Nothing here depends on `agreeing + opposing > 0`. An earlier revision of
    # this condition carried that term as a "degenerate guard" and the comment
    # claimed it was load-bearing; a mutation sweep proved it inert
    # (scripts/mutation_inflation_convergence.py, D2), which is exactly the
    # defect the sweep exists to find — a redundant condition defended by a
    # comment that asserts it matters.
    if total > 0 and losing >= deep_conflict_share * total:
        return "CONFLICTED"

    frac = agreeing / total if total else 0.0
    settings = get_settings().inflation.convergence
    if frac >= settings.high:
        return "HIGH"
    if frac >= settings.medium:
        return "MEDIUM"
    return "LOW"


def _bands_available(independent_families: int) -> list[str]:
    """Which bands the independent-family count permits, strongest first.

    Section 15.19-D's requirement, made explicit in the output rather than
    applied silently: the count of independent families is a **ceiling on the
    claim**, and a caller that sees ``classification='HIGH'`` alongside
    ``bands_available=['LOW']`` has been told that the agreement fraction
    satisfied HIGH while the evidence base did not support it.
    """
    settings = get_settings().inflation.convergence
    return [
        band
        for band in ("HIGH", "MEDIUM", "LOW")
        if independent_families >= settings.min_families(band.lower())
    ]


def inflation_convergence_classifier(
    inputs: InflationConvergenceInputs,
) -> ModelResult:
    """Grade how strongly the inflation sub-measures converge. Module 5.3.

    ``value`` is an :class:`InflationConvergenceVerdict` as a dict — never a
    bare label, because the label is uninterpretable without the measure count,
    the split, and the independent-family count that went into it (Section
    22.9, and D-046's "a count without its denominator" rule).

    **This is the first caller of ``count_independent_families``.** Section
    15.19-D obliges every convergence classifier in this system to weight
    confidence by the number of genuinely independent source families rather
    than by the number of agreeing signals, and states the test: *five agreeing
    BLS-CPI-derived sub-measures should never produce higher confidence than two
    genuinely independent sources agreeing.* That comparison is pinned by
    ``test_five_redundant_measures_do_not_outscore_two_independent_ones``.

    Three honest limitations travel in the output:

    * **The sign test is weak, and here it is close to degenerate.** Over 522
      real months the specification's three-measure form returns HIGH 86.6% of
      the time, because price levels rise in 88-98% of months. The measured base
      rates are published in ``value`` and warned about, so the number cannot be
      read as an economic finding.
    * **Three measures is the specification's Phase 1 configuration and this
      build can supply six.** The count is published because it changes what
      ``frac_agreeing`` means.
    * **The classification is heuristic.** Its thresholds are the
      specification's illustrative literals, and it takes the heuristic penalty
      in ``compute_confidence``.
    """
    settings = get_settings().inflation.convergence

    directions = inputs.all_directions
    total = len(directions)
    agreeing_side = sum(1 for d in directions if d > 0)
    opposing_side = sum(1 for d in directions if d < 0)
    flat = sum(1 for d in directions if d == 0)
    majority = max(agreeing_side, opposing_side)
    frac = majority / total if total else 0.0

    # Section 15.19-D: the count of INDEPENDENT FAMILIES, computed by the
    # Module 13 machinery over per-measure results that carry a typed tag.
    tagged, _ = _tagged_measures(inputs, directions)
    census = count_independent_families(tagged)
    census_value = census.value
    assert isinstance(census_value, dict)
    independent_families = int(census_value["distinct_families"])
    family_names = [str(name) for name in census_value["families"]]

    classification = _classify(
        agreeing=majority,
        opposing=min(agreeing_side, opposing_side),
        headline=inputs.headline_cpi_direction,
        core=inputs.core_cpi_direction,
        total=total,
        deep_conflict_share=settings.deep_conflict_share,
    )

    bands = _bands_available(independent_families)
    attainable = _attainable_fracs(total)

    base_rates = {
        "three_measure_high": settings.measured_base_rates.three_measure_high,
        "six_measure_high": settings.measured_base_rates.six_measure_high,
        "current_measure_count_high": (
            settings.measured_base_rates.three_measure_high
            if total <= 3
            else settings.measured_base_rates.six_measure_high
        ),
    }

    warnings: list[str] = []

    # --- degeneracy of the threshold pair (correction 3) -------------------
    if total < 5:
        warnings.append(
            f"THRESHOLDS ARE DEGENERATE AT n={total}. The attainable agreement "
            f"fractions are {attainable}, so the configured thresholds "
            f"({settings.medium}, {settings.high}) fall on the same attainable "
            "value and the MEDIUM band has no width — 'MEDIUM' means exactly "
            f"{round(2 / total, 6)} and nothing else. The band structure becomes "
            "a band at n>=5. Reported rather than retuned: the thresholds are "
            "Section 15.19-C's own literals."
        )

    # --- the base-state disclosure (correction 2) --------------------------
    current_rate = base_rates["current_measure_count_high"]
    if classification == "HIGH" and current_rate > 0.75:
        warnings.append(
            f"HIGH IS THE BASE STATE, NOT A FINDING. A {total}-measure sign test "
            f"returned HIGH in {current_rate:.1%} of 522 real months "
            "(1983-01..2026-07), because the price level rises in 88-98% of "
            "months. This reading carries little information on its own; it is "
            "the disinflation months that are informative. See D-047 / O-23."
        )

    # --- Section 15.19-D's ceiling (the integration requirement) -----------
    if classification in bands:
        pass
    elif bands:
        warnings.append(
            f"BAND CEILED BY INDEPENDENT EVIDENCE. The agreement fraction "
            f"satisfied {classification}, but only {independent_families} "
            f"independent source family/families are present "
            f"({', '.join(family_names) or 'none'}), which supports no better "
            f"than {bands[0]}. Five measures from one release are one "
            "observation, not five (Section 15.19-D)."
        )
    else:
        warnings.append(
            "NO BAND SUPPORTED. Not even one independent source family is "
            "present, so no convergence claim is available however the "
            "directions read."
        )

    # --- a single family cannot corroborate itself ------------------------
    if independent_families == 1 and total > 1:
        warnings.append(
            f"ALL {total} MEASURES COME FROM ONE SOURCE FAMILY "
            f"({family_names[0] if family_names else 'unknown'}). Their "
            "agreement is one observation reported several times and must not be "
            "read as convergence."
        )

    if flat:
        warnings.append(
            f"{flat} measure(s) read exactly flat and are EXCLUDED from both "
            "sides. A zero change is absence of evidence, not corroboration for "
            "the larger side."
        )

    # --- the corrected conflict gate in action (correction 1) -------------
    pair_conflict = inputs.headline_cpi_direction * inputs.core_cpi_direction < 0
    if classification == "CONFLICTED" and not pair_conflict:
        warnings.append(
            "CONFLICTED on the WHOLE-SET gate, not the headline/core pair. "
            "Section 15.19-C tests only `headline * core < 0`, which reports "
            "convergence in months where those two agree while the remaining "
            "measures split. The corrected gate fires when the losing side "
            "carries at least "
            f"{settings.deep_conflict_share:.0%} of the measures (D-047)."
        )

    # --- the always-on method caveat --------------------------------------
    warnings.append(
        "Sign test over month-over-month changes. It is a weak statistic: two "
        "measures at +0.001% and one at +5.0% read as agreement. This is a "
        "breadth indicator, not a magnitude estimate."
    )

    return ModelResult(
        model_name="inflation_convergence_classifier",
        country="us",
        as_of=utc_now(),
        value=InflationConvergenceVerdict(
            classification=classification,
            agreeing=majority,
            opposing=min(agreeing_side, opposing_side),
            flat=flat,
            measures_used=total,
            frac_agreeing=round(frac, 6),
            attainable_fracs=attainable,
            independent_families=independent_families,
            family_names=family_names,
            bands_available=bands,
            base_rates=base_rates,
        ).model_dump(),
        confidence=compute_confidence(
            ConfidenceInputs(
                is_heuristic_not_calibrated=True,
                # Section 15.19-D's integration requirement: the FAMILY count,
                # not len(directions). compute_confidence already credits this,
                # and suppressing it would be the D-027 circularity error in
                # reverse — the classifier would refuse to recognise evidence
                # its own caller had just measured.
                source_independence_count=independent_families,
            )
        ),
        interpretation=(
            f"Inflation sub-measure convergence: {classification} "
            f"({majority}/{total} measures agree; "
            f"{independent_families} independent source family/families)"
        ),
        context=(
            f"Module 5.3 (Section 15.19-C). {total} measure(s) supplied of the "
            f"six this build can reach. Independent families: "
            f"{', '.join(family_names) or 'none'}."
        ),
        inputs_used=[name for name, _ in _INPUT_FAMILIES if getattr(inputs, name) is not None],
        warnings=warnings,
    )


# The vocabulary's two halves are asserted here so the module cannot be imported
# with a `Literal` that has drifted from the tuple (D-045a). A member declared
# and unreachable is the defect this pair of lines exists to prevent.
assert set(get_args(ConvergenceClass)) == set(CONVERGENCE_CLASSES)
