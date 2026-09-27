"""Mutation sweep for Section 6.8 — ``oil_balance_signal`` (Module 10) — the
model, the new commodity client, and its config block.

**One function, two new modules, one client extension, one sweep** (the
D-118/D-119 shape). The labels are partitioned by FILE:

* **``M1``-``M9``** are ``models/commodities.py``'s — the model's own decisions
  plus its input contract.
* **``C1``-``C8``** are ``data_layer/commodities_client.py``'s — the symbol
  selection, the projection-tail clip, the seasonal baseline, and the value
  guards.
* **``G1``-``G4``** are ``src/macro_engine/config.py``'s ``OilBalanceSettings`` —
  the three accessors and the three validators.

⚠️ **This sweep is NOT an extension of ``mutation_em_vulnerability.py``.** The
model module and the client module are new, and the config class is new, so the
labels are independent.

⚠️ **D-119's LESSON APPLIED AT AUTHORING TIME — THE AMBIGUOUS ANCHORS WERE
WIDENED, NOT DISCOVERED LATE.** Adding ``OilBalanceSettings`` to ``config.py``
creates a THIRD byte-identical copy of two guard strings that already existed in
``InterventionSettings`` and ``EMVulnerabilitySettings``:

* ``        if not 0.0 <= self.reliability_value <= 1.0:`` now appears **3x**;
* ``        return float(self.reliability_cap.value)`` now appears **3x**.

Both are WIDENED below with a distinguishing neighbour measured at exactly one
occurrence (``G1``/``G4`` and ``G2``), because ``str.replace(old, new, 1)``
rewrites the FIRST site and a wrong-site mutation manufactures a false survivor
(D-048). The same applies to the two ``if when > as_of:`` sites in the client
(``C3``/``C4``) — each is widened with its own body line.

**Every ``old`` string below was measured with ``str.count()`` against the file
it targets before being written**, and the count is recorded in a comment. The
``_check_targets_only`` mode re-verifies it on demand.

What the grouping means
-----------------------
* **``M1``** breaks the SIGN — Section 6.8's ``tightness = -deviation``.
* **``M2``** breaks the DIRECTION label.
* **``M3``** breaks the ROUNDING.
* **``M4``** breaks the CONFIDENCE product and its inputs.
* **``M5``** breaks the REFUSAL.
* **``M6``** breaks the RESULT CONTRACT (unit, family).
* **``M7``** breaks the DISCLOSURE (a supplied leg must say so).
* **``M8``** breaks the INPUT GUARDS (the non-finite refusal).
* **``M9``** breaks the VALUE dict (each of the three published keys).
* **``C1``/``C2``** break the SYMBOL SELECTION — by name, on both routes.
* **``C3``/``C4``** break the PROJECTION-TAIL CLIP — the D-116 vintage guard.
* **``C5``** breaks the WEEK-CHANGE.
* **``C6``** breaks the "< 2 observations" refusal.
* **``C7``** breaks the SEASONAL BASELINE (the year window and the none-return).
* **``C8``** breaks the NULL-VALUE refusal.
* **``G1``-``G4``** break the CONFIG accessors and validators.

A survivor is one of three things (D-031): a weak test, an **inert** mutation, or
a **broken** mutation. The runner heals before it measures (D-035 rule 19).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _sweep_gate import (
    check_only_requested,
    check_targets,
    format_problems,
    sweep_lifecycle,
)

MODEL = Path("src/macro_engine/models/commodities.py")
CLIENT = Path("src/macro_engine/data_layer/commodities_client.py")
CONFIG = Path("src/macro_engine/config.py")

# --------------------------------------------------------------------------
# M1: the sign (Section 6.8's arithmetic).  measured: 1
# --------------------------------------------------------------------------

_SIGN = "    tightness = -deviation  # draw = tightening (Section 6.8)"

# --------------------------------------------------------------------------
# M2: the direction label.  measured: 1
# --------------------------------------------------------------------------

_DIRECTION = '        direction="tightening" if tightness > 0 else "loosening",'

# --------------------------------------------------------------------------
# M3: the rounding.  measured: 1
# --------------------------------------------------------------------------

_ROUND = "    rounded_tightness = round(tightness, decimals)"

# --------------------------------------------------------------------------
# M4: the confidence product and its inputs.  measured: 1 each
# --------------------------------------------------------------------------

_CONF_PRODUCT = "    confidence = computed * oil.reliability_value"
# ⚠️ WIDENED at D-121: `            data_quality_flags_present=fetched_legs < 2,`
#     is byte-identical in the gold model too (measured 2). The distinguishing
#     neighbour is the OIL-only next line, which uses `fetched_legs` as the
#     independence count; the gold model uses `independent_providers`. Widened
#     form measured: 1.
_CONF_DQ = (
    "            data_quality_flags_present=fetched_legs < 2,\n"
    "            is_heuristic_not_calibrated=not oil.reliability_cap_is_calibrated,\n"
    "            source_independence_count=fetched_legs,"
)
_CONF_IND = "            source_independence_count=fetched_legs,"

# --------------------------------------------------------------------------
# M5: the refusal.  measured: 1
# --------------------------------------------------------------------------

# ⚠️ D-122 WIDENED THIS. `    if missing:` now occurs at TWO sites in the model
#    (the oil refusal and the metals refusal). Widened with the OIL block's own
#    error-message prefix, which names `oil_balance_signal`: 1 (asserted by
#    `_check_targets_only`). A bare anchor here would have rewritten the METALS
#    refusal instead, leaving the oil refusal alive and manufacturing a false
#    survivor — exactly the D-119 O-145 class, in the opposite direction.
_MISSING_REFUSAL = (
    "    if missing:\n"
    "        raise ValueError(\n"
    '            f"oil_balance_signal cannot compute the transmitted tightness: no "'
)

# --------------------------------------------------------------------------
# M6: the published contract.  measured: 1 each
# --------------------------------------------------------------------------

_UNIT = '        unit="thousand_barrels_seasonal_deviation",'
# ⚠️ WIDENED at D-121: `            EvidenceSourceFamily.MARKET_COMMODITY` was
#     measured at TWO sites once the gold model landed (oil + gold). The
#     distinguishing neighbour is the OIL-only `value` dict entry above it —
#     the gold model's is `dominant_layer`. Widened form: 1.
_FAMILY = (
    "            EvidenceSourceFamily.MARKET_COMMODITY\n"
    "            if fetched_legs > 0\n"
    "            else EvidenceSourceFamily.MANUAL_ASSESSMENT\n"
    "        ),\n"
    "        interpretation=(\n"
    "            f\"Oil market {'tightening' if tightness > 0 else 'loosening'} \""
)

# --------------------------------------------------------------------------
# M7: the disclosure.  measured: 1
# --------------------------------------------------------------------------

_SUPPLIED_INV = '            "inventory_change_weekly SUPPLIED BY THE CALLER — unit is THOUSAND "'

# --------------------------------------------------------------------------
# M8: the input guards.
#
# ⚠️ D-122 WIDENED THIS. The bare guard line now occurs at TWO sites (the oil
#    validator and the metals validator — the metals block reuses the same
#    idiom). Widened with the loop's own `getattr` line, which the metals
#    validator has but the oil one does not: 1 (asserted by
#    `_check_targets_only`).
# --------------------------------------------------------------------------

_NAN_GUARD = (
    "            value = getattr(self, name)\n"
    '            if value is not None and (value != value or abs(value) == float("inf")):'
)

# --------------------------------------------------------------------------
# M9: the value dict keys.  measured: 1 each
# --------------------------------------------------------------------------

_TIGHT_KEY = '            "tightness": rounded_tightness,'
_DEV_KEY = (
    '            "inventory_seasonal_deviation_thousand_barrels": round(deviation, decimals),'
)
_SPARE_KEY = '            "opec_spare_capacity_mbd": spare,'

# --------------------------------------------------------------------------
# C1/C2: the symbol selection (by NAME, never position).  measured: 1 each
# --------------------------------------------------------------------------

_SYM_INV = '    selected = [r for r in records if r.get("symbol") == INVENTORY_SYMBOL]'
_SYM_SPARE = '    selected = [r for r in records if r.get("symbol") == SPARE_CAPACITY_SYMBOL]'

# --------------------------------------------------------------------------
# C3/C4: the projection-tail clip.
#
# ⚠️ WIDENED AGAIN at D-121. `        if when > as_of:` was measured at TWO
#     sites before (inventory `continue`, spare `projection_rows_dropped += 1`)
#     and at THREE after the gold pair-reader was added — because the gold reader
#     uses the SAME `continue`-only body as the inventory clip (measured 2
#     occurrences of `if when > as_of:\n            continue`). So the widened
#     form is widened AGAIN with the inventory clip's own preceding parse line,
#     which is the only one that names INVENTORY_SYMBOL. Final widened form: 1.
#     The spare form loses nothing: its body (`projection_rows_dropped += 1`)
#     remains unique.
# --------------------------------------------------------------------------

_FUTURE_INV = (
    '        when = _parse_date(row.get("date"), context=f"{INVENTORY_SYMBOL} inventory row")\n'
    "        if when > as_of:\n"
    "            continue"
)
_FUTURE_SPARE = "        if when > as_of:\n            projection_rows_dropped += 1"

# --------------------------------------------------------------------------
# C5: the week-over-week change.  measured: 1
# --------------------------------------------------------------------------

_WEEK_CHANGE = "        change_weekly_thousand_barrels=latest_value - prior_value,"

# --------------------------------------------------------------------------
# C6: the "< 2 observations" refusal.  measured: 1
# --------------------------------------------------------------------------

_GE_TWO = "    if len(parsed) < 2:"

# --------------------------------------------------------------------------
# C7: the seasonal baseline.  measured: 1 each
# --------------------------------------------------------------------------

_SEASONAL_YEARS = "    wanted = {latest_week.year - offset for offset in range(1, years + 1)}"
_SEASONAL_NONE = "    if not present:\n        return None, 0"

# --------------------------------------------------------------------------
# C8: the null-value refusal.  measured: 1
# --------------------------------------------------------------------------

_NULL_GUARD = "    if raw is None:"

# --------------------------------------------------------------------------
# G1-G4: the config accessors and validators.
#
# ⚠️ WIDENED: `        if not 0.0 <= self.reliability_value <= 1.0:` and
#     `        return float(self.reliability_cap.value)` were each measured at
#     THREE occurrences (Intervention/EMVulnerability/OilBalance share the
#     identical guard and accessor text). The distinguishing neighbour is the
#     `oil_balance.` error-message prefix (G1) and the OilBalance docstring line
#     (G4), each measured at exactly one site.
# --------------------------------------------------------------------------

_CAP_ACCESSOR = (
    "        are measured series, not a rule of thumb about historical crises.\n"
    '        """\n'
    "        return float(self.reliability_cap.value)"
)
_DECIMALS_ACCESSOR = (
    "        thousand. The leaf is kept at the specification's ``2`` for\n"
    "        comparability, but the note records that the last digit is not\n"
    "        informative.\n"
    '        """\n'
    "        return int(self.value_decimals_leaf.value)"
)
_SPARE_THRESHOLD_ACCESSOR = "        return float(self.tight_spare_threshold_mbd.value)"
_CAP_VALIDATOR = (
    "        if not 0.0 <= self.reliability_value <= 1.0:\n"
    "            raise ValueError(\n"
    '                f"oil_balance.reliability_cap is {self.reliability_value}. A "'
)
_DECIMALS_VALIDATOR = (
    "        if self.value_decimals < 0:\n"
    "            raise ValueError(\n"
    '                f"oil_balance.value_decimals is {self.value_decimals}. A negative "'
)
_SPARE_THRESHOLD_VALIDATOR = "        if self.tight_spare_threshold_value < 0.0:"

