"""Mutation sweep for ``four_pillar_scorecard`` (Module 12.2, D-050).

This function's output space is *enumerable* — four pillars over ``{-1, 0, +1}``
crossed with a family count — so, as in D-049's sweep, the mutations are derived
from that space rather than aimed by hand wherever a generator is possible. Two
properties of the earlier sweeps carry over because they are what the repository
learned the hard way:

* **The generators cannot miss their target**, because they rewrite a whole
  expression whose text is derivable from the shipped arithmetic.
* **Every hand-written target is gated by** ``check_targets`` (D-048), which
  refuses to run on an ABSENT, AMBIGUOUS or INERT-BY-CONSTRUCTION ``old``
  string. A sweep that reports a number while pointing at the wrong function is
  worse than no sweep: it changes the file, so it looks applied, and the
  surviving-test conclusion is then drawn about code nobody mutated.

Mutations, grouped by what they attack — the group is what tells you which test
is missing when one survives (D-031). The grouping here tracks the module
docstring's **four specification defects**, so a survivor points at a defect
whose repair is not yet pinned:

* **M1** the ``CONFLICTED`` opposition gate — Defect 1's repair. This is the
  group that matters most: every mutation in it can turn a mandatory blocking
  verdict into a green light.
* **M2** the dissent-count gates and the family floors — Defect 2's repair, plus
  Section 15.19-D's floors. Includes the *ordering* of the two bands, because
  swapping them promotes every MEDIUM read to HIGH.
* **M3** the §15.19-D census wiring — Defect 3's repair. The census **call**
  removed, its result ignored, or its count replaced by the raw pillar count.
* **M4** the published ``value`` — each of the eight keys renamed, inverted or
  given the wrong quantity. Several keys decide the verdict, so a rename is not
  merely cosmetic.
* **M5** the disclosures — each warning branch deleted.
* **M6** the contract — ``extra="forbid"``, the ``-1/0/1`` literal, the source
  minimum length, the all-neutral validator, and the model identity.
* **M7** the confidence — ``compute_confidence()`` replaced by a hardcoded
  value, or its family term dropped (Section 22.8).
* **C1** the config accessors and the dissent-ceiling validator, which together
  stop a threshold from being decorative.

**Run this in the FOREGROUND.** The sweep rewrites ``scorecard.py`` and
``config.py`` in place, so any concurrent test run, live check or probe reads a
mutated module. D-047's Postscript 2 records a contaminated reading produced
exactly that way, and D-049 left the source mutated when its sweep was killed
mid-run — the full suite then passed *with the mutation in place*. The blast
radius is the whole repository.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _sweep_gate import sweep_lifecycle

SRC = Path("src/macro_engine/models/scorecard.py")
CONFIG = Path("src/macro_engine/config.py")

#: Every file this sweep may mutate. Declared once, at module level, so
#: `main` hands the SAME set to the sidecar lifecycle that the loop restores
#: -- a set written twice is a set that can disagree (O-103).
SWEEP_PATHS = {SRC, CONFIG}

# --- The shipped text each hand-written mutation targets --------------------
#
# Transcribed from the source. `check_targets` verifies every one is present
# EXACTLY ONCE before the sweep runs.

_MODEL_HEADER = '        model_name="four_pillar_scorecard",\n        country="us",'

# --- Defect 1: the opposition gate -----------------------------------------

_OPPOSED = "    opposed = up > 0 and down > 0"
_OPPOSED_USES = "    elif opposed:"

_CONFLICTED_REASON = (
    "        reason = (\n"
    "            f\"the pillars oppose each other — {', '.join(up_names)} read \"\n"
    "            f\"tightening while {', '.join(down_names)} read easing. Agreement is \"\n"
    '            f"{agree_frac:.0%} and the read is a genuine split rather than weak "\n'
    '            f"agreement"\n'
    "        )"
)

_UP_NAMES = (
    "        up_names = [name for name, d in zip(_PILLARS, directions, strict=True) if d > 0]"
)
_DOWN_NAMES = (
    "        down_names = [name for name, d in zip(_PILLARS, directions, strict=True) if d < 0]"
)

# --- Defect 2: the dissent gates -------------------------------------------

_HIGH_GATE = (
    "    elif dissent <= settings.high_dissent_ceiling and (\n"
    "        independent_families >= settings.high_family_floor\n"
    "    ):"
)
_MEDIUM_GATE = (
    "    elif dissent <= settings.medium_dissent_ceiling and (\n"
    "        independent_families >= settings.medium_family_floor\n"
    "    ):"
)

_DISSENT = "    dissent = n - max(up, down) if n else 0"

# --- Defect 3: the Section 15.19-D census ----------------------------------

_CENSUS_CALL = "    independent_families, family_names = _pillar_census(inputs)"
_CENSUS_DISTINCT = '    distinct = value.get("distinct_families")'
_CENSUS_FAMILIES = "    return distinct, sorted({r.family.value for r in inputs.pillar_reads()})"
_CENSUS_NON_DICT = "    if not isinstance(value, dict):  # pragma: no cover - contract guard"
# Added by D-051's cross-classifier check: this filter did not exist when the
# sweep was first written, and its absence was a real defect (neutral pillars
# contributed families to a directional verdict). The group now mutates it.
_CENSUS_DIRECTIONAL = (
    "    directional = [\n"
    "        (name, read)\n"
    "        for name, read in zip(_PILLARS, inputs.pillar_reads(), strict=True)\n"
    "        if read.direction != 0\n"
    "    ]"
)

# --- The all-neutral guard -------------------------------------------------

_VALIDATOR_NEUTRAL = (
    "    def _at_least_one_pillar_must_be_directional(self) -> ScorecardInputs:\n"
    "        reads = [getattr(self, name) for name in _PILLARS]\n"
    "        if all(r.direction == 0 for r in reads) and not self.allow_all_neutral:"
)
_ALLOW_FIELD = "    allow_all_neutral: bool = Field(\n        default=False,\n        description=("

# --- The published value ---------------------------------------------------

_PUBLISHED = (
    '            "classification": verdict,\n'
    '            "agreement_fraction": round(agree_frac, 4),\n'
    '            "agreement_margin": round(margin, 4),\n'
    '            "dissenting_pillars": dissent,\n'
    '            "non_neutral_pillars": n,\n'
    '            "independent_families": independent_families,\n'
    '            "family_names": family_names,\n'
    '            "pillar_directions": dict(zip(_PILLARS, directions, strict=True)),'
)

_PUBLISHED_DIRECTIONS = (
    '            "pillar_directions": dict(zip(_PILLARS, directions, strict=True)),'
)

_NO_SIGNAL_REASON = (
    "        reason = (\n"
    '            "all four pillars read neutral — no directional signal to converge "\n'
    '            "on. This is distinct from LOW, where signals exist and disagree"\n'
    "        )"
)

_HIGH_REASON = (
    "        reason = (\n"
    '            f"unanimous among {n} directional pillar(s), backed by "\n'
    '            f"{independent_families} independent source families"\n'
    "        )"
)

_LOW_REASON_INDEPENDENCE = "        if independent_families < settings.medium_family_floor:"

# --- The confidence --------------------------------------------------------

_CONFIDENCE_CALL = (
    "    confidence = compute_confidence(\n"
    "        ConfidenceInputs(\n"
    "            data_quality_flags_present=False,\n"
    "            is_heuristic_not_calibrated=True,\n"
    "            depends_on_unobservable=False,\n"
    "            source_independence_count=independent_families,\n"
    "        )\n"
    "    )"
)

# --- The contract ----------------------------------------------------------

_MODEL_CONFIG = '    model_config = ConfigDict(extra="forbid")\n\n    growth: PillarRead'
_DIRECTION_FIELD = "    direction: Literal[-1, 0, 1] = Field("
_SOURCE_FIELD = "    source: str = Field(\n        min_length=1,"

_PILLAR_READ_CONFIG = (
    '    model_config = ConfigDict(extra="forbid")\n\n    direction: Literal[-1, 0, 1] = Field('
)

# --- Warning heads ---------------------------------------------------------

_WARNING_HEADS: dict[str, str] = {
    "w1_illustrative": (
        "    warnings: list[str] = [\n"
        '        "Thresholds are illustrative starting heuristics, not calibrated "'
    ),
    "w2_conflicted": '    if verdict == "CONFLICTED":',
    "w3_no_signal": '    elif verdict == "NO_SIGNAL":',
    "w4_redundant": "    elif agree_frac >= 0.75 and independent_families < high_family_floor:",
    "w5_partial": '    if 0 < n < 4 and verdict not in {"NO_SIGNAL", "CONFLICTED"}:',
}

_W5_BODY = '    if 0 < n < 4 and verdict not in {"NO_SIGNAL", "CONFLICTED"}:'
_W4_BODY = "    elif agree_frac >= 0.75 and independent_families < high_family_floor:"

# --- config.py targets -----------------------------------------------------

_CFG_PROPERTIES: dict[str, str] = {
    "high_dissent_ceiling": (
        "    @property\n"
        "    def high_dissent_ceiling(self) -> int:\n"
        '        """Dissenters permitted and still `HIGH`. Zero — i.e. unanimity."""\n'
        "        return int(self.max_dissenting_pillars_high.value)"
    ),
    "medium_dissent_ceiling": (
        "    @property\n"
        "    def medium_dissent_ceiling(self) -> int:\n"
        '        """Dissenters permitted and still `MEDIUM`. One."""\n'
        "        return int(self.max_dissenting_pillars_medium.value)"
    ),
    "high_family_floor": (
        "    @property\n"
        "    def high_family_floor(self) -> int:\n"
        '        """Independent families required for `HIGH` (Section 15.19-D\'s example)."""\n'
        "        return int(self.min_independent_families_high.value)"
    ),
    "medium_family_floor": (
        "    @property\n"
        "    def medium_family_floor(self) -> int:\n"
        '        """Independent families required for `MEDIUM`."""\n'
        "        return int(self.min_independent_families_medium.value)"
    ),
    "conflicted_base_share": (
        "    @property\n"
        "    def conflicted_base_share(self) -> float:\n"
        '        """Share of the admissible input space that classifies `CONFLICTED`."""\n'
        "        return float(self.measured_conflicted_share.value)"
    ),
}

