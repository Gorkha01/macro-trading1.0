"""Mutation sweep for ``inversion_probability_adjustment`` (Module 8, D-049).

This function is small enough that its behaviour can be enumerated, so the sweep
does exactly that rather than aiming substitutions by hand. Two consequences
worth stating up front, because they are what the earlier sweeps in this
repository learned the hard way:

* **The dimension generators cannot miss their target**, because they rewrite a
  whole expression whose text is derivable from the shipped arithmetic. There is
  no "the string moved" failure mode for those.
* **Every hand-written target is gated by** ``check_targets`` (D-048), which
  refuses to run on an ABSENT or AMBIGUOUS ``old`` string. A sweep that reports a
  number while pointing at the wrong function is worse than no sweep: it changes
  the file, so it looks applied, and the surviving-test conclusion is then drawn
  about code nobody mutated.

Mutations, grouped by what they attack — the group is what tells you which test
is missing when one survives (D-031):

* **M1** the branch structure: the no-inversion guard dropped or inverted, the
  adjustment applied to a non-inverted curve, the sign test made strict.
* **M2** the two saturating factors: the depth or duration ratio inverted,
  unclamped, offset, or the two swapped.
* **M3** the ceiling: the clamp removed, made a floor, applied before the
  adjustment, or its binding flag computed wrongly.
* **M4** the published residue: each of the six ``value`` keys renamed, inverted,
  or given the wrong leaf.
* **M5** the disclosures: each warning branch deleted.
* **M6** the contract: ``extra="forbid"``, the slope/duration validator, the
  open-interval bounds on the base rate.
* **M7** the confidence: a hardcoded value restored (Section 22.8).
* **C1** the config accessors: hardcoded to the shipped literals, swapped, or
  read from the wrong leaf.
* **K1** the ceiling validator, which is the one piece of config that stops a
  threshold from being decorative or dead.

**Run this in the FOREGROUND.** The sweep rewrites ``yield_curve.py`` and
``config.py`` in place, so any concurrent test run, live check or probe reads a
mutated module. D-047's Postscript 2 records a contaminated reading produced
exactly that way; the blast radius here is the whole repository.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SRC = Path("src/macro_engine/models/yield_curve.py")
CONFIG = Path("src/macro_engine/config.py")

# --- The shipped text each hand-written mutation targets --------------------
#
# Transcribed from the source. `check_targets` verifies every one is present
# EXACTLY ONCE before the sweep runs.

_MODEL_HEADER = '        model_name="inversion_probability_adjustment",\n        country="us",'

_GUARD = "    if inputs.current_slope_bp >= 0:"

_DEPTH_FACTOR = (
    "    depth_factor = min(abs(inputs.current_slope_bp) / settings.depth_saturation, 1.0)"
)
_DURATION_FACTOR = (
    "    duration_factor = min(inputs.weeks_inverted / settings.duration_cap_weeks, 1.0)"
)
_ADJUSTMENT = (
    "    adjustment = settings.max_probability_adjustment * depth_factor * duration_factor"
)
_UNCAPPED = "    uncapped = base_rate + adjustment"
_ADJUSTED = "    adjusted = min(uncapped, settings.ceiling)"
_CEILING_BINDING = "    reached_ceiling = adjusted < uncapped"
_SATURATED = (
    "    saturated = (\n"
    "        abs(inputs.current_slope_bp) >= settings.depth_saturation\n"
    "        or inputs.weeks_inverted >= settings.duration_cap_weeks\n"
    "    )"
)
_PAST_TURN = "    duration_past_turn = inputs.weeks_inverted > settings.duration_cap_weeks"

_INVERTED_CALL = (
    '            "adjusted_probability": round(adjusted, 4),\n'
    '            "base_rate": base_rate,\n'
    '            "adjustment": round(adjustment, 4),\n'
    '            "depth_factor": round(depth_factor, 4),\n'
    '            "duration_factor": round(duration_factor, 4),\n'
    '            "saturated": saturated,\n'
    '            "ceiling_binding": reached_ceiling,\n'
    "            # The published base rates are the whole point of D-029 compliance:\n"
    "            # without them a reader cannot tell 0.55 from a signal (0.489) plus\n"
    "            # a prior (0.209) or from a near-coin-flip with no information.\n"
    '            "inverted_base_rate": settings.base_rates.inverted_12mo,\n'
    '            "not_inverted_base_rate": settings.base_rates.not_inverted_12mo,'
)

_NO_INVERSION_BODY = (
    "            value={\n"
    '                "adjusted_probability": base_rate,\n'
    '                "base_rate": base_rate,\n'
    '                "adjustment": 0.0,\n'
    '                "depth_factor": 0.0,\n'
    '                "duration_factor": 0.0,\n'
    '                "saturated": False,\n'
    '                "ceiling_binding": reached_ceiling,\n'
    "            },"
)

_NO_INVERSION_CONF = (
    "            confidence=compute_confidence(ConfidenceInputs()),\n"
    "            interpretation=(\n"
    '                f"Curve not inverted ({inputs.current_slope_bp:+.1f}bp) — "'
)

_CONFIDENCE_INVERTED = (
    "        confidence=compute_confidence(ConfidenceInputs()),\n"
    "        interpretation=(\n"
    '            f"Recession probability (12mo): {adjusted:.1%} "'
)

_WARNING_HEADS = {
    "w1_illustrative": (
        "    warnings = [\n"
        '        "ILLUSTRATIVE heuristic, not a fitted historical model — Section 15.20-B "'
    ),
    "w2_saturated": "    if saturated:",
    "w3_past_turn": "    if duration_past_turn:",
    "w4_ceiling": "    if ceiling_binding:",
}

_PUBLISHED_BASE_RATES = (
    '            "inverted_base_rate": settings.base_rates.inverted_12mo,\n'
    '            "not_inverted_base_rate": settings.base_rates.not_inverted_12mo,'
)

_VALIDATORS = {
    "v_duration_sign": "        if self.current_slope_bp >= 0 and self.weeks_inverted != 0:",
    # The base-rate bounds, anchored on the field they belong to. The bare
    # `gt=0.0,` appears on several fields in this module, so an unanchored
    # mutation would rewrite whichever field the parser reached first.
    "v_base_interval": (
        "    base_rate_recession_prob_12mo: float = Field(\n        gt=0.0,\n        lt=1.0,"
    ),
}

_MODEL_CONFIG = (
    '    model_config = ConfigDict(extra="forbid")\n\n    current_slope_bp: float = Field('
)

# --- config.py targets ------------------------------------------------------

_CFG_PROPERTIES = {
    "depth_saturation": (
        "    @property\n"
        "    def depth_saturation(self) -> float:\n"
        '        """Inversion depth, in bp, at which the depth factor reaches 1.0.'
    ),
    "duration_cap_weeks": (
        "    @property\n"
        "    def duration_cap_weeks(self) -> float:\n"
        '        """Weeks inverted at which the duration factor reaches 1.0.'
    ),
    "max_probability_adjustment": (
        "    @property\n"
        "    def max_probability_adjustment(self) -> float:\n"
        '        """The largest amount the inversion signal may add to the base rate."""\n'
        "        return float(self.max_adjustment.value)"
    ),
    "ceiling": (
        "    @property\n"
        "    def ceiling(self) -> float:\n"
        '        """Hard cap on the returned probability — the system never claims certainty."""\n'
        "        return float(self.probability_ceiling.value)"
    ),
}