# --------------------------------------------------------------------------
# GM1-GM8: the GOLD model (D-121, Appendix D).
#
# ⚠️ EVERY ANCHOR HERE WAS MEASURED IN PYTHON BEFORE BEING WRITTEN DOWN, and
#     five had to be WIDENED because the gold model and the oil model share
#     byte-identical plumbing (O-145's lesson, D-119). The measurements:
#
#       `            data_quality_flags_present=fetched_legs < 2,`   -> 2
#       `    if trend == "rising":`            -> 2 (model + _active_layers)
#       `    if change_bp is None:`            -> 2 (resolve guard + refusal)
#       `    if crisis is None:`               -> 2
#       `            EvidenceSourceFamily.MARKET_COMMODITY`  -> 2
#
#     Each is widened with a DISTINGUISHING NEIGHBOUR that occurs once; the
#     widened form's count is asserted in the comment. NEVER delete a mutation
#     to resolve an ambiguity — widen it.
# --------------------------------------------------------------------------

# The `abs(change_bp) > threshold_bp` predicate lives in `_active_layers`.
_GOLD_ABS = "    if abs(change_bp) > threshold_bp:"

# `if trend == "rising":` occurs TWICE (the model's warning branch and the
# helper's layer append). Widened with the helper's own append body: 1.
_GOLD_TREND = '    if trend == "rising":\n        layers.append('