#: The two dissent-ceiling accessors, in source order, for the SWAP mutation.
_CFG_DISSENT_ACCESSORS = (
    "    @property\n"
    "    def high_dissent_ceiling(self) -> int:\n"
    '        """Dissenters permitted and still `HIGH`. Zero — i.e. unanimity."""\n'
    "        return int(self.max_dissenting_pillars_high.value)\n"
    "\n"
    "    @property\n"
    "    def medium_dissent_ceiling(self) -> int:\n"
    '        """Dissenters permitted and still `MEDIUM`. One."""\n'
    "        return int(self.max_dissenting_pillars_medium.value)"
)

#: The two family-floor accessors, in source order.
_CFG_FAMILY_ACCESSORS = (
    "    @property\n"
    "    def high_family_floor(self) -> int:\n"
    '        """Independent families required for `HIGH` (Section 15.19-D\'s example)."""\n'
    "        return int(self.min_independent_families_high.value)\n"
    "\n"
    "    @property\n"
    "    def medium_family_floor(self) -> int:\n"
    '        """Independent families required for `MEDIUM`."""\n'
    "        return int(self.min_independent_families_medium.value)"
)

# These three targets are anchored on the preceding ``max_dissenting_pillars_*``
# reads because ``ConvergenceSettings`` (D-051) ships the SAME validator bodies
# for its own ceilings. Without the anchor, ``str.replace`` would rewrite the
# convergence validator instead and the sweep would report a survival about code
# nobody mutated — the failure mode check_targets exists to refuse.
_CFG_VALIDATOR_ORDER = (
    "        _high = int(self.max_dissenting_pillars_high.value)\n"
    "        _medium = int(self.max_dissenting_pillars_medium.value)\n"
    "        if _high > _medium:"
)
_CFG_VALIDATOR_NEGATIVE = (
    "        if _high > _medium:\n"
    "            raise ValueError(\n"
    '                f"scorecard.max_dissenting_pillars_high ({_high}) must not exceed "\n'
    '                f"max_dissenting_pillars_medium ({_medium}): HIGH is the STRICTER "\n'
    '                "verdict, so it cannot tolerate more dissent than MEDIUM. Inverting "\n'
    '                "them would make the MEDIUM band unreachable and silently promote "\n'
    '                "every MEDIUM read to HIGH."\n'
    "            )\n"
    "        if _high < 0:"
)
_CFG_VALIDATOR_DEAD = "        if _medium > 3:"