#: Both single-line accessors, in source order, for the SWAP mutation. They are
#: two lines apart only because the docstrings are one line each.
_CFG_TWO_ACCESSORS = (
    "    @property\n"
    "    def max_probability_adjustment(self) -> float:\n"
    '        """The largest amount the inversion signal may add to the base rate."""\n'
    "        return float(self.max_adjustment.value)\n"
    "\n"
    "    @property\n"
    "    def ceiling(self) -> float:\n"
    '        """Hard cap on the returned probability — the system never claims certainty."""\n'
    "        return float(self.probability_ceiling.value)"
)

_CFG_CEILING_VALIDATOR = "        if not _low < _ceiling < _high:"


# ---------------------------------------------------------------------------
# The behavioural matrix the mutations are derived from
# ---------------------------------------------------------------------------
#
# The function's output space is small and fully enumerable, which makes the
# "did any test actually try this" question answerable rather than assumed:
#
#   * the depth factor has FIVE regimes (zero, nothing, partial, exactly-1,
#     clamped-past-1),
#   * the duration factor has the same five,
#   * the ceiling has two (binding, not),
#   * the branch has two (inverted, not).
#
# A mutation of any single factor must be visible in at least one cell, and the
# generator below produces one representative input per regime so that statement
# can be checked rather than believed.

