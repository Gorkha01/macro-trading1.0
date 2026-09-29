"""Mutation sweep for ``ppi_pipeline.py`` (``ppi_pipeline_signal``, Module 5.4).

The suite would pass under the specification's own spelling in places, so this
sweep exists mainly to prove three corrections are **load-bearing** rather than
cosmetic:

* **M1** reverts the two ``Literal`` fields to the specification's free ``str``.
  Under that spelling a typo'd assessment is accepted and reports ``fuller``
  pass-through. If the suite does not catch M1, the ``Literal`` correction is
  decoration.
* **M2** drops the base-rate keys from ``value``, which would remove the D-029
  disclosure while leaving the flag — the exact shape the finding is about.
* **M3** makes pass-through read the gradient, which destroys the
  margin-absorption mechanism the module exists to model.

Every pattern is matched against the pristine source read from the repo, not a
backup: a ``/tmp`` path resolves in Git Bash but not in a Windows Python process.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _sweep_gate import (
    check_only,
    check_only_requested,
    check_targets,
    format_problems,
    sweep_lifecycle,
)

SRC = Path("src/macro_engine/models/ppi_pipeline.py")

# Named fragments keep the mutation literals under the line limit (E501).
_MARGIN_FIELD = "    corporate_margin_trend: MarginTrend = Field("
_DEMAND_FIELD = "    demand_condition: DemandCondition = Field("
_VALUE_DICT = (
    '            "base_rate_strict_descending": base_rate.strict_descending_rate,\n'
    '            "base_rate_crude_above_final": base_rate.crude_above_final_rate,\n'
)
_MARGIN_WARNING = '        "``corporate_margin_trend`` is a HUMAN ASSESSMENT, not an observation "'
_BASE_RATE_WARNING = '        f"The stage gradient\'s own base rate: the strict ordering "'

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
        '__all__ = [\n    "MarginTrend",',
        "__CANARY__ = <<<SYNTAX ERROR>>>",
    ),
    # --- The Literal correction (the centrepiece) -------------------------
    (
        "M1a margin field reverted to the spec's free str",
        _MARGIN_FIELD,
        "    corporate_margin_trend: str = Field(",
    ),
    (
        "M1b demand field reverted to the spec's free str",
        _DEMAND_FIELD,
        "    demand_condition: str = Field(",
    ),
    (
        "M1c margin Literal admits a typo'd extra member",
        'MarginTrend = Literal["expanding", "stable", "compressing"]',
        'MarginTrend = Literal["expanding", "stable", "compressing", "compress"]',
    ),
    (
        "M1d demand Literal admits a case variant",
        'DemandCondition = Literal["strong", "neutral", "weak"]',
        'DemandCondition = Literal["strong", "neutral", "weak", "Strong"]',
    ),
    # NOTE: an attempt to mutate the *description text* of the margin field was
    # removed from this sweep after being diagnosed as an INERT MUTATION.
    # pydantic builds the ``literal_error`` message from the ``Literal``
    # annotation's members, not from ``Field(description=...)``, so shortening
    # the description cannot change anything a test could observe — verified by
    # mutating the source, re-importing the module, and comparing the
    # ValidationError text with and without the change: byte-identical. An inert
    # mutation is not a test gap, and keeping it in the list would misreport the
    # kill rate. That probe is not kept as a script because the finding is a
    # one-time property of pydantic's error construction rather than a recurring
    # check. The two survivors that WERE real test gaps (M4e, M5b) became tests
    # in tests/models/test_ppi_pipeline.py instead.
    # --- The D-029 base-rate disclosure -----------------------------------
    (
        "M2a base-rate keys removed from value",
        _VALUE_DICT,
        "",
    ),
    (
        "M2b strict base rate reported as a percentage (30.0 not 0.30)",
        '"base_rate_strict_descending": base_rate.strict_descending_rate,',
        '"base_rate_strict_descending": base_rate.strict_descending_rate * 100.0,',
    ),
    (
        "M2c crude-above-final rate swapped for the strict rate",
        '"base_rate_crude_above_final": base_rate.crude_above_final_rate,',
        '"base_rate_crude_above_final": base_rate.strict_descending_rate,',
    ),
    (
        "M2d base-rate warning removed entirely",
        _BASE_RATE_WARNING,
        '        f"REMOVED: ',
    ),
    (
        "M2e base-rate warning states no number",
        'f"The stage gradient\'s own base rate: the strict ordering "\n'
        '        f"crude > intermediate > final held in "\n'
        '        f"{base_rate.strict_descending_rate:.1%} of the 190 months this build "',
        'f"The stage gradient\'s own base rate: the strict ordering "\n'
        '        f"crude > intermediate > final held in "\n'
        '        f"some share of the months this build "',
    ),
    # --- Pass-through mechanism -------------------------------------------
    (
        "M3a pass-through reads the gradient (destroys margin absorption)",
        '    absorbing = inputs.demand_condition == "weak" or '
        'inputs.corporate_margin_trend == "compressing"',
        '    absorbing = upstream_building and inputs.demand_condition == "weak"',
    ),
    (
        "M3b pass-through ignores the margin trend",
        'inputs.demand_condition == "weak" or inputs.corporate_margin_trend == "compressing"',
        'inputs.demand_condition == "weak"',
    ),
    (
        "M3c pass-through ignores the demand condition",
        'inputs.demand_condition == "weak" or inputs.corporate_margin_trend == "compressing"',
        'inputs.corporate_margin_trend == "compressing"',
    ),
    (
        "M3d pass-through labels inverted",
        '    pass_through: PipelinePassThrough = "muted" if absorbing else "fuller"',
        '    pass_through: PipelinePassThrough = "fuller" if absorbing else "muted"',
    ),
    # --- The ordering test and the dead band ------------------------------
    (
        "M4a strict ordering loosened to crude > final only",
        "    upstream_building = crude > intermediate > final",
        "    upstream_building = crude > final",
    ),
    (
        "M4b strict ordering inverted",
        "    upstream_building = crude > intermediate > final",
        "    upstream_building = crude < intermediate < final",
    ),
    (
        "M4c dead band removed (tolerance forced to zero)",
        "    tolerance = settings.inflation.pipeline_gradient_tolerance",
        "    tolerance = 0.0",
    ),
    (
        "M4d dead band made exclusive (<= becomes <)",
        "    within_band = abs(crude - intermediate) <= tolerance and abs(intermediate - final) <= tolerance",
        "    within_band = abs(crude - intermediate) < tolerance and abs(intermediate - final) < tolerance",
    ),
    (
        "M4e dead band applies to only one adjacent pair",
        "    within_band = abs(crude - intermediate) <= tolerance and abs(intermediate - final) <= tolerance",
        "    within_band = abs(crude - intermediate) <= tolerance",
    ),
    (
        "M4f non-monotonic label collapsed into the downstream case",
        '        gradient_direction = "non_monotonic"',
        '        gradient_direction = "passing_through_downstream"',
    ),
    (
        "M4g stage spread sign flipped",
        "    stage_spread = crude - final",
        "    stage_spread = final - crude",
    ),
    # --- The within-band contradiction (defect #6) ------------------------
    # The dead band runs FIRST, so an earlier version returned a single
    # "no_clear_gradient" for every within-band reading — including a
    # strictly-descending month whose boolean was True. These four mutants
    # re-create that contradiction and each must be killed by
    # `test_gradient_direction_never_contradicts_the_boolean` or by the
    # dedicated within-band test.
    (
        "M4h within-band state collapsed to the old bare no-gradient label",
        '            "building_within_tolerance" if upstream_building else "flat_within_tolerance"',
        '            "no_clear_gradient"',
    ),
    (
        "M4i within-band state ignores the boolean (always flat)",
        '            "building_within_tolerance" if upstream_building else "flat_within_tolerance"',
        '            "flat_within_tolerance"',
    ),
    (
        "M4j within-band state ignores the boolean (always building)",
        '            "building_within_tolerance" if upstream_building else "flat_within_tolerance"',
        '            "building_within_tolerance"',
    ),
    (
        "M4k band width forced to zero (band never fires)",
        "    tolerance = settings.inflation.pipeline_gradient_tolerance",
        "    tolerance = 0.0",
    ),
    (
        "M4l band made unbounded (every reading is within-band)",
        "    tolerance = settings.inflation.pipeline_gradient_tolerance",
        "    tolerance = 1e9",
    ),
    # --- Conditional warnings ---------------------------------------------
    (
        "M5a contradiction warning removed",
        '    if upstream_building and inputs.corporate_margin_trend == "expanding":',
        "    if False:",
    ),
    (
        "M5b contradiction warning fires regardless of the margin trend",
        '    if upstream_building and inputs.corporate_margin_trend == "expanding":',
        "    if upstream_building:",
    ),
    (
        "M5c non-monotonic warning removed",
        '    if gradient_direction == "non_monotonic":',
        "    if False:",
    ),
    (
        "M5d downstream-arrival warning removed",
        '    if gradient_direction == "passing_through_downstream":',
        "    if False:",
    ),
    (
        "M5e flat-ends warning removed",
        "    if abs(stage_spread) <= tolerance:",
        "    if False:",
    ),
    (
        "M5f margin human-assessment warning removed",
        _MARGIN_WARNING,
        '        "REMOVED:',
    ),
    (
        "M5g 1:1-predictor warning removed",
        '        "PPI is NOT a 1:1 CPI predictor — margin absorption breaks the link "',
        '        "REMOVED: PPI is a 1:1 CPI predictor "',
    ),
    # --- Confidence and contract ------------------------------------------
    (
        "M6a confidence hardcoded to the spec's 0.4",
        "        confidence=compute_confidence(\n"
        "            ConfidenceInputs(\n"
        "                is_heuristic_not_calibrated=True,\n"
        "                depends_on_unobservable=True,\n"
        "            ),\n"
        "        ),",
        "        confidence=0.4,",
    ),
    (
        "M6b heuristic penalty dropped",
        "                is_heuristic_not_calibrated=True,\n",
        "",
    ),
    (
        "M6c unobservable penalty dropped",
        "                depends_on_unobservable=True,\n",
        "",
    ),
    (
        "M6d inputs_used loses a field",
        '            "demand_condition",\n        ],',
        "        ],",
    ),
    (
        "M6e extra=forbid removed from the input model",
        '    model_config = ConfigDict(extra="forbid")\n\n    crude_stage_yoy_pct',
        "    crude_stage_yoy_pct",
    ),
]


def run_tests() -> bool:
    # The test path is a literal, not the ``_TEST_FILE`` constant, because ruff's
    # S603 rule treats a variable argument to ``subprocess`` as potentially
    # untrusted input and cannot see that the constant is a pinned path. The
    # constant above is used for documentation; the invocation stays literal.
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/models/test_ppi_pipeline.py",
            "-q",
            "--no-header",
        ],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def _check_targets_only() -> int:
    """Print the anchor verdict and STOP, touching nothing (O-138)."""
    return check_only([(name, SRC, old, new) for name, old, new in MUTATIONS])


def main() -> int:
    # O-138: the check-only mode must be answered BEFORE the lifecycle
    # writes, and before ANY file is read -- see check_only's docstring.
    if check_only_requested():
        return _check_targets_only()
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