# ---------------------------------------------------------------------------
# The behavioural matrix the mutations are derived from
# ---------------------------------------------------------------------------
#
# The verdict is a function of (pillar directions, family count), and both parts
# are small:
#
#   * the four directions over {-1, 0, +1} minus the all-neutral corner: 80
#     configurations, of which 50 genuinely oppose;
#   * the family count, which the fixtures pin to 4 / 2 / 1 so that the three
#     verdict bands (above both floors / between them / below both) are reachable.
#
# Every single-term mutation below must be visible in at least one cell of that
# matrix. The families are the identity of the LIVE CHECK's judgement calls, so
# the fixture sets here mirror it.

#: Four genuinely distinct families, one per pillar.
_FOUR_FAMILIES = (
    "BLS_EMPLOYMENT_SITUATION",
    "BLS_CPI",
    "MARKET_BREAKEVEN",
    "TREASURY_OFFICIAL",
)

#: Two distinct families — the ONLY configuration that reaches MEDIUM.
_TWO_FAMILIES = ("BLS_CPI", "BLS_CPI", "MARKET_BREAKEVEN", "MARKET_BREAKEVEN")

#: One repeated family — below both floors, so LOW however unanimous the pillars.
_ONE_FAMILY = ("BLS_CPI",) * 4


# ---------------------------------------------------------------------------
# The mutations
# ---------------------------------------------------------------------------


def _opposition_mutations() -> list[tuple[str, Path, str, str]]:
    """Defect 1's repair: the gate must BE the guard.

    The specification computed the opposition predicate and then required a
    second, narrower condition before honouring it. Every mutation here is a way
    of reintroducing a filter between the guard and the verdict, so every one of
    them turns some opposed read from ``CONFLICTED`` into a non-blocking verdict.
    That is the failure mode with consequences, which is why it has the largest
    group.
    """
    return [
        (
            "MX1a the gate is the specification's narrow form (growth x inflation < 0)",
            SRC,
            _OPPOSED_USES,
            "    elif opposed and directions[0] * directions[1] < 0:",
        ),
        (
            "MX1b the gate requires FULL opposition (all four pillars split 2-2)",
            SRC,
            _OPPOSED_USES,
            "    elif up == 2 and down == 2:",
        ),
        (
            "MX1c the gate requires a majority on both sides (impossible)",
            SRC,
            _OPPOSED_USES,
            "    elif up > n / 2 and down > n / 2:",
        ),
        (
            "MX1d the gate is inverted (only NON-opposed reads are CONFLICTED)",
            SRC,
            _OPPOSED_USES,
            "    elif not opposed:",
        ),
        (
            "MX1e the gate is dropped (opposition falls through to the dissent gates)",
            SRC,
            _OPPOSED_USES,
            "    elif False:",
        ),
        (
            "MX1f the predicate demands BOTH sides twice rather than one each",
            SRC,
            _OPPOSED,
            "    opposed = up >= 2 and down >= 2",
        ),
        (
            "MX1g the predicate is an `or` (a one-sided read counts as opposed)",
            SRC,
            _OPPOSED,
            "    opposed = up > 0 or down > 0",
        ),
        (
            "MX1h the predicate is always False (CONFLICTED becomes unreachable)",
            SRC,
            _OPPOSED,
            "    opposed = False",
        ),
        (
            "MX1i the predicate is always True (every read is CONFLICTED)",
            SRC,
            _OPPOSED,
            "    opposed = True",
        ),
        (
            "MX1j `up` counts the easing side (the two sides are swapped)",
            SRC,
            "    up = sum(1 for d in non_neutral if d > 0)",
            "    up = sum(1 for d in non_neutral if d < 0)",
        ),
        (
            "MX1k `down` counts the tightening side (the two sides are swapped)",
            SRC,
            "    down = sum(1 for d in non_neutral if d < 0)",
            "    down = sum(1 for d in non_neutral if d > 0)",
        ),
        (
            "MX1l the reason names the wrong side first (the disclosure lies)",
            SRC,
            _UP_NAMES,
            "        up_names = [\n"
            "            name for name, d in zip(_PILLARS, directions, strict=True) if d < 0\n"
            "        ]",
        ),
        (
            "MX1m the reason's easing side names the tightening pillars",
            SRC,
            _DOWN_NAMES,
            "        down_names = [\n"
            "            name for name, d in zip(_PILLARS, directions, strict=True) if d > 0\n"
            "        ]",
        ),
        (
            "MX1n the CONFLICTED reason is replaced by a generic string",
            SRC,
            _CONFLICTED_REASON,
            '        reason = "the pillars are conflicted"',
        ),
    ]