#: Depth regimes, as (label, slope in bp) pairs. The values are chosen relative
#: to the config cap so a recalibration moves them with it.
_DEPTH_REGIMES: tuple[tuple[str, float], ...] = (
    ("zero", 0.0),
    ("shallow", -5.0),
    ("partial", -40.0),
    ("exact", -100.0),
    ("beyond", -170.0),
)

#: Duration regimes, as (label, weeks) pairs.
_DURATION_REGIMES: tuple[tuple[str, int], ...] = (
    ("none", 0),
    ("short", 4),
    ("partial", 13),
    ("exact", 26),
    ("beyond", 107),
)

#: Base rates that put the ceiling on either side of the clamp. With a
#: max_adjustment of 0.35, a base of 0.30 tops out at 0.65 (no clamp) and a base
#: of 0.489 tops out at 0.839 (clamped at 0.80).
_BASE_NO_CLAMP = 0.30
_BASE_CLAMPS = 0.489


# ---------------------------------------------------------------------------
# The mutations
# ---------------------------------------------------------------------------


def _factor_mutations() -> list[tuple[str, Path, str, str]]:
    """The two saturating factors, broken one way each.

    Generated rather than aimed: each mutation rewrites the whole assignment, so
    the target text is derivable from the shipped arithmetic instead of
    transcribed from a memory of it. The *swapped* pair and the *unclamped* pair
    are the two an "arithmetic looks right" test would miss — an inverted ratio
    still produces a plausible number in [0, 1] for shallow inputs.
    """
    return [
        (
            "MX2a the depth ratio is inverted (deeper reads as shallower)",
            SRC,
            _DEPTH_FACTOR,
            "    depth_factor = min(settings.depth_saturation / abs(inputs.current_slope_bp), 1.0)",
        ),
        (
            "MX2b the depth factor is unclamped (deep inversions scale without limit)",
            SRC,
            _DEPTH_FACTOR,
            "    depth_factor = abs(inputs.current_slope_bp) / settings.depth_saturation",
        ),
        (
            "MX2c the depth factor ignores the slope (constant)",
            SRC,
            _DEPTH_FACTOR,
            "    depth_factor = 1.0",
        ),
        (
            "MX2d the depth factor applies `>` instead of `>=` at the cap",
            SRC,
            _DEPTH_FACTOR,
            "    depth_factor = 1.0 if abs(inputs.current_slope_bp) > settings.depth_saturation "
            "else abs(inputs.current_slope_bp) / settings.depth_saturation",
        ),
        (
            "MX2e the duration ratio is inverted (longer reads as shorter)",
            SRC,
            _DURATION_FACTOR,
            "    duration_factor = min(\n"
            "        settings.duration_cap_weeks / max(inputs.weeks_inverted, 1), 1.0\n"
            "    )",
        ),
        (
            "MX2f the duration factor is unclamped (long inversions scale without limit)",
            SRC,
            _DURATION_FACTOR,
            "    duration_factor = inputs.weeks_inverted / settings.duration_cap_weeks",
        ),
        (
            "MX2g the duration factor ignores the elapsed weeks (constant)",
            SRC,
            _DURATION_FACTOR,
            "    duration_factor = 1.0",
        ),
        (
            "MX2h the duration factor counts DAYS rather than weeks (a 7x error)",
            SRC,
            _DURATION_FACTOR,
            "    duration_factor = min(\n"
            "        inputs.weeks_inverted * 7 / settings.duration_cap_weeks, 1.0\n"
            "    )",
        ),
        (
            "MX2i the two factors are divided rather than multiplied",
            SRC,
            _ADJUSTMENT,
            "    adjustment = (\n"
            "        settings.max_probability_adjustment * depth_factor / duration_factor\n"
            "    )",
        ),
        (
            "MX2j the two factors are summed instead of multiplied",
            SRC,
            _ADJUSTMENT,
            "    adjustment = (\n"
            "        settings.max_probability_adjustment\n"
            "        * (depth_factor + duration_factor)\n"
            "        / 2\n"
            "    )",
        ),
        (
            "MX2k the adjustment ignores the depth factor entirely",
            SRC,
            _ADJUSTMENT,
            "    adjustment = settings.max_probability_adjustment * duration_factor",
        ),
        (
            "MX2l the adjustment ignores the duration factor entirely",
            SRC,
            _ADJUSTMENT,
            "    adjustment = settings.max_probability_adjustment * depth_factor",
        ),
        (
            "MX2m the adjustment subtracts instead of adding to the base rate",
            SRC,
            _UNCAPPED,
            "    uncapped = base_rate - adjustment",
        ),
        (
            "MX2n the adjustment is added to itself (the base rate dropped)",
            SRC,
            _UNCAPPED,
            "    uncapped = adjustment + adjustment",
        ),
    ]


