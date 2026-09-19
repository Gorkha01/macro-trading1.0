"""Mutation sweep for Module 7.3's ``leading_indicator_proxy``.

The suite exists to prove four corrections are load-bearing rather than
cosmetic. Each mutation below reverts one of them to the specification's own
spelling, and each must be killed:

* **M1** restores the specification's hardcoded ``confidence=0.5 if ... else 0.3``,
  which Section 22.8 forbids. If the suite does not catch M1, the
  ``compute_confidence`` correction is decoration.
* **M2** restores the literal ``0.6`` threshold, making the config entry
  decorative and the boundary unreviewable.
* **M3** flips the breadth operator from the specification's inclusive ``>=`` to
  a strict ``>``, changing the flagged set without changing any other output.
* **M4** drops the D-029 base-rate disclosure from the value dict and from the
  warnings, so a reader would again be handed a flag with no frequency.
* **M5** renames the model back to the specification's ``lei_composite`` — the
  Section 21.1 naming rule — and removes the disclaimer text.
* **M6** weakens the input contract: the partial-weight guard, the negative-weight
  guard, the non-finite guard, and ``extra="forbid"``.
* **M7** breaks the three-state read so the advance label can be emitted while
  the composite sum is negative — the direction/headline contradiction.

A survivor is one of three things (D-031): a weak test, an **inert** mutation
(the edit cannot change any asserted token), or a **broken** mutation (the
fragment no longer matches the source, usually because ``ruff format`` moved a
trailing comma). The runner reports pattern-miss separately from survival so
those cannot be confused.

Every pattern is matched against the pristine source read from the repo.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SRC = Path("src/macro_engine/models/lei_proxy.py")

# ---------------------------------------------------------------------------
# Named fragments, so the mutation literals stay readable and under the line
# limit. Each must match the source byte-for-byte, including indentation and
# trailing commas — ruff format will reflow a fragment that only approximately
# matches, and the sweep would then silently not apply.
# ---------------------------------------------------------------------------

_CONF_BLOCK = (
    "        confidence=compute_confidence(\n"
    "            ConfidenceInputs(\n"
    "                is_heuristic_not_calibrated=True,\n"
    "                depends_on_unobservable=True,\n"
    "                source_independence_count=0,\n"
    "            )\n"
    "        ),"
)
_THRESHOLD_READ = "    threshold = settings.breadth_threshold_value"
_BROAD_BASED = "    broad_based = breadth >= threshold"
_NULL_RATE_READ = "    null_rate = _breadth_null_rate(n_components, threshold)"
_NULL_FN_SIGN = "    required = ceil(breadth_threshold * n_components)"
_DECLINE_KEY = '            "broad_based": broad_based,'
_NULL_KEY = '            "breadth_null_rate": round(null_rate, 4),'
_DIRECTION_KEY = '            "lead_direction": lead_direction,'
_DECLINE_COUNT = "    n_declining = sum(1 for change in components.values() if change < 0)"
_MODEL_NAME = '        model_name="leading_indicator_proxy",'
_DISCLAIMER = (
    "_NOT_LEI = (\n"
    '    "This is NOT the Conference Board LEI. That series is licensed and "\n'
    '    "unreachable on this build (FRED USLEI returns empty), and Section 21.1 "\n'
    '    "states that an in-house composite built from free components must not be "\n'
    "    \"called 'LEI'. This is a custom proxy with different components, different \"\n"
    '    "weights and a different index level — its LEVEL is not comparable to the "\n'
    '    "published LEI."\n'
    ")"
)
_PARTIAL_WEIGHT_GUARD = (
    "        missing = sorted(set(self.components) - set(self.weights))\n"
    "        if missing:\n"
    "            raise ValueError("
)
_NEGATIVE_WEIGHT_GUARD = (
    "        negative = sorted(name for name, weight in self.weights.items() if weight < 0)\n"
    "        if negative:\n"
    "            raise ValueError("
)
_ALL_ZERO_GUARD = (
    "        if not any(weight > 0 for weight in self.weights.values()):\n"
    "            raise ValueError("
)
_FINITE_GUARD = "        if not isfinite(change):\n            raise ValueError("
_EXTRA_FORBID = (
    '    model_config = ConfigDict(extra="forbid")\n\n    components: dict[str, float] = Field('
)
_ADVANCE_GUARD = "    elif advance_breadth >= threshold and composite > 0:"
_MIXED_WARNING = '            "The components are split — no threshold-sized majority moved the "\n'

# --- D-033 fragments, which live in the data layer, not the model ----------
# They are grouped here rather than beside the mutation list because the list
# is applied against four different files; keeping every pattern defined above
# it means a missing definition is an import error rather than an F821 at the
# point of use, which is far harder to read.
_SNAPSHOT_BUILDER = Path("src/macro_engine/data_layer/snapshot_builder.py")
_VALIDATION = Path("src/macro_engine/data_layer/validation.py")
_CONFIG = Path("src/macro_engine/config.py")

_NOT_A_SNAPSHOT_GUARD = "    if entry.not_a_snapshot_field:\n        raise OpenBBFetchError("
_TOLERANCE_BRANCH = "            if lead_days <= future_date_tolerance_days:"
_TOLERANCE_FIELD = (
    "    future_date_tolerance_days: int = Field(\n        default=0,\n        ge=0,\n        le=7,"
)
_TOLERATED_INFO = '                code="SAME_DAY_PUBLICATION_AHEAD_OF_CLOCK",'


MUTATIONS: list[tuple[str, str, str]] = [
    # --- Correction 1: confidence is computed, never asserted --------------
    (
        "M1a confidence reverted to the spec's hardcoded 0.5/0.3",
        _CONF_BLOCK,
        "        confidence=0.5 if broad_based else 0.3,",
    ),
    (
        "M1b confidence hardcoded to a constant 0.5",
        _CONF_BLOCK,
        "        confidence=0.5,",
    ),
    (
        "M1c heuristic penalty dropped",
        "                is_heuristic_not_calibrated=True,\n"
        "                depends_on_unobservable=True,\n"
        "                source_independence_count=0,\n"
        "            )\n"
        "        ),",
        "                depends_on_unobservable=True,\n"
        "                source_independence_count=0,\n"
        "            )\n"
        "        ),",
    ),
    (
        "M1d unobservable penalty dropped",
        "                is_heuristic_not_calibrated=True,\n"
        "                depends_on_unobservable=True,\n"
        "                source_independence_count=0,\n"
        "            )\n"
        "        ),",
        "                is_heuristic_not_calibrated=True,\n"
        "                source_independence_count=0,\n"
        "            )\n"
        "        ),",
    ),
    # --- Correction 2: the threshold is config, not a literal --------------
    (
        "M2a threshold reverted to the spec's literal 0.6",
        _THRESHOLD_READ,
        "    threshold = 0.6",
    ),
    (
        "M2b threshold read from the WRONG config leaf (the null rate)",
        _THRESHOLD_READ,
        "    threshold = settings.null_rate",
    ),
    (
        "M2c threshold scaled by 100 (0.006 instead of 0.6)",
        _THRESHOLD_READ,
        "    threshold = settings.breadth_threshold_value / 100.0",
    ),
    # --- Correction 3: the boundary operator -------------------------------
    (
        "M3a boundary changed from the spec's inclusive >= to strict >",
        _BROAD_BASED,
        "    broad_based = breadth > threshold",
    ),
    (
        "M3b breadth comparison inverted (advance counts as decline)",
        _DECLINE_COUNT,
        "    n_declining = sum(1 for change in components.values() if change > 0)",
    ),
    (
        "M3c flat component counted as declining (<= 0 instead of < 0)",
        _DECLINE_COUNT,
        "    n_declining = sum(1 for change in components.values() if change <= 0)",
    ),
    # --- Correction 4: D-029 base-rate disclosure --------------------------
    (
        "M4a null-rate key dropped from the value dict",
        _NULL_KEY,
        "",
    ),
    (
        "M4b null rate reported as a percentage (31.25 not 0.3125)",
        _NULL_KEY,
        '            "breadth_null_rate": round(null_rate * 100.0, 4),',
    ),
    (
        "M4c null rate always 1.0 (the required count is never reached)",
        _NULL_RATE_READ,
        "    null_rate = 1.0",
    ),
    (
        "M4d the ceil becomes a truncation (off-by-one in the required count)",
        _NULL_FN_SIGN,
        "    required = int(breadth_threshold * n_components)",
    ),
    (
        "M4e the null tail loses its upper range (only exactly 'required' counts)",
        "    favourable = sum(binomials[required:])",
        "    favourable = binomials[required]",
    ),
    (
        "M4f the null denominator uses the wrong exponent (n-1 not n)",
        "    return favourable / float(2**n_components)",
        "    return favourable / float(2 ** (n_components - 1))",
    ),
    # --- Correction 5: Section 21.1's naming rule -------------------------
    (
        "M5a model renamed to the spec's 'lei_composite'",
        _MODEL_NAME,
        '        model_name="lei_composite",',
    ),
    (
        "M5b the not-LEI disclaimer removed",
        _DISCLAIMER,
        '_NOT_LEI = "Leading indicator composite."',
    ),
    (
        "M5c the disclaimer loses the level-comparability caveat",
        _DISCLAIMER,
        '_NOT_LEI = (\n    "This is NOT the Conference Board LEI."\n)',
    ),
    # --- Correction 6: the input contract ---------------------------------
    (
        "M6a partial weight map accepted (w.get(k, 0) semantics)",
        _PARTIAL_WEIGHT_GUARD,
        "        missing = []\n        if missing:\n            raise ValueError(",
    ),
    (
        "M6b negative weight accepted",
        _NEGATIVE_WEIGHT_GUARD,
        "        negative = []\n        if negative:\n            raise ValueError(",
    ),
    (
        "M6c all-zero weights accepted (composite is a constant)",
        _ALL_ZERO_GUARD,
        "        if False:\n            raise ValueError(",
    ),
    (
        "M6d non-finite guard removed (NaN counted as not-declining)",
        _FINITE_GUARD,
        "        if False:\n            raise ValueError(",
    ),
    (
        "M6e extra=forbid removed from the input model",
        _EXTRA_FORBID,
        "    components: dict[str, float] = Field(",
    ),
    # --- Correction 7: the three-state read -------------------------------
    (
        "M7a advance requires only the breadth (composite can contradict it)",
        _ADVANCE_GUARD,
        "    elif advance_breadth >= threshold:",
    ),
    (
        "M7b the mixed state collapses into 'no decline' (bidirectional)",
        '    else:\n        lead_direction = "mixed"',
        '    else:\n        lead_direction = "broad_based_advance"',
    ),
    (
        "M7c lead_direction dropped from the value dict",
        _DIRECTION_KEY,
        "",
    ),
    (
        "M7d the mixed-reading warning removed",
        _MIXED_WARNING,
        '            "REMOVED",\n',
    ),
    (
        "M7e broad_based flag dropped from the value dict",
        _DECLINE_KEY,
        "",
    ),
    # --- Correction 8: D-033's two data-layer contracts -------------------
    # These target `snapshot_builder.py` and `validation.py`, not the model.
    # They live in this sweep because they were found by THIS increment's
    # full-suite run, and because the registry entries that made them
    # necessary are Module 7.3's own.
    (
        "M8a the not-a-snapshot-field refusal removed (fallback resolves it)",
        _NOT_A_SNAPSHOT_GUARD,
        "",
    ),
    (
        "M8b the refusal made unconditional (every entry is refused)",
        _NOT_A_SNAPSHOT_GUARD,
        '    if True:\n        raise OpenBBFetchError(\n            "refused",\n        )\n',
    ),
    (
        "M8c the tolerance comparison loses its bound (any lead is tolerated)",
        _TOLERANCE_BRANCH,
        "            if True:",
    ),
    (
        "M8d the tolerance boundary off by one (<= becomes <)",
        _TOLERANCE_BRANCH,
        "            if lead_days < future_date_tolerance_days:",
    ),
    (
        "M8e the tolerance defaults to unlimited (int default changed)",
        _TOLERANCE_FIELD,
        _TOLERANCE_FIELD.replace("default=0", "default=9999"),
    ),
    (
        "M8f the tolerated point is reported as a projection (FORWARD_LOOKING)",
        _TOLERATED_INFO,
        '                code="FORWARD_LOOKING_HORIZON",',
    ),
    (
        "M8g the tolerance is applied to forward_looking series too",
        "    if tolerated_future_dates and not forward_looking:",
        "    if tolerated_future_dates:",
    ),
]

# Files this sweep mutates beyond the model itself. D-033's guard lives in the
# data layer, so the sweep reads them from disk like the model source.


def run_tests() -> bool:
    # The test path is a literal, not a constant, because ruff's S603 rule
    # treats a variable argument to ``subprocess`` as potentially untrusted
    # input and cannot see that a pinned constant is safe.
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/models/test_lei_proxy.py",
            "tests/data_layer/test_phase1_data_layer.py",
            "-q",
            "--no-header",
            "-m",
            "not live",
        ],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def _iter_mutations() -> list[tuple[str, Path, str, str]]:
    """Pair every mutation with the file it belongs to.

    The D-033 guards live in the data layer while the Module 7.3 corrections
    live in the model, so a single ``SRC`` would silently apply a data-layer
    pattern to the model's text and report it as ``PATTERN MISSING`` — a
    failure mode that looks like a typo rather than a targeting bug.
    """
    out: list[tuple[str, Path, str, str]] = []
    for name, old, new in MUTATIONS:
        target = SRC
        if name.startswith("M8"):
            if "not_a_snapshot" in name or "refusal" in name:
                target = _SNAPSHOT_BUILDER
            elif "tolerance defaults" in name:
                target = _CONFIG
            else:
                target = _VALIDATION
        out.append((name, target, old, new))
    return out


def main() -> int:
    originals: dict[Path, str] = {
        p: p.read_text(encoding="utf-8") for p in {SRC, _SNAPSHOT_BUILDER, _VALIDATION, _CONFIG}
    }

    survivors: list[tuple[str, str]] = []
    for name, target, old, new in _iter_mutations():
        pristine = originals[target]
        if old not in pristine:
            print(f"PATTERN MISSING   {name}  [{target.name}]")
            survivors.append((name, "pattern-not-found"))
            continue
        target.write_text(pristine.replace(old, new, 1), encoding="utf-8", newline="")
        caught = not run_tests()
        target.write_text(pristine, encoding="utf-8", newline="")
        print(f"{'KILLED' if caught else 'SURVIVED':17} {name}")
        if not caught:
            survivors.append((name, "survived"))

    print()
    total = len(MUTATIONS)
    print(f"{total - len(survivors)}/{total} killed")
    for name, why in survivors:
        print(f"  SURVIVOR ({why}): {name}")
    return 0 if not survivors else 1


if __name__ == "__main__":
    raise SystemExit(main())
