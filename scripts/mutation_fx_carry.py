"""Mutation sweep for Section 6.7's Module 9 — ``cip_check``, ``carry_score``
and ``dollar_smile_regime``.

**Three functions, one module, one sweep** (D-109, extended at D-110). The
labels are partitioned by function: **``M1``-``M8`` and ``C1`` are
``cip_check``'s** (D-108), **``K1``-``K6`` and ``C2`` are ``carry_score``'s**
(D-109), and **``S1``-``S8`` and ``C3`` are ``dollar_smile_regime``'s** (D-110).
One sweep rather than three because the functions share a file and a config
block, and a further sweep over the same file would multiply the places a
future edit must be mirrored — `mutation_econometrics.py` covers five functions
in one module the same way.

**⚠️ This file is the VICTIM whenever a function is added to ``fx_carry.py``,
not the culprit.** Adding ``carry_score`` made two of the anchors below fail
`check_targets` before the sweep would run:

* **M6a's anchor became AMBIGUOUS (2 occurrences)** — the new input model's
  validator opens with the same ``if not math.isfinite(value):`` line. Fixed by
  widening the anchor with the unique ``for name in (...)`` line above it.
* **M8h's anchor became ABSENT** — it pinned the helper call
  ``_thresholds_are_calibrated()``, which this increment RENAMED to
  ``_cip_bands_are_calibrated()`` so it names the leaf it reads. Fixed by
  following the rename.

Both are D-055/D-060's class and both were caught by the gate rather than by a
mis-reported survivor — which is what the gate is for. **A surviving mutant is a
claim about the tests until proven otherwise; an AMBIGUOUS anchor is a claim
about the SWEEP.**

Every mutation below reverts one decision the implementation makes to a
plausible alternative, and each must be killed. The grouping follows each
function's own structure, because a mutation that does not correspond to a
*decision* is a mutation that cannot teach anything:

* **``cip_check`` — ``M1``-``M8``, ``C1``:**

* **M1** breaks the PARITY IDENTITY — the whole point of the estimator.
  ``M1a`` swaps the two rates in the ratio, ``M1b`` substitutes the linear
  interest-differential approximation for the exact ratio, ``M1c`` multiplies
  where it should divide. Each returns a confident number that is not a parity
  deviation.
* **M2** breaks the ANNUALISATION — the sophistication the specification's stub
  omits. ``M2a`` drops the tenor scaling entirely (the D-106 class: an
  annualised number read as a period number), ``M2b`` inverts it, ``M2c``
  annualises only one leg, ``M2d`` inverts the basis's annualisation, ``M2e``
  reads the wrong rate into the domestic leg.
* **M3** breaks the SIGN — the derivation the module docstring exists to pin.
  ``M3a`` flips the deviation's numerator, ``M3b`` inverts the synthetic-rate
  ratio, ``M3c`` flips the basis's sign, ``M3d`` publishes a fraction where a
  percentage is promised.
* **M4** breaks the QUOTE CONVENTION — the silent sign inversion. ``M4a``
  disables the inversion, ``M4b`` inverts nothing when it should, ``M4c``
  inverts the condition.
* **M5** breaks the BANDS — the reachability of each label. ``M5a``/``M5b``
  collapse the three-way severity into two, ``M5c``/``M5d`` do the same to the
  funding side, ``M5e``/``M5f`` move each boundary from strict to inclusive.
* **M6** breaks the GUARDS — the finiteness, positivity, tenor and period-rate
  refusals.
* **M7** breaks the WARNINGS — each branch, and the noise floor.
* **M8** breaks the PUBLISHED VALUE or the confidence computation.
* **C1** swaps or hardcodes the config accessors and the settings validators.

* **``carry_score`` — ``K1``-``K6``, ``C2``:**
* **K1** breaks the RATIO — the whole point of the estimator. ``K1a`` inverts it,
  ``K1b`` multiplies where it should divide, ``K1c`` subtracts.
* **K2** breaks the FLOOR — the denominator substitution. ``K2a`` disables it,
  ``K2b`` swaps the two branches, ``K2c`` takes the MINIMUM instead of the
  maximum (which inverts the capping direction), ``K2d`` makes the boundary
  inclusive.
* **K3** breaks the DIRECTION — the sign rule and the ``flat`` label.
* **K4** breaks the GUARDS — the finiteness and positive-volatility refusals and
  the settings validator.
* **K5** breaks the WARNING — one branch, and it must fire only when the
  estimand changes.
* **K6** breaks the PUBLISHED VALUE, the unit, the source family or the
  confidence.
* **C2** hardcodes the floor accessor or points the calibration helper at the
  wrong leaf.

* **``dollar_smile_regime`` — ``S1``-``S8``, ``C3``:**
* **S1** breaks the VIX GATE — the left limb's entire definition. ``S1a`` makes
  it inclusive, ``S1b`` reverses it, ``S1c`` makes the limb unreachable, ``S1d``
  conflates the two thresholds.
* **S2** breaks the BOTH-POSITIVE test — the right limb. ``S2a`` weakens the
  conjunction to a disjunction, ``S2b``/``S2c`` drop one input, ``S2d`` makes it
  inclusive (which would give the zero case to the right limb), ``S2e`` reverses
  the signs.
* **S3** breaks the BRANCH ORDER — Section 6.7's most-severe-first rule. Testing
  the growth branch first relabels every high-VIX strong-data reading.
* **S4** breaks the NEUTRAL-INPUT derivation — the two-cause middle label.
* **S5** breaks the finiteness GUARD. ``S5a`` removes it (the probe measured
  ``nan`` → middle and ``+inf`` → left), ``S5b`` guards only one field, ``S5c``
  inverts it.
* **S6** breaks the WARNINGS — each branch, and the right limb's deliberate
  silence.
* **S7** breaks the PUBLISHED VALUE — the label, the flags, the republished
  inputs, the two thresholds, and the base rates.
* **S8** breaks the unit and the confidence.
* **C3** hardcodes or cross-wires the two config accessors, and points the
  calibration helper at one leaf, the other, or a CIP band.

A survivor is one of three things (D-031): a weak test, an **inert** mutation, or
a **broken** mutation. The runner heals before it measures — an interrupted run
leaves the mutated file on disk, and a naive re-run would adopt it as the
baseline (D-035 rule 19).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _sweep_gate import check_targets, format_problems, sweep_lifecycle

SRC = Path("src/macro_engine/models/fx_carry.py")
CONFIG = Path("src/macro_engine/config.py")

# --------------------------------------------------------------------------
# M1: the parity identity.
# --------------------------------------------------------------------------

_IMPLIED_FORWARD = (
    "    implied_forward = spot * (1.0 + i_domestic_period) / (1.0 + i_foreign_period)"
)

# --------------------------------------------------------------------------
# M2: the annualisation.
# --------------------------------------------------------------------------

_PERIOD_SCALE = "    period_scale = inputs.tenor_days / basis_days"
_I_D_PERIOD = "    i_domestic_period = inputs.i_domestic_annualized * period_scale"
_I_F_PERIOD = "    i_foreign_period = inputs.i_foreign_annualized * period_scale"
_BASIS_BP = "    basis_bp_annualized = basis_period / period_scale * 10_000.0"
_BASIS_DAYS_LINE = '_BASIS_DAYS: dict[str, int] = {"actual_360": 360, "actual_365": 365}'

# --------------------------------------------------------------------------
# M3: the sign.
# --------------------------------------------------------------------------

_DEVIATION_FRACTION = "    deviation_fraction = (forward - implied_forward) / implied_forward"
_DEVIATION_PCT = "    deviation_pct = deviation_fraction * 100.0"
_SYNTHETIC = "    synthetic_domestic_period = (forward / spot) * (1.0 + i_foreign_period) - 1.0"
_BASIS_PERIOD = "    basis_period = synthetic_domestic_period - i_domestic_period"

# --------------------------------------------------------------------------
# M4: the quote convention.
# --------------------------------------------------------------------------

_INVERTED_FLAG = '    inverted = inputs.quote == "foreign_per_domestic"'
_INVERT_BRANCH = (
    "    if inverted:\n        spot = 1.0 / inputs.spot\n        forward = 1.0 / inputs.forward"
)

# --------------------------------------------------------------------------
# M5: the bands.
# --------------------------------------------------------------------------

_SEVERITY_EXTREME = "    if magnitude > extreme_pct:"
_SEVERITY_NOTABLE = "    elif magnitude > notable_pct:"
_SIDE_QUIET = "    if magnitude <= notable_pct:"
_SIDE_SIGN = "    elif deviation_pct > 0.0:"

# --------------------------------------------------------------------------
# M6: the guards.
# --------------------------------------------------------------------------

# WIDENED at D-109: the bare `if not math.isfinite(value):` line became
# AMBIGUOUS when `carry_score`'s input model opened its validator with the same
# line. The `for name in (...)` above it is unique to `CIPInputs`, so the anchor
# now resolves to exactly one site. This is the D-055/D-060 remedy — widen the
# anchor with a distinguishing neighbouring line — and NOT a reason to delete
# the mutation.
_FINITE_GUARD = (
    '        for name in ("spot", "forward", "i_domestic_annualized", "i_foreign_annualized"):\n'
    "            value = getattr(self, name)\n"
    "            if not math.isfinite(value):"
)
_POSITIVE_GUARD = "            if value <= 0.0:"
_TENOR_GUARD = "        if self.tenor_days > basis_days:"
_PERIOD_RATE_GUARD = "            if 1.0 + period <= 0.0:"

# --------------------------------------------------------------------------
# M7: the warnings.
# --------------------------------------------------------------------------

_WARN_EXTREME = '    if severity == "extreme":'
_WARN_NOTABLE = '    elif severity == "notable":'

# --------------------------------------------------------------------------
# M8: the published value and the confidence.
# --------------------------------------------------------------------------

_DEVIATION_KEY = '            "deviation_pct": round(deviation_pct, 6),'
_I_D_PERIOD_KEY = '            "i_domestic_period": round(i_domestic_period, 8),'
_BASIS_KEY = '            "domestic_funding_basis_bp_annualized": round(basis_bp_annualized, 4),'
_SEVERITY_KEY = '            "severity": severity,'
_SIDE_KEY = '            "stressed_currency": side,'
_NORMALIZED_KEY = '            "normalized_to": "domestic_per_foreign",'
_INVERTED_KEY = '            "quote_was_inverted": inverted,'
# RENAMED at D-109: the helper this pinned became `_cip_bands_are_calibrated`
# when the module gained a second function with its own threshold and a generic
# `_thresholds_are_calibrated` stopped saying which leaf it read. Following the
# rename here is mandatory — an anchor left pointing at the old name goes ABSENT
# and the gate refuses the whole sweep.
_CIP_HEURISTIC_FLAG = "                is_heuristic_not_calibrated=not _cip_bands_are_calibrated(),"

# --------------------------------------------------------------------------
# K1-K6: carry_score.
# --------------------------------------------------------------------------

_CARRY_RATIO = "    score = differential / denominator"
_CARRY_FLOOR_BINDS = "    floor_binds = realized_vol < volatility_floor"
_CARRY_DENOMINATOR = "    denominator = volatility_floor if floor_binds else realized_vol"
_CARRY_OUTCOME_POSITIVE = (
    '    if rate_differential_annualized > 0.0:\n        return "long_domestic"'
)
_CARRY_OUTCOME_NEGATIVE = (
    '    if rate_differential_annualized < 0.0:\n        return "long_foreign"'
)
_CARRY_FINITE_GUARD = (
    '        for name in ("rate_differential_annualized", "realized_vol_annualized"):\n'
    "            value = getattr(self, name)\n"
    "            if not math.isfinite(value):"
)
_CARRY_VOL_GUARD = "        if self.realized_vol_annualized <= 0.0:"
_CARRY_WARN_EARLY_RETURN = "    if not floor_binds:\n        return []"
_CARRY_SCORE_KEY = '            "score": round(score, 6),'
_CARRY_DENOM_KEY = '            "effective_denominator": round(denominator, 8),'
_CARRY_BINDING_KEY = '            "volatility_floor_binding": floor_binds,'
_CARRY_OUTCOME_KEY = '            "carry_outcome": outcome,'
_CARRY_UNIT = '        unit="dimensionless (annualised carry per unit of annualised volatility)",'
_CARRY_DIRECTION = "        direction=outcome,"
# WIDENED at D-110: the bare `source_family=EvidenceSourceFamily.MARKET_FX,` line
# became AMBIGUOUS when `dollar_smile_regime` — this module's third function —
# declared the same source family. `str.replace` would have rewritten the FIRST
# occurrence, i.e. `carry_score`'s, so the mutation would have landed on the
# wrong function while reporting a kill: the worst possible output, because it
# looks like health (D-048/D-055). The narrowing is `carry_score`'s own
# assumptions block — its second entry names the money-market construction of
# the differential, which `dollar_smile_regime` has no equivalent of.
_CARRY_SOURCE_FAMILY = (
    "`realized_vol_annualized` is the realised volatility of that pair's "
    '"\n            "return series over a window the caller chose, annualised '
    'by the same "\n            "convention as the differential.",\n        ],\n'
    "        source_family=EvidenceSourceFamily.MARKET_FX,"
)
_CARRY_HEURISTIC_FLAG = (
    "                is_heuristic_not_calibrated=not _carry_floor_is_calibrated(),"
)
_CARRY_FLOOR_PROP = "        return float(self.carry_vol_floor.value)"
_CARRY_CALIBRATED_READ = '    return settings.is_calibrated("fx_carry.carry_vol_floor")'
_CARRY_FLOOR_VALIDATOR = "        if self.volatility_floor <= 0.0:"

# --------------------------------------------------------------------------
# C1: the config accessors and validators.
# --------------------------------------------------------------------------

_NOTABLE_READ = "    notable_pct = fx_carry.notable_threshold_pct"
_EXTREME_READ = "    extreme_pct = fx_carry.extreme_threshold_pct"
_CALIBRATED_READ = '    return settings.is_calibrated("fx_carry.notable_deviation_pct")'
_NOTABLE_PROP = "        return float(self.notable_deviation_pct.value)"
_EXTREME_PROP = "        return float(self.extreme_deviation_pct.value)"
_ORDER_VALIDATOR = "        if extreme <= notable:"
_POSITIVE_VALIDATOR = "        if notable <= 0.0:"

# --------------------------------------------------------------------------
# S1-S8: dollar_smile_regime (this module's THIRD function, D-110).
#
# The labels continue the scheme rather than restarting: `M*` belongs to
# `cip_check`, `K*` to `carry_score`, so `dollar_smile_regime` takes `S*` (for
# **S**mile) and the config side takes `C3`. A re-used prefix would make two
# different mutants share a label, and the kill log is read by a human who has
# no other way to tell them apart.
# --------------------------------------------------------------------------

# The gate and the both-positive test. Both are byte-verbatim, single-occurrence
# lines — verified before being written here, because a branch anchor that
# resolves to zero sites makes the mutant a `pattern-not-found` SURVIVOR that
# looks like a weak test (D-031).
_DS_VIX_GATE = "    if vix_level > vix_threshold:"
_DS_BOTH_POSITIVE = (
    "    if us_growth_surprise > sign_boundary and us_vs_row_rate_diff > sign_boundary:"
)
_DS_NEUTRAL_RETURN = "    return us_growth_surprise == 0.0 or us_vs_row_rate_diff == 0.0"

# The finiteness guard. WIDENED past the bare `if not math.isfinite(value):`
# line for the same reason M6a and K4a are widened: three input models in this
# module open a validator with that line, so the bare line is AMBIGUOUS (3
# occurrences). The `for name in (...)` line above it is unique to
# `DollarSmileInputs`.
_DS_FINITE_GUARD = (
    '        for name in ("vix_level", "us_growth_surprise", "us_vs_row_rate_diff"):\n'
    "            value = getattr(self, name)\n"
    "            if not math.isfinite(value):"
)

# The warnings. `if side == "left":\n        warnings.append(` is unique; so is
# the middle-branch guard, which carries `and _dollar_smile_is_neutral(...)`.
_DS_WARN_LEFT = '    if side == "left":\n        warnings.append('
_DS_WARN_MIDDLE = '    elif side == "middle" and _dollar_smile_is_neutral(us_growth_surprise, us_vs_row_rate_diff):'

# The published value and the contract.
_DS_SIDE_KEY = '            "side": side,'
_DS_NEUTRAL_KEY = '            "is_neutral_input": is_neutral,'
_DS_VIX_KEY = '            "vix_level": round(vix_level, 6),'
_DS_GROWTH_KEY = '            "us_growth_surprise": round(growth, 6),'
_DS_RATEDIFF_KEY = '            "us_vs_row_rate_diff": round(rate_diff, 6),'
_DS_VIX_ABOVE_KEY = '            "vix_above_threshold": vix_above,'
_DS_GROWTH_ABOVE_KEY = '            "growth_above_boundary": growth_above,'
_DS_RATE_ABOVE_KEY = '            "rate_above_boundary": rate_above,'
_DS_VIX_THRESH_KEY = '            "vix_threshold": vix_threshold,'
_DS_SIGN_BOUNDARY_KEY = '            "sign_boundary": sign_boundary,'
_DS_UNIT = "        unit=\"categorical (dollar smile limb: 'left' | 'right' | 'middle')\","
_DS_HEURISTIC_FLAG = (
    "                is_heuristic_not_calibrated=not _dollar_smile_thresholds_are_calibrated(),"
)
# The base rates. A mutated share must move the published limitation text.
_DS_BASE_RATES = '    "left": 1750 / 3025,\n    "right": 204 / 3025,\n    "middle": 1071 / 3025,'

# The config side.
_DS_CALIBRATED_READ = (
    '    return settings.is_calibrated("fx_carry.dollar_smile_vix_threshold") and settings.is_calibrated(\n'
    '        "fx_carry.dollar_smile_sign_boundary"\n'
    "    )"
)
_DS_VIX_PROP = "        return float(self.dollar_smile_vix_threshold.value)"
_DS_BOUNDARY_PROP = "        return float(self.dollar_smile_sign_boundary.value)"
_DS_VIX_VALIDATOR = "        if self.dollar_smile_vix_level <= 0.0:"


_MUTATIONS: list[tuple[str, Path, str, str]] = [
    # -- canary (CONTROL) -------------------------------------------------
    # NOT a revert of a project decision: a mutation CERTAIN to be caught, so
    # the sweep can REFUSE TO CERTIFY when it survives. A sweep whose anchors
    # resolve but whose selection no longer reaches the mutated module reports
    # every mutant as killed (D-051). The anchor is the module's FIRST
    # STATEMENT — the future import — so it does not churn the way `__all__`
    # does (O-119/O-126: an `__all__` canary was broken by an export edit and
    # reported as a LEFTOVER).
    (
        "CANARY1 the module literal is replaced with a syntax error (CONTROL)",
        SRC,
        "from __future__ import annotations",
        "__CANARY__ = <<<SYNTAX ERROR>>>",
    ),
    # --- M1: the parity identity -----------------------------------------
    (
        "M1a the two rates are swapped in the parity ratio",
        SRC,
        _IMPLIED_FORWARD,
        "    implied_forward = spot * (1.0 + i_foreign_period) / (1.0 + i_domestic_period)",
    ),
    (
        "M1b the linear interest-differential approximation replaces the ratio",
        SRC,
        _IMPLIED_FORWARD,
        "    implied_forward = spot * (1.0 + i_domestic_period - i_foreign_period)",
    ),
    (
        "M1c the parity ratio is multiplied instead of divided",
        SRC,
        _IMPLIED_FORWARD,
        "    implied_forward = spot / ((1.0 + i_domestic_period) / (1.0 + i_foreign_period))",
    ),
    # --- M2: the annualisation -------------------------------------------
    (
        "M2a the tenor scaling dropped (annualised rates read as period rates)",
        SRC,
        _PERIOD_SCALE,
        "    period_scale = 1.0",
    ),
    (
        "M2b the tenor scaling inverted",
        SRC,
        _PERIOD_SCALE,
        "    period_scale = basis_days / inputs.tenor_days",
    ),
    (
        "M2c only the domestic leg is annualised",
        SRC,
        _I_F_PERIOD,
        "    i_foreign_period = inputs.i_foreign_annualized",
    ),
    (
        "M2d the domestic leg reads the foreign rate",
        SRC,
        _I_D_PERIOD,
        "    i_domestic_period = inputs.i_foreign_annualized * period_scale",
    ),
    (
        "M2e the basis is annualised by multiplying instead of dividing",
        SRC,
        _BASIS_BP,
        "    basis_bp_annualized = basis_period * period_scale * 10_000.0",
    ),
    (
        "M2f the ACT/365 year is given 360 days",
        SRC,
        _BASIS_DAYS_LINE,
        '_BASIS_DAYS: dict[str, int] = {"actual_360": 360, "actual_365": 360}',
    ),
    # --- M3: the sign ----------------------------------------------------
    (
        "M3a the deviation's numerator is reversed (sign flipped)",
        SRC,
        _DEVIATION_FRACTION,
        "    deviation_fraction = (implied_forward - forward) / implied_forward",
    ),
    (
        "M3b the synthetic-rate ratio is inverted",
        SRC,
        _SYNTHETIC,
        "    synthetic_domestic_period = (spot / forward) * (1.0 + i_foreign_period) - 1.0",
    ),
    (
        "M3c the basis's sign is flipped",
        SRC,
        _BASIS_PERIOD,
        "    basis_period = i_domestic_period - synthetic_domestic_period",
    ),
    (
        "M3d the deviation is published as a fraction, not a percentage",
        SRC,
        _DEVIATION_PCT,
        "    deviation_pct = deviation_fraction",
    ),
    # --- M4: the quote convention ----------------------------------------
    (
        "M4a the inversion is disabled (every quote read as domestic-per-foreign)",
        SRC,
        _INVERTED_FLAG,
        "    inverted = False",
    ),
    (
        "M4b the branch inverts nothing (the flag is read but not acted on)",
        SRC,
        _INVERT_BRANCH,
        "    if inverted:\n        spot = inputs.spot\n        forward = inputs.forward",
    ),
    (
        "M4c the inversion condition is inverted",
        SRC,
        _INVERTED_FLAG,
        '    inverted = inputs.quote == "domestic_per_foreign"',
    ),
    # --- M5: the bands ---------------------------------------------------
    (
        "M5a the extreme band collapses onto the notable one",
        SRC,
        _SEVERITY_EXTREME,
        "    if magnitude > notable_pct:",
    ),
    (
        "M5b the notable band collapses onto the extreme one",
        SRC,
        _SEVERITY_NOTABLE,
        "    elif magnitude > extreme_pct:",
    ),
    (
        "M5c the quiet side-band extends to the extreme threshold",
        SRC,
        _SIDE_QUIET,
        "    if magnitude <= extreme_pct:",
    ),
    (
        "M5d the funding side's sign rule is reversed",
        SRC,
        _SIDE_SIGN,
        "    elif deviation_pct < 0.0:",
    ),
    (
        "M5e the extreme boundary becomes inclusive (>= instead of >)",
        SRC,
        _SEVERITY_EXTREME,
        "    if magnitude >= extreme_pct:",
    ),
    (
        "M5f the notable boundary becomes inclusive (>= instead of >)",
        SRC,
        _SEVERITY_NOTABLE,
        "    elif magnitude >= notable_pct:",
    ),
    # --- M6: the guards --------------------------------------------------
    (
        "M6a the finiteness guard removed (nan reaches the arithmetic)",
        SRC,
        _FINITE_GUARD,
        "            if False:",
    ),
    (
        "M6b a zero exchange rate is admitted",
        SRC,
        _POSITIVE_GUARD,
        "            if value < 0.0:",
    ),
    (
        "M6c the tenor guard removed (simple interest past one money-market year)",
        SRC,
        _TENOR_GUARD,
        "        if False:",
    ),
    (
        "M6d the period-rate guard is unreachable",
        SRC,
        _PERIOD_RATE_GUARD,
        "            if 1.0 + period <= -1.0:",
    ),
    # --- M7: the warnings ------------------------------------------------
    (
        "M7a the extreme warning removed",
        SRC,
        _WARN_EXTREME,
        "    if False:",
    ),
    (
        "M7b the notable warning removed",
        SRC,
        _WARN_NOTABLE,
        "    elif False:",
    ),
    # --- M8: the published value and the confidence ----------------------
    (
        "M8a the deviation is published at 2dp (the hand-computed digits are lost)",
        SRC,
        _DEVIATION_KEY,
        '            "deviation_pct": round(deviation_pct, 2),',
    ),
    (
        "M8b the domestic period rate publishes the foreign one",
        SRC,
        _I_D_PERIOD_KEY,
        '            "i_domestic_period": round(i_foreign_period, 8),',
    ),
    (
        "M8c the basis is published un-annualised (the identity breaks by the tenor)",
        SRC,
        _BASIS_KEY,
        '            "domestic_funding_basis_bp_annualized": round(basis_period, 4),',
    ),
    (
        "M8d the published severity is a constant",
        SRC,
        _SEVERITY_KEY,
        '            "severity": "none",',
    ),
    (
        "M8e the published funding side is a constant",
        SRC,
        _SIDE_KEY,
        '            "stressed_currency": "none",',
    ),
    (
        "M8f the published normalization target is the wrong space",
        SRC,
        _NORMALIZED_KEY,
        '            "normalized_to": "foreign_per_domestic",',
    ),
    (
        "M8g the inversion flag is published as a constant",
        SRC,
        _INVERTED_KEY,
        '            "quote_was_inverted": False,',
    ),
    (
        "M8h the confidence drops the heuristic penalty",
        SRC,
        _CIP_HEURISTIC_FLAG,
        "                is_heuristic_not_calibrated=False,",
    ),
    # --- C1: the config accessors and validators -------------------------
    (
        "C1a the notable band is a hardcoded literal",
        SRC,
        _NOTABLE_READ,
        "    notable_pct = 0.1",
    ),
    (
        "C1b the extreme band is a hardcoded literal",
        SRC,
        _EXTREME_READ,
        "    extreme_pct = 0.5",
    ),
    (
        "C1c the notable accessor returns the EXTREME leaf",
        CONFIG,
        _NOTABLE_PROP,
        "        return float(self.extreme_deviation_pct.value)",
    ),
    (
        "C1d the extreme accessor returns the NOTABLE leaf",
        CONFIG,
        _EXTREME_PROP,
        "        return float(self.notable_deviation_pct.value)",
    ),
    (
        "C1e the calibration helper reports calibrated unconditionally",
        SRC,
        _CALIBRATED_READ,
        "    return True",
    ),
    (
        "C1f the calibration helper reads the EXTREME leaf",
        SRC,
        _CALIBRATED_READ,
        '    return settings.is_calibrated("fx_carry.extreme_deviation_pct")',
    ),
    (
        "C1g the band-ordering validator removed",
        CONFIG,
        _ORDER_VALIDATOR,
        "        if False:",
    ),
    (
        "C1h the positive-band validator removed",
        CONFIG,
        _POSITIVE_VALIDATOR,
        "        if False:",
    ),
    # --- K1: the ratio (carry_score's reason to exist) --------------------
    (
        "K1a the ratio is inverted",
        SRC,
        _CARRY_RATIO,
        "    score = denominator / differential",
    ),
    (
        "K1b the differential is multiplied by the denominator",
        SRC,
        _CARRY_RATIO,
        "    score = differential * denominator",
    ),
    (
        "K1c the differential has the denominator subtracted from it",
        SRC,
        _CARRY_RATIO,
        "    score = differential - denominator",
    ),
    # --- K2: the floor ----------------------------------------------------
    (
        "K2a the floor is disabled (the denominator is always the realised vol)",
        SRC,
        _CARRY_FLOOR_BINDS,
        "    floor_binds = False",
    ),
    (
        "K2b the two denominator branches are swapped",
        SRC,
        _CARRY_DENOMINATOR,
        "    denominator = realized_vol if floor_binds else volatility_floor",
    ),
    (
        "K2c the MINIMUM is taken instead of the maximum (capping direction inverted)",
        SRC,
        _CARRY_DENOMINATOR,
        "    denominator = min(realized_vol, volatility_floor)",
    ),
    (
        "K2d the floor boundary becomes inclusive",
        SRC,
        _CARRY_FLOOR_BINDS,
        "    floor_binds = realized_vol <= volatility_floor",
    ),
    # --- K3: the direction ------------------------------------------------
    (
        "K3a a positive differential is labelled long_foreign",
        SRC,
        _CARRY_OUTCOME_POSITIVE,
        '    if rate_differential_annualized > 0.0:\n        return "long_foreign"',
    ),
    (
        "K3b a negative differential is labelled long_domestic",
        SRC,
        _CARRY_OUTCOME_NEGATIVE,
        '    if rate_differential_annualized < 0.0:\n        return "long_domestic"',
    ),
    (
        "K3c the flat case is absorbed into long_foreign (its label becomes unreachable)",
        SRC,
        _CARRY_OUTCOME_NEGATIVE,
        '    if rate_differential_annualized <= 0.0:\n        return "long_foreign"',
    ),
    # --- K4: the guards ---------------------------------------------------
    (
        "K4a the carry finiteness guard removed",
        SRC,
        _CARRY_FINITE_GUARD,
        '        for name in ("rate_differential_annualized", "realized_vol_annualized"):\n'
        "            value = getattr(self, name)\n"
        "            if False:",
    ),
    (
        "K4b a zero volatility is admitted",
        SRC,
        _CARRY_VOL_GUARD,
        "        if self.realized_vol_annualized < 0.0:",
    ),
    (
        "K4c the settings' positive-floor validator removed",
        CONFIG,
        _CARRY_FLOOR_VALIDATOR,
        "        if False:",
    ),
    # --- K5: the warning --------------------------------------------------
    (
        "K5a the floor warning fires on every call (the early return removed)",
        SRC,
        _CARRY_WARN_EARLY_RETURN,
        "    if False:\n        return []",
    ),
    (
        "K5b the floor warning never fires",
        SRC,
        _CARRY_WARN_EARLY_RETURN,
        "    if True:\n        return []",
    ),
    # --- K6: the published value, the unit, the family, the confidence ----
    (
        "K6a the published score ignores the floor",
        SRC,
        _CARRY_SCORE_KEY,
        '            "score": round(differential / realized_vol, 6),',
    ),
    (
        "K6b the published denominator is the realised vol, floor or not",
        SRC,
        _CARRY_DENOM_KEY,
        '            "effective_denominator": round(realized_vol, 8),',
    ),
    (
        "K6c the floor-binding flag is published as a constant",
        SRC,
        _CARRY_BINDING_KEY,
        '            "volatility_floor_binding": False,',
    ),
    (
        "K6d the published outcome is a constant",
        SRC,
        _CARRY_OUTCOME_KEY,
        '            "carry_outcome": "flat",',
    ),
    (
        "K6e the unit is misdeclared as percent",
        SRC,
        _CARRY_UNIT,
        '        unit="percent",',
    ),
    (
        "K6f the direction field is a constant",
        SRC,
        _CARRY_DIRECTION,
        '        direction="flat",',
    ),
    (
        "K6g the source family is dropped",
        SRC,
        _CARRY_SOURCE_FAMILY,
        "        source_family=None,",
    ),
    (
        "K6h the confidence drops the heuristic penalty",
        SRC,
        _CARRY_HEURISTIC_FLAG,
        "                is_heuristic_not_calibrated=False,",
    ),
    # --- C2: the carry config accessors -----------------------------------
    (
        "C2a the floor accessor is a hardcoded literal",
        CONFIG,
        _CARRY_FLOOR_PROP,
        "        return 0.1",
    ),
    (
        "C2b the floor accessor returns a CIP band instead",
        CONFIG,
        _CARRY_FLOOR_PROP,
        "        return float(self.notable_deviation_pct.value)",
    ),
    (
        "C2c the calibration helper reads a CIP band instead of the floor",
        SRC,
        _CARRY_CALIBRATED_READ,
        '    return settings.is_calibrated("fx_carry.notable_deviation_pct")',
    ),
    # --- S1: the VIX gate ------------------------------------------------
    # The gate is the left limb's whole definition. Each of these produces a
    # confident label for a real input, which is what makes a classifier's
    # branch a decision rather than an implementation detail.
    (
        "S1a the gate becomes inclusive (a VIX exactly ON 25 is classified left)",
        SRC,
        _DS_VIX_GATE,
        "    if vix_level >= vix_threshold:",
    ),
    (
        "S1b the gate's inequality is reversed (high VIX becomes the middle limb)",
        SRC,
        _DS_VIX_GATE,
        "    if vix_level < vix_threshold:",
    ),
    (
        "S1c the left limb is unreachable (the gate can never fire)",
        SRC,
        _DS_VIX_GATE,
        "    if False:",
    ),
    (
        "S1d the VIX gate reads the sign boundary (the two thresholds are conflated)",
        SRC,
        _DS_VIX_GATE,
        "    if vix_level > sign_boundary:",
    ),
    # --- S2: the both-positive test (the right limb) ----------------------
    (
        "S2a the conjunction becomes a disjunction (either input alone suffices)",
        SRC,
        _DS_BOTH_POSITIVE,
        "    if us_growth_surprise > sign_boundary or us_vs_row_rate_diff > sign_boundary:",
    ),
    (
        "S2b only the growth input is tested (the rate sign is ignored)",
        SRC,
        _DS_BOTH_POSITIVE,
        "    if us_growth_surprise > sign_boundary:",
    ),
    (
        "S2c only the rate input is tested (the growth sign is ignored)",
        SRC,
        _DS_BOTH_POSITIVE,
        "    if us_vs_row_rate_diff > sign_boundary:",
    ),
    (
        "S2d the boundaries become inclusive (a signed input AT zero reaches right)",
        SRC,
        _DS_BOTH_POSITIVE,
        "    if us_growth_surprise >= sign_boundary and us_vs_row_rate_diff >= sign_boundary:",
    ),
    (
        "S2e the BOTH inputs reverse sign (negative surprises reach the right limb)",
        SRC,
        _DS_BOTH_POSITIVE,
        "    if us_growth_surprise < sign_boundary and us_vs_row_rate_diff < sign_boundary:",
    ),
    # --- S3: the branch ORDER (most-severe-first) ------------------------
    # Section 6.7 requires the crisis reading to win when both gates would fire.
    # Swapping the two tests relabels every high-VIX strong-data reading from
    # left to right — the exact silent relabelling the docstring warns about.
    (
        "S3a the left gate is tested SECOND (a high VIX with strong data becomes right)",
        SRC,
        '    if vix_level > vix_threshold:\n        return "left"\n'
        "    if us_growth_surprise > sign_boundary and us_vs_row_rate_diff > sign_boundary:\n"
        '        return "right"',
        "    if us_growth_surprise > sign_boundary and us_vs_row_rate_diff > sign_boundary:\n"
        '        return "right"\n'
        '    if vix_level > vix_threshold:\n        return "left"',
    ),
    # --- S4: the neutral-input derivation --------------------------------
    (
        "S4a the neutral test uses AND (it can never fire, since a both-zero input"
        " is not both-positive either) — collapses a two-cause label into one",
        SRC,
        _DS_NEUTRAL_RETURN,
        "    return us_growth_surprise == 0.0 and us_vs_row_rate_diff == 0.0",
    ),
    (
        "S4b the neutral test reads the VIX instead of the signed inputs",
        SRC,
        _DS_NEUTRAL_RETURN,
        "    return vix_level == 0.0",
    ),
    (
        "S4c the neutral test is disabled (the middle limb's neutral cause is lost)",
        SRC,
        _DS_NEUTRAL_RETURN,
        "    return False",
    ),
    (
        "S4d the neutral test is unconditional (every middle label claims neutrality)",
        SRC,
        _DS_NEUTRAL_RETURN,
        "    return True",
    ),
    (
        "S4e the neutral test uses a tolerance band instead of exact zero",
        SRC,
        _DS_NEUTRAL_RETURN,
        "    return abs(us_growth_surprise) < 1e-6 or abs(us_vs_row_rate_diff) < 1e-6",
    ),
    # --- S5: the guards --------------------------------------------------
    (
        "S5a the finiteness guard removed (nan reaches the label, per the probe)",
        SRC,
        _DS_FINITE_GUARD,
        '        for name in ("vix_level", "us_growth_surprise", "us_vs_row_rate_diff"):\n'
        "            value = getattr(self, name)\n"
        "            if False:",
    ),
    (
        "S5b the finiteness guard tests only the VIX (two fields unguarded)",
        SRC,
        _DS_FINITE_GUARD,
        '        for name in ("vix_level",):\n'
        "            value = getattr(self, name)\n"
        "            if not math.isfinite(value):",
    ),
    (
        "S5c the finiteness guard is inverted (every finite input is refused)",
        SRC,
        _DS_FINITE_GUARD,
        '        for name in ("vix_level", "us_growth_surprise", "us_vs_row_rate_diff"):\n'
        "            value = getattr(self, name)\n"
        "            if math.isfinite(value):",
    ),
    # --- S6: the warnings ------------------------------------------------
    (
        "S6a the left-limb warning never fires",
        SRC,
        _DS_WARN_LEFT,
        "    if False:\n        warnings.append(",
    ),
    (
        "S6b the middle-neutral warning never fires",
        SRC,
        _DS_WARN_MIDDLE,
        '    elif side == "middle":',
    ),
    (
        "S6c the middle warning fires on EVERY middle label (neutrality unstated)",
        SRC,
        _DS_WARN_MIDDLE,
        '    elif side == "middle" and not _dollar_smile_is_neutral(us_growth_surprise, us_vs_row_rate_diff):',
    ),
    (
        "S6d the right limb emits noise (its own name is its reason, so this is"
        " a warning that says nothing)",
        SRC,
        '    if side == "left":\n        warnings.append(',
        '    if side == "left" or side == "right":\n        warnings.append(',
    ),
    # --- S7: the published value ------------------------------------------
    (
        "S7a the published side is a constant",
        SRC,
        _DS_SIDE_KEY,
        '            "side": "middle",',
    ),
    (
        "S7b the neutral flag is published as a constant",
        SRC,
        _DS_NEUTRAL_KEY,
        '            "is_neutral_input": False,',
    ),
    (
        "S7c the published VIX is the sign boundary (inputs conflated in the output)",
        SRC,
        _DS_VIX_KEY,
        '            "vix_level": round(sign_boundary, 6),',
    ),
    (
        "S7d the published growth surprise is the rate differential",
        SRC,
        _DS_GROWTH_KEY,
        '            "us_growth_surprise": round(rate_diff, 6),',
    ),
    (
        "S7e the published rate differential is the growth surprise",
        SRC,
        _DS_RATEDIFF_KEY,
        '            "us_vs_row_rate_diff": round(growth, 6),',
    ),
    (
        "S7f the published vix_above flag is the rate comparison",
        SRC,
        _DS_VIX_ABOVE_KEY,
        '            "vix_above_threshold": rate_above,',
    ),
    (
        "S7g the published growth_above flag is the rate comparison",
        SRC,
        _DS_GROWTH_ABOVE_KEY,
        '            "growth_above_boundary": rate_above,',
    ),
    (
        "S7h the published rate_above flag is the growth comparison",
        SRC,
        _DS_RATE_ABOVE_KEY,
        '            "rate_above_boundary": growth_above,',
    ),
    (
        "S7i the published vix_threshold is the sign boundary (label not re-derivable)",
        SRC,
        _DS_VIX_THRESH_KEY,
        '            "vix_threshold": sign_boundary,',
    ),
    (
        "S7j the published sign_boundary is the VIX gate (label not re-derivable)",
        SRC,
        _DS_SIGN_BOUNDARY_KEY,
        '            "sign_boundary": vix_threshold,',
    ),
    (
        "S7k the published base rates are transposed (left and right swapped)",
        SRC,
        _DS_BASE_RATES,
        '    "left": 204 / 3025,\n    "right": 1750 / 3025,\n    "middle": 1071 / 3025,',
    ),
    # --- S8: the contract and the confidence ------------------------------
    (
        "S8a the unit is misdeclared as a percent",
        SRC,
        _DS_UNIT,
        '        unit="percent",',
    ),
    (
        "S8b the confidence drops the heuristic penalty",
        SRC,
        _DS_HEURISTIC_FLAG,
        "                is_heuristic_not_calibrated=False,",
    ),
    # --- C3: the dollar-smile config accessors and validator --------------
    (
        "C3a the VIX-gate accessor is a hardcoded literal",
        CONFIG,
        _DS_VIX_PROP,
        "        return 25.0",
    ),
    (
        "C3b the VIX-gate accessor returns the sign boundary leaf instead",
        CONFIG,
        _DS_VIX_PROP,
        "        return float(self.dollar_smile_sign_boundary.value)",
    ),
    (
        "C3c the sign-boundary accessor returns the VIX gate leaf instead",
        CONFIG,
        _DS_BOUNDARY_PROP,
        "        return float(self.dollar_smile_vix_threshold.value)",
    ),
    (
        "C3d the calibration helper reports calibrated unconditionally",
        SRC,
        _DS_CALIBRATED_READ,
        "    return True",
    ),
    (
        "C3e the calibration helper reads ONLY the VIX gate (the sign boundary's"
        " placeholder stops costing confidence)",
        SRC,
        _DS_CALIBRATED_READ,
        '    return settings.is_calibrated("fx_carry.dollar_smile_vix_threshold")',
    ),
    (
        "C3f the calibration helper reads ONLY the sign boundary",
        SRC,
        _DS_CALIBRATED_READ,
        '    return settings.is_calibrated("fx_carry.dollar_smile_sign_boundary")',
    ),
    (
        "C3g the calibration helper reads a CIP band instead",
        SRC,
        _DS_CALIBRATED_READ,
        '    return settings.is_calibrated("fx_carry.notable_deviation_pct")',
    ),
    (
        "C3h the non-positive VIX-gate validator removed",
        CONFIG,
        _DS_VIX_VALIDATOR,
        "        if False:",
    ),
]


def run_tests() -> bool:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/models/test_cip_check.py",
            "tests/models/test_carry_score.py",
            "tests/models/test_dollar_smile_regime.py",
            "tests/test_infrastructure.py",
            "-q",
            "--no-header",
            # `-x` is D-057's rule, not a preference: a kill is a kill, the
            # first failing test is sufficient evidence, and an interrupted
            # long run on win32 leaves every mutant applied so far on disk
            # (D-082).
            "-x",
            "-m",
            "not live",
        ],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def main() -> int:
    # The whole interrupt defence in one call (O-103): heal any sidecar a killed
    # previous run left behind, write the pristine text to a sidecar BEFORE the
    # first mutation, and consume it on the way out. On win32 no Python signal
    # handler runs for SIGTERM/SIGINT, so the sidecar — not a handler — is the
    # defence that actually has reach here.
    with sweep_lifecycle([SRC, CONFIG]) as originals:
        return _run_sweep(originals)


def _run_sweep(originals: dict[Path, str]) -> int:
    problems = check_targets(originals, _MUTATIONS)
    print(f"check_targets: {len(_MUTATIONS)} mutations, {len(problems)} problem(s)", flush=True)
    if problems:
        print(format_problems(problems))
        print()
        print("REFUSING TO RUN: fix the anchors above first. A sweep that cannot")
        print("prove it mutates the site it names certifies nothing.")
        return 4

    survivors: list[tuple[str, str]] = []
    try:
        for name, target, old, new in _MUTATIONS:
            pristine = originals[target]
            if old not in pristine:
                print(f"PATTERN MISSING   {name}  [{target.name}]", flush=True)
                survivors.append((name, "pattern-not-found"))
                continue
            target.write_text(pristine.replace(old, new, 1), encoding="utf-8", newline="")
            caught = not run_tests()
            target.write_text(pristine, encoding="utf-8", newline="")
            print(f"{'KILLED' if caught else 'SURVIVED':17} {name}", flush=True)
            if not caught:
                survivors.append((name, "survived"))
    finally:
        # Belt and braces: an exception mid-mutation must never leave the tree
        # mutated. A SIGTERM on win32 still can — no handler and no ``finally``
        # gets a turn — which is the case the sidecar covers, not this.
        for path, text in originals.items():
            path.write_text(text, encoding="utf-8", newline="")

    print()
    print("=" * 74)
    total = len(_MUTATIONS)
    killed = total - len(survivors)
    print(
        f"MUTATION SWEEP — fx_carry (cip_check + carry_score + dollar_smile_regime): "
        f"{killed}/{total} killed",
        flush=True,
    )
    print("=" * 74)
    if survivors:
        print("SURVIVORS (each is a weak test, an inert mutation, or a broken one):")
        for name, reason in survivors:
            print(f"  [{reason}] {name}")
    # O-72's canary gate. A canary that SURVIVES means the sweep ran but tested
    # nothing: its selection no longer reaches the mutated module, so every
    # "killed" above is a statement about the harness rather than the suite
    # (D-051). CANARY1 is REQUIRED to be killed, not tolerated as a survivor.
    if any(name.startswith("CANARY1 ") for name, _ in survivors):
        print()
        print("REFUSING TO CERTIFY: the honesty canary SURVIVED.")
        print("  !! CANARY1 -- the test selection no longer reaches the mutated")
        print("     module, so no kill above is evidence about the suite (O-72).")
        return 3
    if survivors:
        return 1
    print("  every mutation killed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