def _ceiling_mutations() -> list[tuple[str, Path, str, str]]:
    """The ceiling, its binding flag, and the saturation flags.

    ``ceiling_binding`` is the one published key whose *meaning* is a comparison,
    so three of these attack the comparison rather than the clamp — a binding flag
    that is always true, always false, or inverted is exactly as wrong as a
    missing clamp and much harder to notice, because the number stays plausible.
    """
    return [
        (
            "MX3a the ceiling clamp removed (the heuristic may exceed certainty)",
            SRC,
            _ADJUSTED,
            "    adjusted = uncapped",
        ),
        (
            "MX3b the ceiling applied as a FLOOR (every result pushed up to the cap)",
            SRC,
            _ADJUSTED,
            "    adjusted = max(uncapped, settings.ceiling)",
        ),
        (
            "MX3c the clamp applied to the adjustment rather than the result",
            SRC,
            _ADJUSTED,
            "    adjusted = base_rate + min(adjustment, settings.ceiling)",
        ),
        (
            "MX3d the clamp uses the depth cap instead of the ceiling",
            SRC,
            _ADJUSTED,
            "    adjusted = min(uncapped, settings.depth_saturation)",
        ),
        (
            "MX3e the binding flag inverted (a clamped result reads as unclamped)",
            SRC,
            _CEILING_BINDING,
            "    reached_ceiling = adjusted >= uncapped",
        ),
        (
            "MX3f the binding flag is always False (the warning becomes unreachable)",
            SRC,
            _CEILING_BINDING,
            "    reached_ceiling = False",
        ),
        (
            "MX3g the binding flag is always True (the warning becomes a constant)",
            SRC,
            _CEILING_BINDING,
            "    reached_ceiling = True",
        ),
        (
            "MX3h the binding flag tests the wrong quantity (slope, not the clamp)",
            SRC,
            _CEILING_BINDING,
            "    reached_ceiling = inputs.current_slope_bp < 0",
        ),
        (
            "MX3i the saturation flag is never set",
            SRC,
            _SATURATED,
            "    saturated = False",
        ),
        (
            "MX3j the saturation flag is always set",
            SRC,
            _SATURATED,
            "    saturated = True",
        ),
        (
            "MX3k saturation uses a strict `>` at both caps",
            SRC,
            _SATURATED,
            "    saturated = (\n"
            "        abs(inputs.current_slope_bp) > settings.depth_saturation\n"
            "        or inputs.weeks_inverted > settings.duration_cap_weeks\n"
            "    )",
        ),
        (
            "MX3l saturation requires BOTH caps rather than either",
            SRC,
            _SATURATED,
            "    saturated = (\n"
            "        abs(inputs.current_slope_bp) >= settings.depth_saturation\n"
            "        and inputs.weeks_inverted >= settings.duration_cap_weeks\n"
            "    )",
        ),
        (
            "MX3m past-turn made inclusive (exactly 26 weeks reads as past it)",
            SRC,
            _PAST_TURN,
            "    duration_past_turn = inputs.weeks_inverted >= settings.duration_cap_weeks",
        ),
        (
            "MX3n the past-turn flag is never set (the reversal is undisclosed)",
            SRC,
            _PAST_TURN,
            "    duration_past_turn = False",
        ),
    ]