# `dominant = layers[0][0] if layers else "none_identified"` measured: 1.
_GOLD_DOMINANT = '    dominant = layers[0][0] if layers else "none_identified"'

_GOLD_CONF = "    confidence = computed * gold.reliability_value"

# `data_quality_flags_present=fetched_legs < 2,` occurs TWICE (oil + gold).
# Widened with the gold-only `independent_providers` neighbour line: 1.
_GOLD_DQ = (
    "            data_quality_flags_present=fetched_legs < 2,\n"
    "            is_heuristic_not_calibrated=not gold.reliability_cap_is_calibrated,\n"
    "            source_independence_count=independent_providers,"
)

# ⚠️ D-122 WIDENED THIS. `            source_independence_count=independent_providers,`
#    now occurs at TWO sites (the gold block and the metals block). Widened with
#    the gold confidence call's own two preceding lines, which carry gold's
#    `fetched_legs < 2` and `gold.reliability_cap_is_calibrated`: 1 (asserted by
#    `_check_targets_only`).
_GOLD_IND = (
    "            data_quality_flags_present=fetched_legs < 2,\n"
    "            is_heuristic_not_calibrated=not gold.reliability_cap_is_calibrated,\n"
    "            source_independence_count=independent_providers,"
)

# `if change_bp is None:` occurs TWICE (the resolve guard and the refusal).
# Widened with the refusal's own first message line: 1.
_GOLD_PRIMARY_REFUSAL = (
    "    if change_bp is None:\n"
    "        raise ValueError(\n"
    '            "gold_driver_attribution cannot resolve the PRIMARY layer: no "'
)

# `if crisis is None:` occurs TWICE (the resolve guard and the refusal).
# Widened with the refusal's own first message line: 1.
_GOLD_CRISIS_REFUSAL = (
    "    if crisis is None:\n"
    "        raise ValueError(\n"
    '            "gold_driver_attribution cannot resolve the CRISIS layer: the VIX "'
)

_GOLD_UNIT = '        unit="layer_attribution",'

# `EvidenceSourceFamily.MARKET_COMMODITY` occurs TWICE (oil + gold). Widened
# with the gold-only `gold_driver_attribution` docstring line above it: 1.
_GOLD_FAMILY = (
    "        source_family=(\n"
    "            EvidenceSourceFamily.MARKET_COMMODITY\n"
    "            if fetched_legs > 0\n"
    "            else EvidenceSourceFamily.MANUAL_ASSESSMENT\n"
    "        ),\n"
    '        interpretation=f"Gold move most likely driven by: {dominant}",'
)

_GOLD_CB_DISCLOSURE = (
    '            "central_bank_net_purchases_trend NOT RESOLVED — no free live source "'
)

_GOLD_CHANGE_RULE = (
    "    return (reading.yield_percent - reading.prior_yield_percent) * BASIS_POINTS_PER_PERCENT"
)

# --------------------------------------------------------------------------
# GC1-GC3: the GOLD client (D-121).
#
# ⚠️ `        if when > as_of:` occurred at 3 sites after the gold addition (the
#     two oil clips and the gold shared pair-reader). Widened with the gold
#     reader's own `continue` body — the oil inventory clip uses the SAME body,
#     so the widened form was measured at 2 and is widened again with the
#     surrounding pair-append line: 1 (asserted below).
# --------------------------------------------------------------------------

_BP_CONST = "BASIS_POINTS_PER_PERCENT = 100.0"

_GOLD_CLIP = (
    "        if when > as_of:\n"
    "            continue\n"
    '        pairs.append((when, _parse_value(raw_value, context=f"{symbol} {label} row @ {when}")))'
)

# ⚠️ D-122 WIDENED THIS. `    if len(observed) >= 2:` now occurs at TWO sites in
#    the client (the gold real-yield reader and the metals shared reader).
#    Widened with the gold reader's own label line and error message, which name
#    `real-yield` and `REAL_YIELD_SYMBOL`: 1 (asserted by `_check_targets_only`).
_GOLD_WINDOW = (
    '        label="real-yield",\n'
    "    )\n"
    "    if not observed:\n"
    "        raise CommodityReadError(\n"
    '            f"real-yield series {REAL_YIELD_SYMBOL} had no observation at or "\n'
    '            f"before {as_of.isoformat()}."\n'
    "        )\n"
    "\n"
    "    latest_date, latest_value = observed[-1]\n"
    "    if len(observed) >= 2:"
)

# --------------------------------------------------------------------------
# GG1-GG4: the GOLD config leaves (D-121).
#
# ⚠️ `        return float(self.reliability_cap.value)` occurred at FOUR sites
#     after the gold addition (Intervention/EMVulnerability/OilBalance/Gold).
#     Widened with the gold block's own preceding line — the accessor's closing
#     docstring sentence, which is gold-specific. Same treatment for the
#     decimals accessor (2 sites): each widened form measured at 1.
# --------------------------------------------------------------------------

_GOLD_CAP_ACCESSOR = (
    '        exact arithmetic.\n        """\n        return float(self.reliability_cap.value)'
)

_GOLD_DECIMALS_ACCESSOR = (
    '        more.\n        """\n        return int(self.value_decimals_leaf.value)'
)

# These two accessors are unique by construction (their leaf names occur once).
_GOLD_YIELD_ACCESSOR = "        return float(self.yield_change_threshold_materiality_bp.value)"
_GOLD_VIX_ACCESSOR = "        return float(self.crisis_vix_spike_level.value)"

# The gold validators. `if not 0.0 <= self.reliability_value <= 1.0:` occurs at
# FOUR sites; widened with the gold block's error-message prefix: 1.
_GOLD_CAP_VALIDATOR = (
    "        if not 0.0 <= self.reliability_value <= 1.0:\n"
    "            raise ValueError(\n"
    '                f"gold_driver.reliability_cap is {self.reliability_value}. A "'
)

# `        if self.value_decimals < 0:` occurs at TWO sites; widened with the
# gold error-message prefix: 1.
_GOLD_DECIMALS_VALIDATOR = (
    "        if self.value_decimals < 0:\n"
    "            raise ValueError(\n"
    '                f"gold_driver.value_decimals is {self.value_decimals}. A negative "'
)

_GOLD_YIELD_VALIDATOR = "        if self.yield_change_threshold_bp <= 0.0:"
_GOLD_VIX_VALIDATOR = "        if self.crisis_vix_threshold_value <= 0.0:"