def _gate_mutations() -> list[tuple[str, Path, str, str]]:
    """Defect 2's repair: the dissent bands and the family floors.

    Four gates have to be in the right order and read the right leaf. The two
    swap mutations are the dangerous pair — swapping the ceilings promotes every
    MEDIUM read to HIGH, and swapping the floors does the same, and neither
    produces an error or an implausible number.
    """
    return [
        (
            "MX2a the HIGH gate permits the MEDIUM ceiling (MEDIUM becomes unreachable)",
            SRC,
            _HIGH_GATE,
            "    elif dissent <= settings.medium_dissent_ceiling and (\n"
            "        independent_families >= settings.high_family_floor\n"
            "    ):",
        ),
        (
            "MX2b the HIGH gate is made strict (`<`), so unanimity fails its own gate",
            SRC,
            _HIGH_GATE,
            "    elif dissent < settings.high_dissent_ceiling and (\n"
            "        independent_families >= settings.high_family_floor\n"
            "    ):",
        ),
        (
            "MX2c the HIGH gate drops the family floor (one release can read HIGH)",
            SRC,
            _HIGH_GATE,
            "    elif dissent <= settings.high_dissent_ceiling:",
        ),
        (
            "MX2d the HIGH gate's family floor uses the MEDIUM leaf",
            SRC,
            _HIGH_GATE,
            "    elif dissent <= settings.high_dissent_ceiling and (\n"
            "        independent_families >= settings.medium_family_floor\n"
            "    ):",
        ),
        (
            "MX2e the MEDIUM gate's ceiling uses the HIGH leaf (MEDIUM never fires)",
            SRC,
            _MEDIUM_GATE,
            "    elif dissent <= settings.high_dissent_ceiling and (\n"
            "        independent_families >= settings.medium_family_floor\n"
            "    ):",
        ),
        (
            "MX2f the MEDIUM gate permits two dissenters",
            SRC,
            _MEDIUM_GATE,
            "    elif dissent <= settings.medium_dissent_ceiling + 1 and (\n"
            "        independent_families >= settings.medium_family_floor\n"
            "    ):",
        ),
        (
            "MX2g the MEDIUM gate drops the family floor (one release reads MEDIUM)",
            SRC,
            _MEDIUM_GATE,
            "    elif dissent <= settings.medium_dissent_ceiling:",
        ),
        (
            "MX2h the MEDIUM gate's family floor is dropped to zero",
            SRC,
            _MEDIUM_GATE,
            "    elif dissent <= settings.medium_dissent_ceiling and (\n"
            "        independent_families >= 0\n"
            "    ):",
        ),
        (
            "MX2i the agreement fraction is read from the raw pillar count",
            SRC,
            "    agree_frac = max(up, down) / n if n else 0.0",
            "    agree_frac = max(up, down) / 4 if n else 0.0",
        ),
        (
            "MX2j the margin equals the agreement fraction (no second measure)",
            SRC,
            "    margin = abs(up - down) / n if n else 0.0",
            "    margin = max(up, down) / n if n else 0.0",
        ),
        (
            "MX2k the margin is never published (always zero)",
            SRC,
            "    margin = abs(up - down) / n if n else 0.0",
            "    margin = 0.0",
        ),
        (
            "MX2l the dissent count counts the agreeing side instead",
            SRC,
            _DISSENT,
            "    dissent = max(up, down) if n else 0",
        ),
        (
            "MX2m the dissent count is always zero (unanimity everywhere)",
            SRC,
            _DISSENT,
            "    dissent = 0",
        ),
        (
            "MX2n the neutral pillars are dropped from the non-neutral list",
            SRC,
            "    non_neutral = [d for d in directions if d != 0]",
            "    non_neutral = [d for d in directions if d > 0]",
        ),
        (
            "MX2o the LOW verdict's independence reason is never reached",
            SRC,
            _LOW_REASON_INDEPENDENCE,
            "        if False:",
        ),
    ]


def _census_mutations() -> list[tuple[str, Path, str, str]]:
    """Defect 3's repair: Section 15.19-D's wiring.

    Three ways of severing it, in increasing subtlety: stop calling the supplier,
    call it and ignore the count, or read a key that does not exist. The middle
    one is the interesting case — it leaves ``count_independent_families`` in the
    source so a grep for the call site still finds it, while the count the
    verdict actually uses comes from somewhere else. That is the "declared,
    consumed, unreachable" class this project keeps finding.

    ``_CENSUS_NON_DICT`` gets a mutation of its own because it is the contract
    guard between the two modules: if the supplier ever changes its return type,
    this is the line that must fail loudly rather than silently mis-reading.
    """
    return [
        (
            "MX3a the census call is removed; the raw pillar count is used instead",
            SRC,
            _CENSUS_CALL,
            "    independent_families, family_names = n, sorted("
            "{r.family.value for r in inputs.pillar_reads()})",
        ),
        (
            "MX3b the census call is removed; the count is hardcoded to four",
            SRC,
            _CENSUS_CALL,
            "    independent_families, family_names = 4, sorted("
            "{r.family.value for r in inputs.pillar_reads()})",
        ),
        (
            "MX3c the census is called but its count is discarded (four always)",
            SRC,
            _CENSUS_CALL,
            "    _, family_names = _pillar_census(inputs)\n    independent_families = 4",
        ),
        (
            "MX3d the census reads a key the supplier does not publish",
            SRC,
            _CENSUS_DISTINCT,
            '    distinct = value.get("families")',
        ),
        (
            "MX3e the measured count is decremented by one",
            SRC,
            _CENSUS_DISTINCT,
            '    distinct = value.get("distinct_families")\n    distinct = distinct - 1 '
            "if isinstance(distinct, int) else distinct",
        ),
        (
            "MX3f the published family names come from the census rather than the reads",
            SRC,
            _CENSUS_FAMILIES,
            "    return distinct, sorted({r.family.value for r in inputs.pillar_reads()})[:1]",
        ),
        (
            "MX3g the non-dict contract guard is removed (a changed supplier is silent)",
            SRC,
            _CENSUS_NON_DICT,
            "    if False:  # pragma: no cover - contract guard",
        ),
        (
            "MX3h the census counts ALL pillars, including the neutral ones",
            SRC,
            _CENSUS_DIRECTIONAL,
            "    directional = list(zip(_PILLARS, inputs.pillar_reads(), strict=True))",
        ),
        (
            "MX3i the census counts only the FIRST pillar",
            SRC,
            _CENSUS_DIRECTIONAL,
            "    directional = list(zip(_PILLARS, inputs.pillar_reads(), strict=True))[:1]",
        ),
        (
            "MX3j the census EXCLUDES the directional pillars (inverted predicate)",
            SRC,
            _CENSUS_DIRECTIONAL,
            "    directional = [\n"
            "        (name, read)\n"
            "        for name, read in zip(_PILLARS, inputs.pillar_reads(), strict=True)\n"
            "        if read.direction == 0\n"
            "    ]",
        ),
    ]


