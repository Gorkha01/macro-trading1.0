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
_CONF_DQ = "            data_quality_flags_present=fetched_legs < 2,"
_CONF_IND = "            source_independence_count=fetched_legs,"

# --------------------------------------------------------------------------
# M5: the refusal.  measured: 1
# --------------------------------------------------------------------------

_MISSING_REFUSAL = "    if missing:"

# --------------------------------------------------------------------------
# M6: the published contract.  measured: 1 each
# --------------------------------------------------------------------------

_UNIT = '        unit="thousand_barrels_seasonal_deviation",'
_FAMILY = "            EvidenceSourceFamily.MARKET_COMMODITY"

# --------------------------------------------------------------------------
# M7: the disclosure.  measured: 1
# --------------------------------------------------------------------------

_SUPPLIED_INV = '            "inventory_change_weekly SUPPLIED BY THE CALLER — unit is THOUSAND "'

# --------------------------------------------------------------------------
# M8: the input guards.  measured: 1
# --------------------------------------------------------------------------

_NAN_GUARD = '            if value is not None and (value != value or abs(value) == float("inf")):'

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
# C3/C4: the projection-tail clip.  Each `if when > as_of:` was measured at 2
# sites, so each is WIDENED with its own body line (inventory `continue`,
# spare `projection_rows_dropped += 1`).  Each widened form: 1.
# --------------------------------------------------------------------------

_FUTURE_INV = "        if when > as_of:\n            continue"
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
_DECIMALS_ACCESSOR = "        return int(self.value_decimals_leaf.value)"
_SPARE_THRESHOLD_ACCESSOR = "        return float(self.tight_spare_threshold_mbd.value)"
_CAP_VALIDATOR = (
    "        if not 0.0 <= self.reliability_value <= 1.0:\n"
    "            raise ValueError(\n"
    '                f"oil_balance.reliability_cap is {self.reliability_value}. A "'
)
_DECIMALS_VALIDATOR = "        if self.value_decimals < 0:"
_SPARE_THRESHOLD_VALIDATOR = "        if self.tight_spare_threshold_value < 0.0:"

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