# --------------------------------------------------------------------------
# MM1-MM8, MC1-MC4, MG1-MG5: the METALS complex (D-122).
#
# ⚠️ EVERY anchor below is a MEASURED-UNIQUE form (``count() == 1`` against its
#    target file AFTER this increment's edits). The widening is stated with each
#    constant so a future reader can see WHY it is not the bare line, and can
#    re-measure it rather than trusting this comment. A bare line that occurs
#    twice would mutate the FIRST site and manufacture a false survivor (D-048).
# --------------------------------------------------------------------------

# The two predicates. Both unique by construction (their parameter names
# ``aluminum_band_pct`` / ``broad_weakness_threshold_pct`` occur once each).
_MM1_CONSTRUCTION = (
    "    construction_specific = iron_ore < copper < 0 and abs(aluminum) < aluminum_band_pct"
)
_MM2_BROAD = (
    "        value < -broad_weakness_threshold_pct for value in (copper, iron_ore, aluminum)"
)
_MM6_DIRECTION = (
    '        direction=("expansionary" if verdict == "MIXED_no_clear_pattern" else "restrictive"),'
)
_MM7_ROUND_CU = '            "copper_change_pct": round(copper, metals.value_decimals),'
_MM7_ROUND_FE = '            "iron_ore_change_pct": round(iron_ore, metals.value_decimals),'
_MM7_ROUND_AL = '            "aluminum_change_pct": round(aluminum, metals.value_decimals),'
_MM8_ASSERT = "    assert copper is not None and iron_ore is not None and aluminum is not None"
# ⚠️ D-122 RETARGET (the D-031 `U4a` precedent). `_MM8_ASSERT` above is a
#    TYPE-NARROWING assertion: past the `missing` guard all three legs are
#    non-None, so removing it changes NO runtime behaviour — a pytest sweep can
#    never kill it. MEASURED 2026-09-27: removing it fails `mypy --strict` with
#    SIX errors (`copper`/`iron_ore`/`aluminum` typed `float | None` at the
#    `_classify_metals` call and the three `round(...)` calls), so the mutation
#    IS load-bearing — but for the MYPY GATE, not for pytest. Per D-031 a
#    survivor that is neither a weak test nor inert is RETARGETED, not dropped:
#    the mutation below inverts the `missing` predicate's sense so the refusal
#    fires on the legs that ARE present. That IS pytest-detectable, keeps the
#    "resolution must be complete" intent, and does NOT duplicate `MM8a` (which
#    removes the raise entirely rather than misfiring it).
_MM8_MISSING = "        if value is None"
_INF = 'float("inf")'
_MM8_FINITE = (
    "            value = getattr(self, name)\n"
    "            if value is not None and (value != value or abs(value) == " + _INF + "):"
)

# The two verdict-literal anchors are unique because the construction branch is
# indented one level deeper than the fallthrough (``        return`` vs
# ``    return``), so each literal occurs once.
_MM3_RET_CONSTRUCTION = '        return "CHINA_CONSTRUCTION_SPECIFIC"'
_MM3_RET_BROAD = '        return "BROAD_INDUSTRIAL_WEAKNESS"'
_MM3_RET_MIXED = '    return "MIXED_no_clear_pattern"'

# ⚠️ ``    independent_providers = 1 if fetched_legs > 0 else 0`` occurs at TWO
#    sites after the metals addition (the gold model has the identical line).
#    WIDENED with the metals comment's own closing words, which are
#    metals-specific: 1.
_MM4_INDEP = (
    "rule, restated for three legs instead of two.\n"
    "    independent_providers = 1 if fetched_legs > 0 else 0"
)

_MM4_MULTIPLY = "    confidence = computed * metals.reliability_value"
_MM4_FLAG = "            data_quality_flags_present=fetched_legs < 3,"

# ⚠️ ``            EvidenceSourceFamily.MARKET_COMMODITY\n            if fetched_legs > 0``
#    occurs at THREE sites (oil, gold, metals). WIDENED with the metals block's
#    own ``direction=`` line, which carries the metals-only verdict vocabulary: 1.
_MM5_FAMILY = (
    '        direction=("expansionary" if verdict == "MIXED_no_clear_pattern"'
    ' else "restrictive"),\n'
    "        source_family=(\n"
    "            EvidenceSourceFamily.MARKET_COMMODITY\n"
    "            if fetched_legs > 0"
)

# ⚠️ ``    if missing:`` occurs at TWO sites in the model. WIDENED with the
#    metals error message's own first fragment (the function name), which is
#    unique: 1.
_MM8_REFUSAL = (
    "    if missing:\n"
    "        raise ValueError(\n"
    '            f"metals_complex_divergence cannot resolve'
)

# --- the CLIENT anchors ----------------------------------------------------
_MC1_COPPER = 'COPPER_SYMBOL = "PCOPPUSDM"'
_MC1_IRON = 'IRON_ORE_SYMBOL = "PIORECRUSDM"'
_MC1_ALUM = 'ALUMINUM_SYMBOL = "PALUMUSDM"'
_MC2_UNIT = 'METALS_SOURCE_UNIT = "usd_per_metric_ton"'
_MC3_PCT = "    return (latest - prior) / prior * 100.0"
_MC3_ZERO = "    if prior == 0.0:"

# ⚠️ ``    if len(observed) >= 2:`` occurs at TWO sites in the client (the gold
#    real-yield reader and the metals shared reader). WIDENED with the metals
#    reader's own label line, which is metals-only (``{label} price``): 1.
_MC4_WINDOW = (
    '    observed = _observed_pairs(frame, symbol=symbol, as_of=as_of, label=f"{label} price")\n'
    "    if not observed:\n"
    "        raise CommodityReadError(\n"
    '            f"{label} price series {symbol} had no observation at or before '
    '{as_of.isoformat()}."\n'
    "        )\n"
    "\n"
    "    latest_date, latest_value = observed[-1]\n"
    "    if len(observed) >= 2:"
)