def _value_key_mutations() -> list[tuple[str, Path, str, str]]:
    """Each published key, renamed and given the wrong quantity.

    Two survivors in the trilemma sweep (D-047) survived for a single reason: no
    test read the keys they changed. Several keys here decide the verdict — a
    rename of ``independent_families`` breaks the §15.19-D assertions, and a
    ``dissenting_pillars`` that reports the agreeing side is a lie a reader would
    act on.
    """
    return [
        (
            "MX4a `classification` renamed (the verdict cannot be routed)",
            SRC,
            _PUBLISHED,
            _PUBLISHED.replace('"classification": verdict,', '"verdict": verdict,'),
        ),
        (
            "MX4b `agreement_fraction` renamed",
            SRC,
            _PUBLISHED,
            _PUBLISHED.replace('"agreement_fraction"', '"agreement"'),
        ),
        (
            "MX4c `agreement_margin` renamed",
            SRC,
            _PUBLISHED,
            _PUBLISHED.replace('"agreement_margin"', '"margin"'),
        ),
        (
            "MX4d `dissenting_pillars` renamed",
            SRC,
            _PUBLISHED,
            _PUBLISHED.replace('"dissenting_pillars"', '"dissenters"'),
        ),
        (
            "MX4e `non_neutral_pillars` renamed",
            SRC,
            _PUBLISHED,
            _PUBLISHED.replace('"non_neutral_pillars"', '"directional_pillars"'),
        ),
        (
            "MX4f `independent_families` renamed",
            SRC,
            _PUBLISHED,
            _PUBLISHED.replace('"independent_families"', '"source_families"'),
        ),
        (
            "MX4g `family_names` renamed",
            SRC,
            _PUBLISHED,
            _PUBLISHED.replace('"family_names"', '"families"'),
        ),
        (
            "MX4h `pillar_directions` renamed",
            SRC,
            _PUBLISHED,
            _PUBLISHED.replace('"pillar_directions"', '"directions"'),
        ),
        (
            "MX4i the published dissent count reports the agreeing side",
            SRC,
            _PUBLISHED,
            _PUBLISHED.replace(
                '"dissenting_pillars": dissent,', '"dissenting_pillars": max(up, down),'
            ),
        ),
        (
            "MX4j the published non-neutral count is the pillar total",
            SRC,
            _PUBLISHED,
            _PUBLISHED.replace('"non_neutral_pillars": n,', '"non_neutral_pillars": 4,'),
        ),
        (
            "MX4k the published family count is the raw pillar count",
            SRC,
            _PUBLISHED,
            _PUBLISHED.replace(
                '"independent_families": independent_families,',
                '"independent_families": n,',
            ),
        ),
        (
            "MX4l the published directions are the easing side only",
            SRC,
            _PUBLISHED_DIRECTIONS,
            '            "pillar_directions": dict(zip(_PILLARS, non_neutral, strict=False)),',
        ),
        (
            "MX4m the published agreement fraction is the margin",
            SRC,
            _PUBLISHED,
            _PUBLISHED.replace(
                '"agreement_fraction": round(agree_frac, 4),',
                '"agreement_fraction": round(margin, 4),',
            ),
        ),
        (
            "MX4n the published family names are dropped",
            SRC,
            _PUBLISHED,
            _PUBLISHED.replace('            "family_names": family_names,\n', ""),
        ),
        (
            "MX4o the published directions are dropped",
            SRC,
            _PUBLISHED,
            _PUBLISHED.replace(_PUBLISHED_DIRECTIONS, ""),
        ),
        (
            "MX4p the NO_SIGNAL reason conflates NO_SIGNAL with LOW",
            SRC,
            _NO_SIGNAL_REASON,
            '        reason = "all four pillars read neutral"',
        ),
        (
            "MX4q the HIGH reason drops the family count (the §15.19-D claim)",
            SRC,
            _HIGH_REASON,
            '        reason = f"unanimous among {n} directional pillar(s)"',
        ),
    ]


def _warning_mutations() -> list[tuple[str, Path, str, str]]:
    """Each disclosure removed, one at a time.

    Deleting a branch is the strongest form of "this warning contributes
    nothing": if the suite still passes, the warning was not being read, and the
    function has quietly stopped disclosing something the specification requires
    it to disclose. The CONFLICTED warning is the one that matters — it carries
    the "MUST block trade construction" instruction.
    """
    out: list[tuple[str, Path, str, str]] = []
    for label, head in _WARNING_HEADS.items():
        if label == "w1_illustrative":
            out.append(
                (
                    "MX5a the illustrative-threshold warning removed",
                    SRC,
                    head + "\n" + '        "against realised convergence outcomes — Phase 5+ '
                    'calibration required.",\n' + "    ]",
                    "    warnings: list[str] = []",
                )
            )
        elif label == "w4_redundant":
            out.append(
                (
                    "MX5d the redundant-evidence warning removed (§15.19-D's catch)",
                    SRC,
                    _W4_BODY,
                    "    elif False and independent_families < high_family_floor:",
                )
            )
        elif label == "w5_partial":
            out.append(
                (
                    "MX5e the partial-pillars warning removed",
                    SRC,
                    _W5_BODY,
                    '    if 0 < n < 4 and verdict not in {"NO_SIGNAL", "CONFLICTED"} and False:',
                )
            )
        elif label == "w2_conflicted":
            out.append(
                (
                    "MX5b the CONFLICTED blocking warning removed",
                    SRC,
                    head,
                    '    if verdict == "CONFLICTED" and False:',
                )
            )
            out.append(
                (
                    "MX5f the base-state share is dropped from the CONFLICTED warning",
                    SRC,
                    '            f"of a four-pillar read: {conflicted_base_share:.1%} of the "\n'
                    '            "admissible input space classifies this way, so the verdict alone "\n'  # must match the source byte for byte
                    '            "does not identify this read as unusual."',
                    '            "of a four-pillar read."',
                )
            )
            out.append(
                (
                    "MX5g the MUST-block sentence is removed from the warning",
                    SRC,
                    '            "CONFLICTED — the pillars point opposite ways. This MUST block trade "\n'  # must match the source byte for byte
                    '            "construction (Module 12.2). Note that CONFLICTED is the BASE STATE "',  # must match the source byte for byte
                    '            "CONFLICTED — the pillars point opposite ways. "',
                )
            )
        elif label == "w3_no_signal":
            out.append(
                (
                    "MX5c the NO_SIGNAL disclosure removed (it reads as LOW)",
                    SRC,
                    head,
                    '    elif verdict == "NO_SIGNAL" and False:',
                )
            )
    return out