def _branch_mutations() -> list[tuple[str, Path, str, str]]:
    """The no-inversion guard and the sign test at its boundary.

    ``>= 0`` is the guard's whole content, so every way of getting it wrong is a
    boundary question: ``> 0`` lets a flat curve through as inverted, ``<= 0``
    sends a first-day inversion down the no-adjustment path. Both are silent —
    the returned number stays in [0, 1] and the interpretation stays grammatical.
    """
    return [
        (
            "MX1a the no-inversion guard removed (an adjustment on a normal curve)",
            SRC,
            _GUARD,
            "    if False:",
        ),
        (
            "MX1b the guard inverted (inversions take the no-adjustment path)",
            SRC,
            _GUARD,
            "    if inputs.current_slope_bp < 0:",
        ),
        (
            "MX1c the guard made strict (a flat curve counts as inverted)",
            SRC,
            _GUARD,
            "    if inputs.current_slope_bp > 0:",
        ),
        (
            "MX1d the guard accepts a flat curve as inverted (`<=`)",
            SRC,
            _GUARD,
            "    if inputs.current_slope_bp <= 0:",
        ),
        (
            "MX1e the no-inversion branch returns zero instead of the stated prior",
            SRC,
            _NO_INVERSION_BODY,
            "            value={\n"
            '                "adjusted_probability": 0.0,\n'
            '                "base_rate": base_rate,\n'
            '                "adjustment": 0.0,\n'
            '                "depth_factor": 0.0,\n'
            '                "duration_factor": 0.0,\n'
            '                "saturated": False,\n'
            '                "ceiling_binding": reached_ceiling,\n'
            "            },",
        ),
        (
            "MX1f the no-inversion branch reports a saturated duration",
            SRC,
            _NO_INVERSION_BODY,
            "            value={\n"
            '                "adjusted_probability": base_rate,\n'
            '                "base_rate": base_rate,\n'
            '                "adjustment": 0.0,\n'
            '                "depth_factor": 0.0,\n'
            '                "duration_factor": 1.0,\n'
            '                "saturated": False,\n'
            '                "ceiling_binding": reached_ceiling,\n'
            "            },",
        ),
    ]


def _value_key_mutations() -> list[tuple[str, Path, str, str]]:
    """Each published key, renamed and inverted.

    Two survivors in the trilemma sweep (D-047) survived for a single reason: no
    test read the keys they changed. The keys here are asserted by several tests,
    and the renames below are the check that this remains true — a rename is
    caught by any test that reads the key, including one that only checks it is
    a float.
    """
    return [
        (
            "MX4a `adjusted_probability` renamed",
            SRC,
            _INVERTED_CALL,
            _INVERTED_CALL.replace('"adjusted_probability"', '"probability"'),
        ),
        (
            "MX4b `base_rate` renamed",
            SRC,
            _INVERTED_CALL,
            _INVERTED_CALL.replace('"base_rate": base_rate', '"prior": base_rate'),
        ),
        (
            "MX4c `depth_factor` renamed",
            SRC,
            _INVERTED_CALL,
            _INVERTED_CALL.replace('"depth_factor"', '"depth"'),
        ),
        (
            "MX4d `duration_factor` renamed",
            SRC,
            _INVERTED_CALL,
            _INVERTED_CALL.replace('"duration_factor"', '"duration"'),
        ),
        (
            "MX4e `saturated` renamed",
            SRC,
            _INVERTED_CALL,
            _INVERTED_CALL.replace('"saturated"', '"capped"'),
        ),
        (
            "MX4f `ceiling_binding` renamed",
            SRC,
            _INVERTED_CALL,
            _INVERTED_CALL.replace('"ceiling_binding"', '"clamped"'),
        ),
        (
            "MX4g the published `adjustment` is always zero",
            SRC,
            _INVERTED_CALL,
            _INVERTED_CALL.replace('"adjustment": round(adjustment, 4),', '"adjustment": 0.0,'),
        ),
        (
            "MX4h the published depth factor is the duration factor",
            SRC,
            _INVERTED_CALL,
            _INVERTED_CALL.replace(
                '"depth_factor": round(depth_factor, 4),',
                '"depth_factor": round(duration_factor, 4),',
            ),
        ),
        (
            "MX4i the published saturated flag inverted",
            SRC,
            _INVERTED_CALL,
            _INVERTED_CALL.replace('"saturated": saturated,', '"saturated": not saturated,'),
        ),
        (
            "MX4j the published ceiling-binding flag inverted",
            SRC,
            _INVERTED_CALL,
            _INVERTED_CALL.replace(
                '"ceiling_binding": reached_ceiling,',
                '"ceiling_binding": not reached_ceiling,',
            ),
        ),
        (
            "MX4k the two published base rates SWAPPED (the D-029 disclosure lies)",
            SRC,
            _PUBLISHED_BASE_RATES,
            '            "inverted_base_rate": settings.base_rates.not_inverted_12mo,\n'
            '            "not_inverted_base_rate": settings.base_rates.inverted_12mo,',
        ),
        (
            "MX4l the published inverted base rate reads the unconditional leaf",
            SRC,
            _PUBLISHED_BASE_RATES,
            '            "inverted_base_rate": settings.base_rates.unconditional_12mo,\n'
            '            "not_inverted_base_rate": settings.base_rates.not_inverted_12mo,',
        ),
        (
            "MX4m the published base rates are dropped entirely",
            SRC,
            _PUBLISHED_BASE_RATES,
            "",
        ),
    ]