# --- the CONFIG anchors ----------------------------------------------------
#
# ⚠️ FIVE of these need widening. Adding ``MetalsComplexSettings`` made the
#    following byte-identical strings AMBIGUOUS — the D-119 O-145 shape, now at
#    FIVE copies across Intervention/EMVulnerability/OilBalance/Gold/Metals:
#
#      ``        return float(self.reliability_cap.value)``     5 sites
#      ``        return int(self.value_decimals_leaf.value)``   3 sites
#      ``        if not 0.0 <= self.reliability_value <= 1.0:`` 5 sites
#      ``        if self.value_decimals < 0:``                  3 sites
#      ``        return self.reliability_cap.is_trustworthy``   5 sites
#
#    Each widened form below was measured at exactly 1.
_MG1_CAP = (
    "        series while these three legs share one provider and one family.\n"
    '        """\n'
    "        return float(self.reliability_cap.value)"
)
_MG1_DECIMALS = (
    "        magnitude without implying the model's bands are resolved finer than\n"
    "        whole per-cent.\n"
    '        """\n'
    "        return int(self.value_decimals_leaf.value)"
)
# These two are unique by construction (their leaf names occur once).
_MG2_BAND = "        return float(self.aluminum_stability_band_pct_leaf.value)"
_MG3_THRESH = "        return float(self.broad_weakness_threshold_pct_leaf.value)"
_MG4_CAP_VALID = (
    "        if not 0.0 <= self.reliability_value <= 1.0:\n"
    "            raise ValueError(\n"
    '                f"metals_complex.reliability_cap is {self.reliability_value}. A "'
)
_MG4_DECIMALS_VALID = (
    "        if self.value_decimals < 0:\n"
    "            raise ValueError(\n"
    '                f"metals_complex.value_decimals is {self.value_decimals}. A "'
)
# These two are unique by construction (metals-only property names).
_MG4_BAND_VALID = "        if self.aluminum_band_pct <= 0.0:"
_MG4_THRESH_VALID = "        if self.broad_weakness_threshold_pct <= 0.0:"
#
# ⚠️ The two metals-branded validators above carry the identity in BOTH the
#    guard compare AND the neighbouring error message, so a mutation of the
#    guard cannot silently retarget a sibling class's validator.
#
# ⚠️ ``        return self.reliability_cap.is_trustworthy`` occurs at FIVE
#    sites; the gas/gold/others' preceding docstrings are identical. WIDENED
#    FORWARD into the NEXT property (``value_decimals``), whose docstring IS
#    metals-specific: 1.
_MG5_TRUST = (
    "        half prices the leaf's own status rather than assuming it.\n"
    '        """\n'
    "        return self.reliability_cap.is_trustworthy\n"
    "\n"
    "    @property\n"
    "    def value_decimals(self) -> int:\n"
    '        """The decimal places each published percent change is rounded to.'
)