def _contract_mutations() -> list[tuple[str, Path, str, str]]:
    """The input contract and the model identity."""
    return [
        (
            "MX6a `extra='forbid'` removed (typo'd pillar names are silently dropped)",
            SRC,
            _MODEL_CONFIG,
            '    model_config = ConfigDict(extra="ignore")\n\n    growth: PillarRead',
        ),
        (
            "MX6b the direction is a plain int (a magnitude becomes a category error)",
            SRC,
            _PILLAR_READ_CONFIG,
            '    model_config = ConfigDict(extra="forbid")\n\n    direction: int = Field(',
        ),
        (
            "MX6c the source minimum length is dropped (an untraceable read passes)",
            SRC,
            _SOURCE_FIELD,
            "    source: str = Field(\n        min_length=0,",
        ),
        (
            "MX6d the all-neutral validator removed (NO_SIGNAL by empty default)",
            SRC,
            _VALIDATOR_NEUTRAL,
            "    def _at_least_one_pillar_must_be_directional(self) -> ScorecardInputs:\n"
            "        reads = [getattr(self, name) for name in _PILLARS]\n"
            "        if False:",
        ),
        (
            "MX6e the all-neutral validator ignores the opt-in flag",
            SRC,
            _VALIDATOR_NEUTRAL,
            "    def _at_least_one_pillar_must_be_directional(self) -> ScorecardInputs:\n"
            "        reads = [getattr(self, name) for name in _PILLARS]\n"
            "        if all(r.direction == 0 for r in reads):",
        ),
        (
            "MX6f the opt-in defaults to True (the guard is decorative)",
            SRC,
            _ALLOW_FIELD,
            "    allow_all_neutral: bool = Field(\n        default=True,\n        description=(",
        ),
        (
            "MX6g the result is labelled with the caller's country",
            SRC,
            _MODEL_HEADER,
            '        model_name="four_pillar_scorecard",\n        country="gb",',
        ),
        (
            "MX6h the model name is wrong (a caller cannot route the result)",
            SRC,
            _MODEL_HEADER,
            '        model_name="pillar_scorecard",\n        country="us",',
        ),
    ]


def _confidence_mutations() -> list[tuple[str, Path, str, str]]:
    """Section 22.8: ``compute_confidence()`` is the only confidence producer.

    The specification hardcodes four confidences (``0.2 / 0.75 / 0.5 / 0.3``)
    that move with the verdict. Two mutations test that the formula is used, and
    two test that its *family term* is — the second is the §15.19-D property, and
    a version that called ``compute_confidence()`` with the count held at zero
    would satisfy the first pair while failing the second.
    """
    return [
        (
            "MX7a the HIGH confidence is hardcoded to the specification's 0.75",
            SRC,
            _CONFIDENCE_CALL,
            '    confidence = 0.75 if verdict == "HIGH" else 0.4',
        ),
        (
            "MX7b the confidence ignores the family count (scale collapses to one)",
            SRC,
            _CONFIDENCE_CALL,
            "    confidence = compute_confidence(\n"
            "        ConfidenceInputs(\n"
            "            data_quality_flags_present=False,\n"
            "            is_heuristic_not_calibrated=True,\n"
            "            depends_on_unobservable=False,\n"
            "            source_independence_count=1,\n"
            "        )\n"
            "    )",
        ),
        (
            "MX7c the confidence uses the raw pillar count as its family term",
            SRC,
            _CONFIDENCE_CALL,
            "    confidence = compute_confidence(\n"
            "        ConfidenceInputs(\n"
            "            data_quality_flags_present=False,\n"
            "            is_heuristic_not_calibrated=True,\n"
            "            depends_on_unobservable=False,\n"
            "            source_independence_count=4,\n"
            "        )\n"
            "    )",
        ),
        (
            "MX7d the heuristic flag is cleared (the penalty is not applied)",
            SRC,
            _CONFIDENCE_CALL,
            "    confidence = compute_confidence(\n"
            "        ConfidenceInputs(\n"
            "            data_quality_flags_present=False,\n"
            "            is_heuristic_not_calibrated=False,\n"
            "            depends_on_unobservable=False,\n"
            "            source_independence_count=independent_families,\n"
            "        )\n"
            "    )",
        ),
        (
            "MX7e a data-quality flag is set (the penalty is applied twice over)",
            SRC,
            _CONFIDENCE_CALL,
            "    confidence = compute_confidence(\n"
            "        ConfidenceInputs(\n"
            "            data_quality_flags_present=True,\n"
            "            is_heuristic_not_calibrated=True,\n"
            "            depends_on_unobservable=False,\n"
            "            source_independence_count=independent_families,\n"
            "        )\n"
            "    )",
        ),
    ]