def _warning_mutations() -> list[tuple[str, Path, str, str]]:
    """Each disclosure removed, one at a time.

    Deleting a branch is the strongest form of "this warning contributes
    nothing": if the suite still passes, the warning was not being read, and the
    function has quietly stopped disclosing something Section 22.5 or D-029
    requires it to disclose.
    """
    out: list[tuple[str, Path, str, str]] = []
    for label, head in _WARNING_HEADS.items():
        if label == "w1_illustrative":
            out.append(
                (
                    "MX5a the illustrative-heuristic warning removed",
                    SRC,
                    head + "\n"
                    "        "
                    '"specifies this as a mechanism-first placeholder for a Phase 5+ logistic "\n'
                    '        "fit. The 6-24 month timing lag is genuinely uncertain."\n'
                    "    ]",
                    "    warnings = []",
                )
            )
        else:
            out.append(
                (
                    f"MX5{label[1]} the {label[2:]} warning branch removed",
                    SRC,
                    head,
                    "    if False:",
                )
            )
    return out


def _contract_mutations() -> list[tuple[str, Path, str, str]]:
    """The input contract and the model identity."""
    return [
        (
            "MX6a `extra='forbid'` removed (typo'd inputs are silently dropped)",
            SRC,
            _MODEL_CONFIG,
            '    model_config = ConfigDict(extra="ignore")\n\n    current_slope_bp: float = Field(',
        ),
        (
            "MX6b the base-rate open-interval bound loosened to allow 1.0",
            SRC,
            _VALIDATORS["v_base_interval"],
            "    base_rate_recession_prob_12mo: float = Field(\n        gt=0.0,\n        le=1.0,",
        ),
        (
            "MX6c the base-rate lower bound loosened to allow 0.0",
            SRC,
            _VALIDATORS["v_base_interval"],
            "    base_rate_recession_prob_12mo: float = Field(\n        ge=0.0,\n        lt=1.0,",
        ),
        (
            "MX6d the slope/duration validator removed (stale duration passes)",
            SRC,
            _VALIDATORS["v_duration_sign"],
            "        if False:",
        ),
        (
            "MX6e the slope/duration validator inverted",
            SRC,
            _VALIDATORS["v_duration_sign"],
            "        if self.current_slope_bp < 0 and self.weeks_inverted == 0:",
        ),
        (
            "MX6f the result is labelled with the caller's country",
            SRC,
            _MODEL_HEADER,
            '        model_name="inversion_probability_adjustment",\n        country="gb",',
        ),
        (
            "MX6g the model name is wrong (a caller cannot route the result)",
            SRC,
            _MODEL_HEADER,
            '        model_name="inversion_adjustment",\n        country="us",',
        ),
    ]


def _confidence_mutations() -> list[tuple[str, Path, str, str]]:
    """Section 22.8: a hardcoded confidence is forbidden in both branches."""
    return [
        (
            "MX7a the inverted branch hardcodes the specification's 0.35",
            SRC,
            _CONFIDENCE_INVERTED,
            "        confidence=0.35,\n"
            "        interpretation=(\n"
            '            f"Recession probability (12mo): {adjusted:.1%} "',
        ),
        (
            "MX7b the no-inversion branch hardcodes the specification's 0.3",
            SRC,
            _NO_INVERSION_CONF,
            "            confidence=0.3,\n"
            "            interpretation=(\n"
            '                f"Curve not inverted ({inputs.current_slope_bp:+.1f}bp) — "',
        ),
        (
            "MX7c the two branches swap their confidence (flat-by-accident)",
            SRC,
            _CONFIDENCE_INVERTED,
            "        confidence=compute_confidence(\n"
            "            ConfidenceInputs(depends_on_unobservable=True)\n"
            "        ),\n"
            "        interpretation=(\n"
            '            f"Recession probability (12mo): {adjusted:.1%} "',
        ),
    ]