_MUTATIONS: list[tuple[str, Path, str, str]] = [
    # --- CANARY (O-72/D-051): a syntax error the selection MUST catch --------
    (
        "CANARY1 a deliberate syntax error in the model",
        MODEL,
        "logger = logging.getLogger(__name__)",
        "logger = logging.getLogger(__name__  # unbalanced",
    ),
    # --- M1: the sign --------------------------------------------------------
    (
        "M1a the tightness sign flipped (a draw would loosen)",
        MODEL,
        _SIGN,
        "    tightness = deviation  # draw = tightening (Section 6.8)",
    ),
    # --- M2: the direction label ---------------------------------------------
    (
        "M2a the direction literal swapped",
        MODEL,
        _DIRECTION,
        '        direction="tightening" if tightness < 0 else "loosening",',
    ),
    (
        "M2b the direction threshold loosened to >= 0",
        MODEL,
        _DIRECTION,
        '        direction="tightening" if tightness >= 0 else "loosening",',
    ),
    # --- M3: the rounding ----------------------------------------------------
    (
        "M3a the tightness rounding dropped",
        MODEL,
        _ROUND,
        "    rounded_tightness = tightness",
    ),
    (
        "M3b the rounding hardcodes two decimals",
        MODEL,
        _ROUND,
        "    rounded_tightness = round(tightness, 2)",
    ),
    # --- M4: the confidence --------------------------------------------------
    (
        "M4a the confidence product becomes the cap alone",
        MODEL,
        _CONF_PRODUCT,
        "    confidence = oil.reliability_value",
    ),
    (
        "M4b the confidence product becomes a min()",
        MODEL,
        _CONF_PRODUCT,
        "    confidence = min(computed, oil.reliability_value)",
    ),
    (
        "M4c the quality flag never set",
        MODEL,
        _CONF_DQ,
        "            data_quality_flags_present=False,",
    ),
    (
        "M4d the independence count hardcoded zero",
        MODEL,
        _CONF_IND,
        "            source_independence_count=0,",
    ),
    # --- M5: the refusal -----------------------------------------------------
    (
        "M5a the missing-legs refusal removed",
        MODEL,
        _MISSING_REFUSAL,
        "    if False:",
    ),
    # --- M6: the contract ----------------------------------------------------
    (
        "M6a the unit mislabelled",
        MODEL,
        _UNIT,
        '        unit="thousand_barrels",',
    ),
    (
        "M6b the family always MANUAL_ASSESSMENT",
        MODEL,
        _FAMILY,
        "            EvidenceSourceFamily.MANUAL_ASSESSMENT",
    ),
    # --- M7: the disclosure --------------------------------------------------
    (
        "M7a the supplied-leg disclosure dropped",
        MODEL,
        _SUPPLIED_INV,
        '            "inventory_change_weekly FETCHED BY THE CALLER — unit is THOUSAND "',
    ),
    # --- M8: the guards ------------------------------------------------------
    (
        "M8a the non-finite guard removed",
        MODEL,
        _NAN_GUARD,
        "            if False:",
    ),
    # --- M9: the value dict ---------------------------------------------------
    (
        "M9a the tightness key dropped from the value",
        MODEL,
        _TIGHT_KEY,
        '            "tightness": 0.0,',
    ),
    (
        "M9b the deviation key omitted",
        MODEL,
        _DEV_KEY,
        '            "inventory_seasonal_deviation_thousand_barrels": 0.0,',
    ),
    (
        "M9c the spare key omitted",
        MODEL,
        _SPARE_KEY,
        '            "opec_spare_capacity_mbd": 0.0,',
    ),
    # --- C1/C2: the symbol selection -----------------------------------------
    (
        "C1a the inventory symbol filter removed",
        CLIENT,
        _SYM_INV,
        "    selected = list(records)",
    ),
    (
        "C2a the spare symbol filter removed",
        CLIENT,
        _SYM_SPARE,
        "    selected = list(records)",
    ),
    # --- C3/C4: the projection-tail clip -------------------------------------
    (
        "C3a the inventory future-date clip removed",
        CLIENT,
        _FUTURE_INV,
        "        if False:\n            continue",
    ),
    (
        "C3b the inventory clip boundary flipped to >= (drops today's observation)",
        CLIENT,
        _FUTURE_INV,
        "        if when >= as_of:\n            continue",
    ),
    (
        "C4a the spare projection clip removed",
        CLIENT,
        _FUTURE_SPARE,
        "        if False:\n            projection_rows_dropped += 1",
    ),
    (
        "C4b the projection clip inverted (keeps only projections)",
        CLIENT,
        _FUTURE_SPARE,
        "        if when < as_of:\n            projection_rows_dropped += 1",
    ),
    # --- C5: the week-over-week change ---------------------------------------
    (
        "C5a the week change sign flipped",
        CLIENT,
        _WEEK_CHANGE,
        "        change_weekly_thousand_barrels=prior_value - latest_value,",
    ),
    # --- C6: the observations guard ------------------------------------------
    (
        "C6a the two-observation guard loosened to one",
        CLIENT,
        _GE_TWO,
        "    if len(parsed) < 1:",
    ),
    # --- C7: the seasonal baseline -------------------------------------------
    (
        "C7a the baseline year window widened",
        CLIENT,
        _SEASONAL_YEARS,
        "    wanted = {latest_week.year - offset for offset in range(1, years + 2)}",
    ),
    (
        "C7b the no-baseline return becomes zero",
        CLIENT,
        _SEASONAL_NONE,
        "    if not present:\n        return 0.0, 0",
    ),
    # --- C8: the null-value refusal ------------------------------------------
    (
        "C8a the null-value refusal removed",
        CLIENT,
        _NULL_GUARD,
        "    if False:",
    ),
    # --- G1-G4: the config ----------------------------------------------------
    (
        "G1a the reliability accessor returns a literal",
        CONFIG,
        _CAP_ACCESSOR,
        '        """\n        return 0.4',
    ),
    (
        "G2a the decimals accessor returns a literal",
        CONFIG,
        _DECIMALS_ACCESSOR,
        "        return 2",
    ),
    (
        "G3a the spare-threshold accessor returns a literal",
        CONFIG,
        _SPARE_THRESHOLD_ACCESSOR,
        "        return 2.0",
    ),
    (
        "G4a the cap validator neutralised",
        CONFIG,
        _CAP_VALIDATOR,
        "        if False:",
    ),
    (
        "G4b the decimals validator neutralised",
        CONFIG,
        _DECIMALS_VALIDATOR,
        "        if False:",
    ),
    (
        "G4c the spare-threshold validator neutralised",
        CONFIG,
        _SPARE_THRESHOLD_VALIDATOR,
        "        if False:",
    ),
    # --- GM1-GM8: the GOLD model (D-121) -------------------------------------
    (
        "GM1a the abs() dropped, so only RATE RISES fire the primary layer",
        MODEL,
        _GOLD_ABS,
        "    if change_bp > threshold_bp:",
    ),
    (
        "GM1b the threshold comparison loosened to >= (the boundary fires)",
        MODEL,
        _GOLD_ABS,
        "    if abs(change_bp) >= threshold_bp:",
    ),
    (
        "GM2a the trend predicate accepts any non-flat value",
        MODEL,
        _GOLD_TREND,
        '    if trend != "flat":',
    ),
    (
        "GM2b the trend predicate inverted to the fall direction",
        MODEL,
        _GOLD_TREND,
        '    if trend == "falling":',
    ),
    (
        "GM3a the dominant layer becomes the LAST active one",
        MODEL,
        _GOLD_DOMINANT,
        '    dominant = layers[-1][0] if layers else "none_identified"',
    ),
    (
        "GM3b the dominant layer becomes a fixed literal",
        MODEL,
        _GOLD_DOMINANT,
        '    dominant = "real_yield"',
    ),
    (
        "GM4a the confidence product becomes the cap alone",
        MODEL,
        _GOLD_CONF,
        "    confidence = gold.reliability_value",
    ),
    (
        "GM4b the confidence product becomes a min()",
        MODEL,
        _GOLD_CONF,
        "    confidence = min(computed, gold.reliability_value)",
    ),
    (
        "GM5a the independence count uses the raw fetched-leg count (2, not 1)",
        MODEL,
        _GOLD_IND,
        "            source_independence_count=fetched_legs,",
    ),
    (
        "GM5b the gold quality flag never set",
        MODEL,
        _GOLD_DQ,
        "            data_quality_flags_present=False,",
    ),
    (
        "GM6a the primary-layer refusal removed (degrades silently)",
        MODEL,
        _GOLD_PRIMARY_REFUSAL,
        "    if False:",
    ),
    (
        "GM6b the crisis-layer refusal removed ('could not read' becomes 'calm')",
        MODEL,
        _GOLD_CRISIS_REFUSAL,
        "    if False:",
    ),
    (
        "GM7a the gold unit mislabelled",
        MODEL,
        _GOLD_UNIT,
        '        unit="thousand_barrels_seasonal_deviation",',
    ),
    (
        "GM7b the gold family always MANUAL_ASSESSMENT",
        MODEL,
        _GOLD_FAMILY,
        "            EvidenceSourceFamily.MANUAL_ASSESSMENT",
    ),
    (
        "GM7c the CB-layer absence disclosed as a fetched value",
        MODEL,
        _GOLD_CB_DISCLOSURE,
        '            "central_bank_net_purchases_trend SUPPLIED BY THE CALLER "',
    ),
    (
        "GM8a the change rule drops the bp conversion",
        CLIENT,
        _GOLD_CHANGE_RULE,
        "    return reading.yield_percent - reading.prior_yield_percent",
    ),
    (
        "GM8b the change rule inverts the sign",
        CLIENT,
        _GOLD_CHANGE_RULE,
        "    return (reading.prior_yield_percent - reading.yield_percent) * BASIS_POINTS_PER_PERCENT",
    ),
    # --- GC1-GC3: the GOLD client --------------------------------------------
    (
        "GC1a the bp conversion constant becomes 1 (levels not bp)",
        CLIENT,
        _BP_CONST,
        "BASIS_POINTS_PER_PERCENT = 1.0",
    ),
    (
        "GC2a the future-row clip removed in the shared pair reader",
        CLIENT,
        _GOLD_CLIP,
        "        if False:\n            continue",
    ),
    (
        "GC2b the future-row clip boundary flipped to >= (drops the as-of row)",
        CLIENT,
        _GOLD_CLIP,
        "        if when >= as_of:\n            continue",
    ),
    (
        "GC3a the two-point window loosened to one (a prior of None)",
        CLIENT,
        _GOLD_WINDOW,
        "    if len(observed) >= 1:",
    ),
    # --- GG1-GG4: the GOLD config leaves -------------------------------------
    (
        "GG1a the gold reliability accessor returns a literal",
        CONFIG,
        _GOLD_CAP_ACCESSOR,
        '        """\n        return 0.35',
    ),
    (
        "GG2a the gold decimals accessor returns a literal",
        CONFIG,
        _GOLD_DECIMALS_ACCESSOR,
        "        return 1",
    ),
    (
        "GG3a the gold yield-threshold accessor returns a literal",
        CONFIG,
        _GOLD_YIELD_ACCESSOR,
        "        return 10.0",
    ),
    (
        "GG3b the gold VIX-threshold accessor returns a literal",
        CONFIG,
        _GOLD_VIX_ACCESSOR,
        "        return 30.0",
    ),
    (
        "GG4a the gold cap validator neutralised",
        CONFIG,
        _GOLD_CAP_VALIDATOR,
        "        if False:",
    ),
    (
        "GG4b the gold decimals validator neutralised",
        CONFIG,
        _GOLD_DECIMALS_VALIDATOR,
        "        if False:",
    ),
    (
        "GG4c the gold yield-threshold validator neutralised",
        CONFIG,
        _GOLD_YIELD_VALIDATOR,
        "        if False:",
    ),
    (
        "GG4d the gold VIX-threshold validator neutralised",
        CONFIG,
        _GOLD_VIX_VALIDATOR,
        "        if False:",
    ),
    # ======================================================================
    # MODULE 10.3 — the METALS complex (D-122).
    #
    # ⚠️ EVERY anchor below was measured with ``str.count()`` against its target
    #    file AFTER this increment's edits, and the count is recorded. Five of
    #    the config anchors and two model/client anchors had to be WIDENED,
    #    because adding ``MetalsComplexSettings`` made byte-identical siblings
    #    AMBIGUOUS — the D-119 O-145 shape, now at FIVE copies:
    #
    #      * ``        return float(self.reliability_cap.value)``       5 sites
    #      * ``        return int(self.value_decimals_leaf.value)``     3 sites
    #      * ``        if not 0.0 <= self.reliability_value <= 1.0:``   5 sites
    #      * ``        if self.value_decimals < 0:``                    3 sites
    #      * ``        return self.reliability_cap.is_trustworthy``     5 sites
    #      * ``    independent_providers = 1 if fetched_legs > 0 else 0`` 2 sites
    #      * ``            EvidenceSourceFamily.MARKET_COMMODITY``/``if fetched_legs > 0`` 3 sites
    #      * ``    if len(observed) >= 2:`` (client)                    2 sites
    #
    #    A widening is a claim about BYTES, so each is asserted at 1 in the
    #    comments and re-verified by ``_check_targets_only``.
    # ======================================================================
    # --- MM1: the construction-specific predicate --------------------------
    #     The DISCRIMINATING test. This is the whole point of the function: a
    #     mutant that drops the iron-ore-first ordering or the aluminum band
    #     destroys the localisation. measured: 1
    (
        "MM1a the iron-ore-first ordering relaxed to copper-first",
        MODEL,
        _MM1_CONSTRUCTION,
        "    construction_specific = copper < iron_ore < 0 and abs(aluminum) < aluminum_band_pct",
    ),
    (
        "MM1b the iron-ore-must-fall condition dropped",
        MODEL,
        _MM1_CONSTRUCTION,
        "    construction_specific = copper < 0 and abs(aluminum) < aluminum_band_pct",
    ),
    (
        "MM1c the aluminum-stability band flipped to <= (a boundary mutant)",
        MODEL,
        _MM1_CONSTRUCTION,
        "    construction_specific = iron_ore < copper < 0 and abs(aluminum) <= aluminum_band_pct",
    ),
    (
        "MM1d the aluminum-stability condition dropped entirely",
        MODEL,
        _MM1_CONSTRUCTION,
        "    construction_specific = iron_ore < copper < 0",
    ),
    # --- MM2: the broad-weakness predicate ---------------------------------
    #     measured: 1
    (
        "MM2a the broad threshold flipped to <= (a boundary mutant)",
        MODEL,
        _MM2_BROAD,
        "        value <= -broad_weakness_threshold_pct for value in (copper, iron_ore, aluminum)",
    ),
    (
        "MM2b the broad threshold sign dropped (rising metals would be 'weak')",
        MODEL,
        _MM2_BROAD,
        "        value < broad_weakness_threshold_pct for value in (copper, iron_ore, aluminum)",
    ),
    (
        "MM2c the broad test applied to only two of the three metals",
        MODEL,
        _MM2_BROAD,
        "        value < -broad_weakness_threshold_pct for value in (copper, iron_ore)",
    ),
    # --- MM3: the verdict literals -----------------------------------------
    (
        "MM3a the construction verdict literal swapped to broad",
        MODEL,
        _MM3_RET_CONSTRUCTION,
        '        return "BROAD_INDUSTRIAL_WEAKNESS"',
    ),
    (
        "MM3b the broad verdict literal swapped to construction",
        MODEL,
        _MM3_RET_BROAD,
        '        return "CHINA_CONSTRUCTION_SPECIFIC"',
    ),
    (
        "MM3c the fallthrough verdict mislabelled",
        MODEL,
        _MM3_RET_MIXED,
        '    return "MIXED"',
    ),
    # --- MM4: confidence / independence ------------------------------------
    #     The independence count must be ONE for any fetched set (three legs,
    #     one provider). Reporting the leg count would triple-count the
    #     evidence — the D-118/D-119 rule restated for three legs.
    (
        "MM4a the independence count inflated to the leg count",
        MODEL,
        _MM4_INDEP,
        "    independent_providers = fetched_legs",
    ),
    (
        "MM4b the independent-provider count forced to 0",
        MODEL,
        _MM4_INDEP,
        "    independent_providers = 0",
    ),
    (
        "MM4c the confidence product replaced by the cap alone (min-like)",
        MODEL,
        _MM4_MULTIPLY,
        "    confidence = metals.reliability_value",
    ),
    (
        "MM4d the fetched-legs quality flag inverted",
        MODEL,
        _MM4_FLAG,
        "            data_quality_flags_present=fetched_legs > 0,",
    ),
    # --- MM5: the source family --------------------------------------------
    (
        "MM5a the fetched family swapped to MANUAL_ASSESSMENT",
        MODEL,
        _MM5_FAMILY,
        "            EvidenceSourceFamily.MANUAL_ASSESSMENT\n            if fetched_legs > 0",
    ),
    (
        "MM5b the fetched condition inverted so a supplied run claims market data",
        MODEL,
        _MM5_FAMILY,
        "            EvidenceSourceFamily.MARKET_COMMODITY\n            if fetched_legs == 0",
    ),
    # --- MM6: the direction vocabulary -------------------------------------
    (
        "MM6a the restrictive branch swapped for expansionary",
        MODEL,
        _MM6_DIRECTION,
        '        direction=("expansionary" if verdict != "MIXED_no_clear_pattern" else "restrictive"),',
    ),
    # --- MM7: the rounding --------------------------------------------------
    (
        "MM7a the copper rounding dropped",
        MODEL,
        _MM7_ROUND_CU,
        '            "copper_change_pct": copper,',
    ),
    (
        "MM7b the iron-ore rounding dropped",
        MODEL,
        _MM7_ROUND_FE,
        '            "iron_ore_change_pct": iron_ore,',
    ),
    (
        "MM7c the aluminum rounding dropped",
        MODEL,
        _MM7_ROUND_AL,
        '            "aluminum_change_pct": aluminum,',
    ),
    # --- MM8: the refusal and the finite guard -----------------------------
    (
        "MM8a the missing-leg refusal neutralised",
        MODEL,
        _MM8_REFUSAL,
        "        pass",
    ),
    (
        "MM8b the non-finite input guard neutralised",
        MODEL,
        _MM8_FINITE,
        "            if False:",
    ),
    (
        "MM8c the non-finite guard's ``abs`` dropped (inf only, nan escapes)",
        MODEL,
        _MM8_FINITE,
        "            if value is not None and (value != value or value == " + _INF + "):",
    ),
    (
        "MM8d the missing predicate inverted (the refusal misfires on present legs)",
        MODEL,
        _MM8_MISSING,
        "        if value is not None",
    ),
    # --- MC1-MC2: the client symbols and unit ------------------------------
    (
        "MC1a the copper symbol swapped for the aluminum one",
        CLIENT,
        _MC1_COPPER,
        'COPPER_SYMBOL = "PALUMUSDM"',
    ),
    (
        "MC1b the iron-ore symbol swapped for the copper one",
        CLIENT,
        _MC1_IRON,
        'IRON_ORE_SYMBOL = "PCOPPUSDM"',
    ),
    (
        "MC1c the aluminum symbol swapped for the iron-ore one",
        CLIENT,
        _MC1_ALUM,
        'ALUMINUM_SYMBOL = "PIORECRUSDM"',
    ),
    (
        "MC2a the metals unit mislabelled as per pound",
        CLIENT,
        _MC2_UNIT,
        'METALS_SOURCE_UNIT = "usd_per_pound"',
    ),
    # --- MC3: the percent change -------------------------------------------
    (
        "MC3a the percent change dropped its scale factor",
        CLIENT,
        _MC3_PCT,
        "    return (latest - prior) / prior",
    ),
    (
        "MC3b the percent change inverted (prior over latest)",
        CLIENT,
        _MC3_PCT,
        "    return (prior - latest) / latest * 100.0",
    ),
    (
        "MC3c the zero-prior guard neutralised",
        CLIENT,
        _MC3_ZERO,
        "    if False:",
    ),
    # --- MC4: the two-vintage window ---------------------------------------
    (
        "MC4a the two-observation window collapsed to one (change always None)",
        CLIENT,
        _MC4_WINDOW,
        "    if len(observed) >= 1:",
    ),
    # --- MG1-MG5: the config accessors and validators ----------------------
    (
        "MG1a the metals cap accessor returns a literal",
        CONFIG,
        _MG1_CAP,
        "        return 0.5",
    ),
    (
        "MG1b the metals decimals accessor returns a literal",
        CONFIG,
        _MG1_DECIMALS,
        "        return 4",
    ),
    (
        "MG2a the aluminum-band accessor returns a literal",
        CONFIG,
        _MG2_BAND,
        "        return 2.0",
    ),
    (
        "MG3a the broad-threshold accessor returns a literal",
        CONFIG,
        _MG3_THRESH,
        "        return 2.0",
    ),
    (
        "MG4a the metals cap validator neutralised",
        CONFIG,
        _MG4_CAP_VALID,
        "        if False:",
    ),
    (
        "MG4b the metals decimals validator neutralised",
        CONFIG,
        _MG4_DECIMALS_VALID,
        "        if False:",
    ),
    (
        "MG4c the metals aluminum-band validator neutralised",
        CONFIG,
        _MG4_BAND_VALID,
        "        if False:",
    ),
    (
        "MG4d the metals broad-threshold validator neutralised",
        CONFIG,
        _MG4_THRESH_VALID,
        "        if False:",
    ),
    (
        "MG5a the metals cap-trust accessor forced True",
        CONFIG,
        _MG5_TRUST,
        "        return True",
    ),
]