def _config_mutations() -> list[tuple[str, Path, str, str]]:
    """The accessors and the dissent-ceiling validator, in ``config.py``."""
    return [
        (
            "CX1 the HIGH dissent accessor hardcodes the shipped literal",
            CONFIG,
            _CFG_PROPERTIES["high_dissent_ceiling"],
            "    @property\n"
            "    def high_dissent_ceiling(self) -> int:\n"
            "        # mutation: the shipped literal replaces the accessor\n"
            "        return 0",
        ),
        (
            "CX2 the MEDIUM dissent accessor hardcodes the shipped literal",
            CONFIG,
            _CFG_PROPERTIES["medium_dissent_ceiling"],
            "    @property\n"
            "    def medium_dissent_ceiling(self) -> int:\n"
            "        # mutation: the shipped literal replaces the accessor\n"
            "        return 1",
        ),
        (
            "CX3 the HIGH family floor accessor hardcodes the shipped literal",
            CONFIG,
            _CFG_PROPERTIES["high_family_floor"],
            "    @property\n"
            "    def high_family_floor(self) -> int:\n"
            "        # mutation: the shipped literal replaces the accessor\n"
            "        return 3",
        ),
        (
            "CX4 the MEDIUM family floor accessor hardcodes the shipped literal",
            CONFIG,
            _CFG_PROPERTIES["medium_family_floor"],
            "    @property\n"
            "    def medium_family_floor(self) -> int:\n"
            "        # mutation: the shipped literal replaces the accessor\n"
            "        return 2",
        ),
        (
            "CX5 the dissent-ceiling accessors swap their leaves",
            CONFIG,
            _CFG_DISSENT_ACCESSORS,
            "    @property\n"
            "    def high_dissent_ceiling(self) -> int:\n"
            "        # mutation: reads the MEDIUM leaf\n"
            "        return int(self.max_dissenting_pillars_medium.value)\n"
            "\n"
            "    @property\n"
            "    def medium_dissent_ceiling(self) -> int:\n"
            "        # mutation: reads the HIGH leaf\n"
            "        return int(self.max_dissenting_pillars_high.value)",
        ),
        (
            "CX6 the family-floor accessors swap their leaves",
            CONFIG,
            _CFG_FAMILY_ACCESSORS,
            "    @property\n"
            "    def high_family_floor(self) -> int:\n"
            "        # mutation: reads the MEDIUM leaf\n"
            "        return int(self.min_independent_families_medium.value)\n"
            "\n"
            "    @property\n"
            "    def medium_family_floor(self) -> int:\n"
            "        # mutation: reads the HIGH leaf\n"
            "        return int(self.min_independent_families_high.value)",
        ),
        (
            "CX7 the base-share accessor reads the HIGH floor leaf",
            CONFIG,
            _CFG_PROPERTIES["conflicted_base_share"],
            "    @property\n"
            "    def conflicted_base_share(self) -> float:\n"
            "        # mutation: reads the wrong leaf\n"
            "        return float(self.min_independent_families_high.value)",
        ),
        (
            "CX8 the ordering validator removed (swapped ceilings load silently)",
            CONFIG,
            _CFG_VALIDATOR_ORDER,
            "        _high = int(self.max_dissenting_pillars_high.value)\n"
            "        _medium = int(self.max_dissenting_pillars_medium.value)\n"
            "        if False:",
        ),
        (
            "CX9 the ordering validator inverted (only swapped configs pass)",
            CONFIG,
            _CFG_VALIDATOR_ORDER,
            "        _high = int(self.max_dissenting_pillars_high.value)\n"
            "        _medium = int(self.max_dissenting_pillars_medium.value)\n"
            "        if _high < _medium:",
        ),
        (
            "CX10 the negative-ceiling check removed",
            CONFIG,
            _CFG_VALIDATOR_NEGATIVE,
            "        if _high > _medium:\n"
            "            raise ValueError(\n"
            '                f"scorecard.max_dissenting_pillars_high ({_high}) must not exceed "\n'
            '                f"max_dissenting_pillars_medium ({_medium}): HIGH is the STRICTER "\n'
            '                "verdict, so it cannot tolerate more dissent than MEDIUM. '
            'Inverting "\n'
            '                "them would make the MEDIUM band unreachable and silently '
            'promote "\n'
            '                "every MEDIUM read to HIGH."\n'
            "            )\n"
            "        if False:",
        ),
        (
            "CX11 the dead-config check removed (a ceiling above 3 loads)",
            CONFIG,
            _CFG_VALIDATOR_DEAD,
            "        if False:",
        ),
    ]


def _mutation_table() -> list[tuple[str, Path, str, str]]:
    return [
        *_opposition_mutations(),
        *_gate_mutations(),
        *_census_mutations(),
        *_value_key_mutations(),
        *_warning_mutations(),
        *_contract_mutations(),
        *_confidence_mutations(),
        *_config_mutations(),
        # -- O-72 canary (CONTROL) ----------------------------------------
        # NOT a revert of a project correction: a mutation CERTAIN to be caught,
        # so the sweep REFUSES TO CERTIFY when it survives. A sweep whose anchors
        # resolve but whose selection no longer reaches the mutated module reports
        # every mutant as killed -- the D-051 trap. The canary is the only entry
        # here that separates "the suite is strong" from "the sweep stopped
        # testing". It replaces a module-level literal with a SYNTAX ERROR, so the
        # kill is STRUCTURAL (tests/ cannot collect) rather than incidental.
        (
            "CANARY1 the module literal is replaced with a syntax error (CONTROL)",
            SRC,
            '__all__ = [\n    "ConvergenceVerdict",',
            "__CANARY__ = <<<SYNTAX ERROR>>>",
        ),
    ]


_MUTATIONS: list[tuple[str, Path, str, str]] = _mutation_table()

#: Mutations that cannot be killed because they cannot change behaviour.
#: Every entry must carry a PROOF — "we could not write a failing test" is not the
#: same claim as "the two programs are equivalent", and only the second belongs
#: here. An empty set is a legitimate outcome; a growing set is not.
#: Mutations that cannot be killed because they cannot change behaviour.
#: Every entry must carry a PROOF — "we could not write a failing test" is not the
#: same claim as "the two programs are equivalent", and only the second belongs
#: here.
#:
#: The five entries below are **not** a weak suite. They are the same fact stated
#: four ways: ``CONFLICTED`` is tested first and consumes every opposed read, so a
#: read that reaches the dissent gates has all its non-neutral pillars pointing the
#: same way — ``max(up, down) == n`` — and therefore ``dissent == 0``, always. The
#: enumeration in ``test_no_read_reaches_the_dissent_gates_with_a_dissenter``
#: asserts exactly this (reachable dissent values past the gate: ``{0}``).
#:
#: Two consequences follow, and each is a mutation below:
#:
#: * the dissent operand never reaches 1, so ``dissent <= 0``, ``<= 1`` and
#:   ``<= 2`` are the *same predicate* — the MEDIUM ceiling cannot bind;
#: * a predicate that is always true cannot change a verdict, so tightening the
#:   HIGH gate to the MEDIUM ceiling is a no-op.
#:
#: Two of the original survivors are deliberately **absent** from this set, because
#: they are missing tests rather than inert mutations:
#:
#: * ``MX2m`` (dissent zeroed) changes the published ``dissenting_pillars`` on a
#:   CONFLICTED read, so it is output-observable and a test now kills it.
#: * ``MX3g`` (the non-dict guard removed) *can* change behaviour — it raises on a
#:   malformed supplier — it simply cannot be reached without a monkeypatched
#:   ``count_independent_families``. There is no test for that path, and it stays a
#:   reported survivor until one exists.
_EXPECTED_INERT: frozenset[str] = frozenset(
    {
        # PROOF: the HIGH gate's ceiling compares `dissent <= settings.high...`
        # (0). Replacing it with the MEDIUM ceiling (1) only differs when a read
        # reaches the gate with dissent == 1. Proved impossible: opposition is
        # tested first, and a non-opposed read has max(up, down) == n, so
        # dissent = n - max(up, down) = 0. Verified by enumeration over all 80
        # non-neutral pillar combinations at three family counts — the reachable
        # dissent set past the gate is exactly {0}
        # (`test_no_read_reaches_the_dissent_gates_with_a_dissenter`).
        "MX2a the HIGH gate permits the MEDIUM ceiling (MEDIUM becomes unreachable)",
        # PROOF: same operand, opposite direction. Reading the HIGH leaf (0) for
        # the MEDIUM ceiling gives `dissent <= 0`, which is `dissent <= 1` on the
        # only reachable value, 0. The band stays reachable via the family floor,
        # and the enumeration in
        # `test_the_medium_band_is_reachable_through_the_family_floor` confirms
        # MEDIUM is still produced.
        "MX2e the MEDIUM gate's ceiling uses the HIGH leaf (MEDIUM never fires)",
        # PROOF: `dissent <= 2` versus `dissent <= 1` differ only at dissent == 2,
        # and dissent == 2 is itself CONFLICTED (both signs present). No read can
        # carry dissent == 2 into this gate.
        "MX2f the MEDIUM gate permits two dissenters",
    }
)


