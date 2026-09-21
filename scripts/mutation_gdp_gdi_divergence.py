"""Mutation sweep for Module 7.1's ``gdp_gdi_divergence``.

The suite exists to prove four corrections are load-bearing rather than
cosmetic. Each mutation below reverts one of them to the specification's own
spelling, and each must be killed:

* **M1** restores the specification's hardcoded ``confidence=0.4 if ... else 0.7``,
  which Section 22.8 forbids. If the suite does not catch M1, the
  ``compute_confidence`` correction is decoration.
* **M2** restores the literal ``1.0`` threshold, which would make the config
  entry decorative and the boundary unreviewable.
* **M3** removes the sign-neutrality warning — the D-031 correction — so a
  reader would again be free to read the residual's direction as a finding.
* **M4** renames ``average_growth_pct`` back to the specification's bare
  ``average``, which invites averaging two levels where the wedge is
  systematically negative.
* **M5** drops the D-029 base-rate disclosure from both the value dict and the
  warnings.
* **M6** weakens the input contract: the non-finite guard, ``extra="forbid"``,
  and the penalty flags.

Every pattern is matched against the pristine source read from the repo. A
``/tmp`` backup path resolves in Git Bash but not in a Windows Python process,
so there is no backup file.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _sweep_gate import (
    check_targets,
    format_problems,
    sweep_lifecycle,
)

SRC = Path("src/macro_engine/models/gdp_nowcast.py")

# Named fragments keep the mutation literals under the line limit (E501).
_CONF_BLOCK = (
    "        confidence=compute_confidence(\n"
    "            ConfidenceInputs(\n"
    "                is_heuristic_not_calibrated=True,\n"
    "                depends_on_unobservable=True,\n"
    "                source_independence_count=0,\n"
    "            )\n"
    "        ),"
)
_THRESHOLD_READ = "    threshold = settings.significance_threshold"
_SIGN_WARNING = (
    '        "Do not read the SIGN of the divergence as a finding: GDP leads GDI "\n'
    '        f"{gdp_led_rate * 100:.1f}% of the time and GDI leads GDP "\n'
    '        f"{(1 - gdp_led_rate) * 100:.1f}%. That is a coin flip, which is what a residual "\n'
    '        "looks like. Magnitude is the information; direction is not.",'
)
_AVERAGE_KEY = '            "average_growth_pct": round(average, 4),'
_BASE_RATE_KEY = '            "divergence_base_rate": base_rate,'
_WEDGE_KEY = '            "level_wedge_mean_pct": round(level_wedge, 4),'
_BASE_RATE_WARNING = (
    '        "GDP and GDI estimate the same aggregate from opposite sides, so their "\n'
    '        f"difference is a statistical RESIDUAL. Measured base rate: |divergence| > "\n'
    '        f"{threshold:.2f}pp in {base_rate * 100:.1f}% of quarters — a routine event, "\n'
    '        "not an anomaly.",'
)
_FINITE_GUARD = (
    "        if not isfinite(value):\n"
    "            raise ValueError(\n"
    '                f"{name} is {value!r}; the divergence is undefined for a non-finite input. "\n'
    '                f"A NaN would make every comparison below evaluate False and be reported "\n'
    "                f\"as 'not significant' — a missing observation disguised as a finding.\"\n"
    "            )"
)
_LEVEL_WARNING = 'f"It is NOT the mean of the two levels: the level wedge averages "'
_EXTRA_FORBID = (
    '    model_config = ConfigDict(extra="forbid")\n\n    gdp_growth_pct: float = Field('
)

MUTATIONS: list[tuple[str, str, str]] = [
    # -- O-72 canary (CONTROL) --------------------------------------------
    # NOT a revert of a project correction: a mutation that is CERTAIN to be
    # caught, so the sweep can REFUSE TO CERTIFY when it survives. A sweep
    # whose anchors resolve but whose test selection no longer reaches the
    # mutated module reports every mutant as killed -- the D-051 trap. The
    # canary is the only entry here that distinguishes 'the suite is strong'
    # from 'the sweep stopped testing'.
    #
    # It replaces a module-level literal with a SYNTAX ERROR, so the kill is
    # STRUCTURAL (`tests/` cannot collect) rather than incidental, and the
    # mutation cannot quietly become inert the way a behavioural one can.
    (
        "CANARY1 the module literal is replaced with a syntax error (CONTROL)",
        '__all__ = [\n    "GdpGdiInputs",',
        "__CANARY__ = <<<SYNTAX ERROR>>>",
    ),
    # --- Correction 1: confidence is computed (Section 22.8 / Finding #8) --
    (
        "M1a confidence reverted to the spec's hardcoded 0.4/0.7",
        _CONF_BLOCK,
        "        confidence=0.4 if significant else 0.7,",
    ),
    (
        "M1b confidence hardcoded to a constant 0.7",
        _CONF_BLOCK,
        "        confidence=0.7,",
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
    (
        "M1e confidence made to vary with the flag (the spec's own shape)",
        _CONF_BLOCK,
        "        confidence=compute_confidence(\n"
        "            ConfidenceInputs(\n"
        "                is_heuristic_not_calibrated=True,\n"
        "                depends_on_unobservable=True,\n"
        "                source_independence_count=3 if significant else 0,\n"
        "            )\n"
        "        ),",
    ),
    # --- Correction 2: the threshold is read, not literal ------------------
    (
        "M2a threshold reverted to the spec's literal 1.0",
        _THRESHOLD_READ,
        "    threshold = 1.0",
    ),
    (
        "M2b threshold read but scaled by 100 (0.01pp instead of 1.0pp)",
        _THRESHOLD_READ,
        "    threshold = settings.significance_threshold / 100.0",
    ),
    (
        "M2c boundary changed from strict > to inclusive >=",
        "    significant = abs(diff) > threshold",
        "    significant = abs(diff) >= threshold",
    ),
    (
        "M2d significance test drops the absolute value (one-sided)",
        "    significant = abs(diff) > threshold",
        "    significant = diff > threshold",
    ),
    (
        "M2e threshold taken from the level wedge by mistake",
        _THRESHOLD_READ,
        "    threshold = abs(settings.level_wedge_mean)",
    ),
    # --- Correction 3: the sign is never interpreted (D-031) ---------------
    (
        "M3a sign-neutrality warning removed",
        _SIGN_WARNING,
        '        "REMOVED",',
    ),
    (
        "M3b sign warning loses the coin-flip evidence",
        _SIGN_WARNING,
        '        "Do not read the SIGN of the divergence as a finding. ",',
    ),
    (
        "M3c sign warning reports a directional rate that is wrong",
        _SIGN_WARNING,
        '        "Do not read the SIGN of the divergence as a finding: GDP leads GDI "\n'
        '        f"always% of the time and GDI leads GDP "\n'
        '        f"never%. That is a finding, not a coin flip, which is what a residual "\n'
        '        "looks like. Magnitude is the information; direction is not.",',
    ),
    # --- Correction 4: the average is labelled for its unit ----------------
    (
        "M4a average renamed back to the spec's bare 'average'",
        _AVERAGE_KEY,
        '            "average": round(average, 4),',
    ),
    (
        "M4b level wedge dropped from the value dict",
        _WEDGE_KEY,
        "",
    ),
    (
        "M4c level-vs-growth warning removed",
        _LEVEL_WARNING,
        'f"REMOVED: not the mean of two levels "',
    ),
    (
        "M4d average computed as the mean of the two LEVELS (biased)",
        "    average = (inputs.gdp_growth_pct + inputs.gdi_growth_pct) / 2",
        "    average = (inputs.gdp_growth_pct + inputs.gdi_growth_pct) / 2 + level_wedge",
    ),
    (
        "M4e divergence sign flipped",
        "    diff = inputs.gdp_growth_pct - inputs.gdi_growth_pct",
        "    diff = inputs.gdi_growth_pct - inputs.gdp_growth_pct",
    ),
    # --- Correction 5: D-029 base-rate disclosure --------------------------
    (
        "M5a base-rate key dropped from the value dict",
        _BASE_RATE_KEY,
        "",
    ),
    (
        "M5b base rate reported as a percentage (21.7 not 0.217)",
        _BASE_RATE_KEY,
        '            "divergence_base_rate": base_rate * 100.0,',
    ),
    (
        "M5c base-rate warning removed entirely",
        _BASE_RATE_WARNING,
        '        "REMOVED",',
    ),
    (
        "M5d base-rate warning loses the number",
        _BASE_RATE_WARNING,
        '        "GDP and GDI estimate the same aggregate from opposite sides, so their "\n'
        '        "difference is a statistical RESIDUAL, at a routine base rate.",',
    ),
    # --- Correction 6: the input contract ----------------------------------
    (
        "M6a non-finite guard removed (NaN passes through as 'not significant')",
        _FINITE_GUARD,
        "        pass",
    ),
    (
        "M6b finite check accepts NaN",
        "        if not isfinite(value):",
        "        if not isfinite(value) and value == value:",
    ),
    (
        "M6c rejection message loses the offending field name",
        '                f"{name} is {value!r}; the divergence is undefined '
        'for a non-finite input. "',
        '                f"input is {value!r}; the divergence is undefined. "',
    ),
    (
        "M6d extra=forbid removed from the input model",
        _EXTRA_FORBID,
        "    gdp_growth_pct: float = Field(",
    ),
    (
        "M6e stale-after read replaced with a literal",
        "    stale_after = settings.divergence_base_rate.stale_after",
        "    stale_after = 2",
    ),
    # --- Contract-level mutations -----------------------------------------
    (
        "M7a inputs_used loses a field",
        '        inputs_used=["gdp_growth_pct", "gdi_growth_pct"],',
        '        inputs_used=["gdp_growth_pct"],',
    ),
    (
        "M7b model_name changed",
        '        model_name="gdp_gdi_divergence",',
        '        model_name="gdp_gdi",',
    ),
    (
        "M7c context dropped",
        "        context=(\n"
        '            "Two measurements of one aggregate. The discrepancy is a residual, so its "\n'
        '            "magnitude is the signal and its direction is not (Module 7.1)."\n'
        "        ),",
        '        context="",',
    ),
]


def run_tests() -> bool:
    # The test path is a literal, not a constant, because ruff's S603 rule
    # treats a variable argument to ``subprocess`` as potentially untrusted
    # input and cannot see that a pinned constant is safe.
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/models/test_gdp_gdi_divergence.py",
            "-q",
            "--no-header",
        ],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def main() -> int:
    # The whole interrupt defence in one call (O-103): heal, protect, spend.
    # On win32 no Python signal handler runs for SIGTERM/SIGINT, so the
    # sidecar -- not a handler -- is the defence with real reach here.
    with sweep_lifecycle([SRC]) as originals:
        return _run_sweep(originals)


def _run_sweep(originals: dict[Path, str]) -> int:
    pristine_src = originals[SRC]

    # A 3-tuple table against a single SRC; target made explicit.
    #
    # Refuse to measure before anything is mutated (D-048, O-29). An anchor
    # that drifted reports as a survivor, which reads as 'the suite has a
    # hole' when the truth is 'the sweep aimed at the wrong text'. A
    # LEFTOVER mutant is reported as such rather than as a drifted anchor
    # (D-081), because those two need opposite responses.
    _table = [(name, SRC, old, new) for name, old, new in MUTATIONS]
    problems = check_targets({SRC: pristine_src}, _table)
    print(f"check_targets: {len(_table)} mutations, {len(problems)} problem(s)")
    if problems:
        print(format_problems(problems))
        print()
        print("REFUSING TO RUN: fix the anchors above first. A sweep")
        print("that cannot prove it mutates the site it names certifies")
        print("nothing (D-048, O-29).")
        return 4

    survivors: list[tuple[str, str]] = []
    for name, old, new in MUTATIONS:
        if old not in pristine_src:
            print(f"PATTERN MISSING   {name}")
            survivors.append((name, "pattern-not-found"))
            continue
        SRC.write_text(pristine_src.replace(old, new, 1), encoding="utf-8", newline="")
        caught = not run_tests()
        SRC.write_text(pristine_src, encoding="utf-8", newline="")
        print(f"{'KILLED' if caught else 'SURVIVED':17} {name}")
        if not caught:
            survivors.append((name, "survived"))

    print()
    print(f"{len(MUTATIONS) - len(survivors)}/{len(MUTATIONS)} killed")
    for name, why in survivors:
        print(f"  SURVIVOR ({why}): {name}")
    # O-72's canary gate. A canary that SURVIVES means the sweep ran but tested
    # nothing: its selection no longer reaches the mutated module, so every
    # "killed" above is a statement about the harness rather than the suite.
    # This is the D-051 trap, and it is why CANARY1 is REQUIRED to be killed
    # rather than tolerated as a survivor.
    if any(name.startswith("CANARY1 ") for name, _ in survivors):
        print()
        print("REFUSING TO CERTIFY: the honesty canary SURVIVED.")
        print("  !! CANARY1 -- the test selection no longer reaches the mutated")
        print("     module, so no kill above is evidence about the suite (O-72).")
        return 3

    return 0 if not survivors else 1


if __name__ == "__main__":
    raise SystemExit(main())