def run_tests() -> bool:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/models/test_commodities.py",
            "tests/data_layer/test_commodities_client.py",
            "tests/test_infrastructure.py",
            "tests/test_openbb_command_inventory.py",
            "-q",
            "--no-header",
            # `-x` is D-057's rule: a kill is a kill, the first failing test is
            # sufficient evidence, and an interrupted long run on win32 leaves
            # every mutant applied so far on disk (D-082).
            "-x",
            "-m",
            "not live",
        ],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def _check_targets_only() -> int:
    """Print the anchor verdict and STOP, touching nothing (O-138).

    **Must run BEFORE ``sweep_lifecycle``** — that helper writes a sidecar and
    installs the interrupt defence, i.e. it writes to the tree, which a SAFE
    pre-flight must not do.
    """
    originals = {p: p.read_text(encoding="utf-8") for p in (MODEL, CLIENT, CONFIG) if p.exists()}
    problems = check_targets(originals, _MUTATIONS)
    print(f"check_targets: {len(_MUTATIONS)} mutations, {len(problems)} problem(s)", flush=True)
    if problems:
        print(format_problems(problems))
        print()
        print("ANCHORS UNSOUND: fix the anchors above before sweeping. A sweep that")
        print("cannot prove it mutates the site it names certifies nothing.")
        return 4
    print()
    print("Anchors sound: every mutation resolves to exactly one site. No mutation")
    print("was applied and no sidecar was written (O-138 — this mode stops here).")
    return 0


def main() -> int:
    # O-138: the check-only mode must be answered BEFORE the lifecycle writes.
    if check_only_requested():
        return _check_targets_only()

    with sweep_lifecycle([MODEL, CLIENT, CONFIG]) as originals:
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
        for path, text in originals.items():
            path.write_text(text, encoding="utf-8", newline="")

    print()
    print("=" * 74)
    total = len(_MUTATIONS)
    killed = total - len(survivors)
    print(
        f"MUTATION SWEEP — commodities (oil_balance_signal + commodities_client "
        f"+ OilBalanceSettings): {killed}/{total} killed",
        flush=True,
    )
    print("=" * 74)
    if survivors:
        print("SURVIVORS (each is a weak test, an inert mutation, or a broken one):")
        for name, reason in survivors:
            print(f"  [{reason}] {name}")
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