def check_targets(originals: dict[Path, str]) -> list[str]:
    """Refuse to run if any mutation's target is missing or AMBIGUOUS.

    The ambiguity check is the one that matters. ``str.replace(old, new, 1)``
    rewrites the FIRST occurrence of ``old``, so a target string that appears
    twice silently mutates whichever function comes first in the file. The
    mutation then looks applied (the file *did* change), the tests pass because
    they were never exercising the mutated line, and the survivor list reports a
    weak test that does not exist. That is D-031's **mis-targeted** class, and it
    is indistinguishable from a real survivor without this gate.

    Back-porting the gate onto the earlier sweeps found a live instance of it
    (``C-1a`` anchored on ``      value: 0.8``, which occurs five times in
    ``settings.yaml``). Hence: fatal, not a warning.
    """
    problems: list[str] = []
    for name, target, old, new in _MUTATIONS:
        text = originals[target]
        if old == new:
            problems.append(f"INERT BY CONSTRUCTION (old == new): {name}")
            continue
        count = text.count(old)
        if count == 0:
            problems.append(f"ABSENT: {name}  [{target.name}]")
        elif count > 1:
            problems.append(f"AMBIGUOUS (x{count}): {name}  [{target.name}]")
    return problems


def run_tests() -> bool:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/models/test_scorecard.py",
            "tests/test_infrastructure.py",
            "-q",
            "--no-header",
            "-m",
            "not live",
        ],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def _applied_mutations(originals: dict[Path, str]) -> list[tuple[str, Path, str, str]]:
    """Find mutations currently in the tree: ``old`` absent AND ``new`` present."""
    found: list[tuple[str, Path, str, str]] = []
    for name, target, old, new in _MUTATIONS:
        text = originals[target]
        if old not in text and new in text:
            found.append((name, target, old, new))
    return found


def repair_leftover_mutations(originals: dict[Path, str]) -> list[str]:
    """Invert any mutation left applied by an interrupted run.

    A naive re-run would adopt the mutated file as the baseline and then report a
    full kill count for a suite that had never seen the original (D-035 rule 19).
    """
    repaired: list[str] = []
    for name, target, old, new in _applied_mutations(originals):
        originals[target] = originals[target].replace(new, old, 1)
        target.write_text(originals[target], encoding="utf-8", newline="")
        repaired.append(name)
    return repaired


def main() -> int:
    # O-103: heal, protect, spend in ONE call. The bare `try/finally` this
    # replaces restored a crash but could not survive a SIGTERM -- on win32
    # no Python signal handler runs and a killed process gets no `finally`
    # turn -- and it had no heal-at-start at all, so a previous kill left a
    # mutant to be adopted as the baseline (D-081).
    with sweep_lifecycle(sorted(SWEEP_PATHS)) as originals:
        return _run_sweep(originals)


def _run_sweep(originals: dict[Path, str]) -> int:

    problems = check_targets(originals)
    if problems:
        print("REFUSING TO RUN — the mutation table does not point at unique, present text:")
        for problem in problems:
            print(f"  {problem}")
        print()
        print("Fix the table (anchor ambiguous targets on surrounding unique context)")
        print("and re-run. Any number this script would report is meaningless.")
        return 3

    repaired = repair_leftover_mutations(originals)
    if repaired:
        print("REPAIRED left over from an interrupted run:")
        for name in repaired:
            print(f"  reverted -> {name}")
        print()

    survived: list[tuple[str, str]] = []
    for name, target, old, new in _MUTATIONS:
        pristine = originals[target]
        if old not in pristine:
            print(f"PATTERN MISSING   {name}  [{target.name}]")
            survived.append((name, "pattern-not-found"))
            continue
        target.write_text(pristine.replace(old, new, 1), encoding="utf-8", newline="")
        caught = not run_tests()
        target.write_text(pristine, encoding="utf-8", newline="")
        print(f"{'KILLED' if caught else 'SURVIVED':17} {name}")
        if not caught:
            survived.append((name, "survived"))

    leftover = _applied_mutations({p: p.read_text(encoding="utf-8") for p in originals})
    if leftover:
        print()
        print("ERROR: a mutation is still applied after the sweep:")
        for name, _, _, _ in leftover:
            print(f"  STILL APPLIED -> {name}")
        return 2

    print()
    unexpected = [(n, w) for n, w in survived if n not in _EXPECTED_INERT]
    total = len(_MUTATIONS)
    print(f"{total - len(survived)}/{total} killed")
    if _EXPECTED_INERT:
        print(f"({len(_EXPECTED_INERT)} expected-inert by design)")
    for name, why in unexpected:
        print(f"  SURVIVOR ({why}): {name}")
    # O-72's canary gate. A canary that SURVIVES means the sweep ran but tested
    # nothing: its selection no longer reaches the mutated module, so every
    # "killed" above is a statement about the harness rather than the suite.
    # This is the D-051 trap, and it is why CANARY1 is REQUIRED to be killed
    # rather than tolerated as a survivor.
    if any(name.startswith("CANARY1 ") for name, _ in survived):
        print()
        print("REFUSING TO CERTIFY: the honesty canary SURVIVED.")
        print("  !! CANARY1 -- the test selection no longer reaches the mutated")
        print("     module, so no kill above is evidence about the suite (O-72).")
        return 3

    return 0 if not unexpected else 1


if __name__ == "__main__":
    raise SystemExit(main())