def _config_mutations() -> list[tuple[str, Path, str, str]]:
    """The accessors and the ceiling validator, in `config.py`."""
    return [
        (
            "CX1 the depth accessor hardcodes the shipped literal",
            CONFIG,
            _CFG_PROPERTIES["depth_saturation"],
            "    @property\n"
            "    def depth_saturation(self) -> float:\n"
            "        # mutation: the shipped literal replaces the accessor\n"
            "        return 100.0",
        ),
        (
            "CX2 the duration accessor hardcodes the shipped literal",
            CONFIG,
            _CFG_PROPERTIES["duration_cap_weeks"],
            "    @property\n"
            "    def duration_cap_weeks(self) -> float:\n"
            "        # mutation: the shipped literal replaces the accessor\n"
            "        return 26.0",
        ),
        (
            "CX3 the ceiling accessor hardcodes the shipped literal",
            CONFIG,
            _CFG_PROPERTIES["ceiling"],
            "    @property\n"
            "    def ceiling(self) -> float:\n"
            "        # mutation: the shipped literal replaces the accessor\n"
            "        return 0.80",
        ),
        (
            "CX4 the max-adjustment accessor hardcodes the shipped literal",
            CONFIG,
            _CFG_PROPERTIES["max_probability_adjustment"],
            "    @property\n"
            "    def max_probability_adjustment(self) -> float:\n"
            "        # mutation: the shipped literal replaces the accessor\n"
            "        return 0.35",
        ),
        (
            "CX5 the max-adjustment and ceiling accessors swap their leaves",
            CONFIG,
            _CFG_TWO_ACCESSORS,
            "    @property\n"
            "    def max_probability_adjustment(self) -> float:\n"
            "        # mutation: reads the ceiling leaf\n"
            "        return float(self.probability_ceiling.value)\n"
            "\n"
            "    @property\n"
            "    def ceiling(self) -> float:\n"
            "        # mutation: reads the max-adjustment leaf\n"
            "        return float(self.max_adjustment.value)",
        ),
        (
            "CX6 the ceiling validator removed (a decorative cap passes validation)",
            CONFIG,
            _CFG_CEILING_VALIDATOR,
            "        if False:",
        ),
        (
            "CX7 the ceiling validator inverted (only backward configs pass)",
            CONFIG,
            _CFG_CEILING_VALIDATOR,
            "        if _low < _ceiling < _high:",
        ),
    ]


def _mutation_table() -> list[tuple[str, Path, str, str]]:
    return [
        *_branch_mutations(),
        *_factor_mutations(),
        *_ceiling_mutations(),
        *_value_key_mutations(),
        *_warning_mutations(),
        *_contract_mutations(),
        *_confidence_mutations(),
        *_config_mutations(),
    ]


_MUTATIONS: list[tuple[str, Path, str, str]] = _mutation_table()

#: Mutations that cannot be killed because they cannot change behaviour.
#: Every entry must carry a PROOF — "we could not write a failing test" is not the
#: same claim as "the two programs are equivalent", and only the second belongs
#: here.
_EXPECTED_INERT: frozenset[str] = frozenset(
    {
        # PROOF, asserted by `test_inversion_adjustment_depth_factor_is_exactly_one_at_the_cap`:
        # `min(r, 1.0)` and `1.0 if x > cap else r` agree at every x. For x < cap
        # both give r = x/cap; for x > cap both give 1.0; and at x == cap both
        # give 1.0, because r = cap/cap = 1.0 exactly. There is no fourth case.
        # The mutation is therefore a genuine no-op, not a weak-spot in the suite,
        # and the only reason to keep it in the table is the record it leaves: it
        # is the boundary an off-by-one WOULD live at, so the day someone changes
        # the comparison operand something must already be watching.
        "MX2d the depth factor applies `>` instead of `>=` at the cap",
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
            "tests/models/test_yield_curve.py",
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
    paths = {SRC, CONFIG}
    originals: dict[Path, str] = {p: p.read_text(encoding="utf-8") for p in paths}

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
    try:
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
    finally:
        for path, text in originals.items():
            path.write_text(text, encoding="utf-8", newline="")

    leftover = _applied_mutations({p: p.read_text(encoding="utf-8") for p in paths})
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
    return 0 if not unexpected else 1


if __name__ == "__main__":
    raise SystemExit(main())
