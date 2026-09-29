"""Mutation sweep for the RECORDED PERFORMANCE EXPLANATION (D-087.19, O-111(b)).

**What is mutated here is prose, not code — and that is the point.**

Every other sweep in this directory mutates a line of ``src/macro_engine`` and
asks whether the *test suite* notices. This one mutates the **recorded
explanation of the build's cost** and asks whether **`tests/test_performance_record.py`**
notices. The explanation is load-bearing: it is the sentence a reviewer reads
before deciding whether the snapshot cache is justified, and the version of it
that shipped was wrong in a way that *sounded* precise (223.6 s vs 9.5 s; "~24
sequential requests") while comparing a COLD run with a WARM one.

That wrong explanation was corrected in prose once already (D-087.19 claimed the
``settings.yaml`` note "has been corrected") and the figures were **still** on
five surfaces when this file was written, because nothing read the note. A
prose-only fix is unenforceable; a sweep is how this project converts a claim
into a check.

The mutations are graded, not merely inverted:

* ``CANARY1`` — a **syntax error** in the guard module itself, so the kill is
  STRUCTURAL. If this survives, the sweep is testing nothing (the D-051 trap).
* ``M1`` — the original live claim, restored verbatim to the config note. This is
  the exact regression: the withdrawn pair stated as current.
* ``M2`` — the same claim with the **retraction still present elsewhere in the
  file**. This is the **O-107 narrow-predicate** test: a guard that matched
  "223.6 appears somewhere near a retraction" would let this through, so it must
  fail *per sentence* rather than per file.
* ``M3`` — the withdrawn figures with the remedy clause (*batching the ~24
  sequential requests*) that D-087.18 disproved by arithmetic on its own numbers.
* ``M4`` — the honest statement **removed** but the old claim not restored: the
  half-fix. Forbidding the old sentence is not enough; the record must say what
  IS true, or the next reader gets no figure at all.
* ``M5`` — the cold figure kept, the **warm half dropped**: quoting "46-81 s"
  alone reintroduces exactly the ambiguity the correction exists to remove.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from _sweep_gate import (
    check_only,
    check_only_requested,
    check_targets,
    format_problems,
    sweep_lifecycle,
)
from _sweep_gate import run_pytest as _run_pytest_inproc

SETTINGS = Path("config/settings.yaml")

# The corrected note, as it must read. Any mutation below is a transform of a
# SLICE of this text, so a drift in the shipped wording makes the anchor miss and
# the sweep refuses (D-048) rather than silently testing nothing.
_HONEST_NOTE = """      MEASURED (D-087.19): a full live snapshot build is dominated by COLD
      START, so a build time quoted without its thermal state is ambiguous, not
      merely imprecise. The honest operational statement is FIRST build
      ~46-81s, SUBSEQUENT builds ~4s (warm means: 4.46s package-first, 3.71s
      local-first, 3 runs each)."""

# The complete corrected note BODY, from the honest paragraph through the
# retraction and the remedy. M5 needs all of it, because the retraction
# paragraph legitimately contains the word "warm" -- a mutant that deleted only
# the honest paragraph would leave "compared a COLD run with a WARM one" behind
# and the guard would (correctly) still see the warm half, so it would be an
# INVALID mutation rather than a survivor. Measured: that is exactly what the
# first draft of M5 did, and the sweep reported it SURVIVED while the guard was
# right. The lesson is the project's: **verify what a predicate actually
# matched before believing the verdict** (lesson 5cm).
_NOTE_BODY = (
    _HONEST_NOTE
    + """ The figures that used to sit here -- 223.6s
      over the local API against 9.5s in-process -- compared a COLD run with a
      WARM one and did NOT reproduce; the ~23x they implied is 1.20x when both
      are measured warm. A request-per-build endpoint is unusable for a
      Workspace UI that polls, so the snapshot is reused within
      snapshot_max_age_hours."""
)

# The remedy clause, VERBATIM from the shipped note. D-087.18 disproved
# "batching the ~24 sequential requests": it targets the build overhead, which is
# 2.41 s of 56 (4%), so naming it as the durable fix misdirects the next reader.
#
# NOTE the leading space, not a 6-space indent: in the shipped note this clause
# begins mid-line, immediately after "...are measured warm." -- the YAML block
# scalar wraps on its own, so the phrase is NOT line-initial. An anchor written
# to the visual indent misses by one space, which is exactly the kind of
# near-miss `check_targets` exists to catch rather than silently skip.
_REMEDY_CLAUSE = """ A request-per-build endpoint is unusable for a
      Workspace UI that polls, so the snapshot is reused within
      snapshot_max_age_hours."""

MUTATIONS: list[tuple[str, str, str]] = [
    # -- O-72 canary (CONTROL) --------------------------------------------
    # A mutation that is CERTAIN to be caught, so the sweep can REFUSE TO
    # CERTIFY when it survives. The file's FIRST top-level key is re-indented and
    # an unbalanced mapping opened, which is a genuine YAML SYNTAX error -- so
    # the kill is STRUCTURAL (`settings.yaml` cannot be loaded by any suite, and
    # `tests/test_infrastructure.py` fails at import/settings time) rather than
    # incidental and behaviour-dependent.
    #
    # Careful, and measured: injecting the error *inside* a block scalar does NOT
    # raise -- a `<<<ERROR>>>` token inside a folded `>` scalar is ordinary text,
    # so that form of canary parses fine and silently becomes inert, which is the
    # very failure this control exists to detect. The canary is asserted to break
    # the parse by the pre-flight below rather than assumed to.
    (
        "CANARY1 the settings file is replaced with a syntax error (CONTROL)",
        "api:",
        "api:\n  !!canary-unterminated-mapping\n    :::",
    ),
    # -- M1: the original live claim, verbatim -----------------------------
    (
        "M1 the withdrawn 223.6s/9.5s pair restored as a live current claim",
        _HONEST_NOTE,
        """      MEASURED: a full live snapshot build took 223.6s over the local
      OpenBB API and 9.5s in-process, so a request-per-build endpoint is
      unusable for a Workspace UI that polls.""",
    ),
    # -- M2: the O-107 narrow predicate ------------------------------------
    # The claim is stated as current in ONE sentence, while the retraction below
    # still mentions the same figures. A guard matching 223.6 against the whole
    # FILE (or the whole note) would be satisfied by the nearby retraction.
    (
        "M2 the claim and its retraction coexist (defeats a whole-file match)",
        _HONEST_NOTE,
        """      MEASURED: a full live snapshot build took 223.6s over the local
      OpenBB API and 9.5s in-process.""",
    ),
    # -- M3: the disproved remedy ------------------------------------------
    (
        "M3 the disproved remedy (batching the ~24 sequential requests) restored",
        _REMEDY_CLAUSE,
        """      The durable fix is batching or parallelising the ~24 sequential
      requests; a request-per-build endpoint is unusable for a Workspace UI
      that polls, so the snapshot is reused within snapshot_max_age_hours.""",
    ),
    # -- M4: the half-fix ---------------------------------------------------
    (
        "M4 the honest statement deleted with no replacement (the half-fix)",
        _HONEST_NOTE,
        "      MEASURED (D-087.19): a full live snapshot build is slow.",
    ),
    # -- M5: the ambiguous single number ------------------------------------
    # The WHOLE honest half is removed, leaving the cold figure quoted alone.
    # Anchored on _NOTE_BODY (honest + retraction + remedy), so the retraction's
    # own mention of "warm" goes with it -- otherwise the mutation would be
    # invalid rather than demanding (see _NOTE_BODY).
    (
        "M5 the cold figure kept and the warm half dropped (the original ambiguity)",
        _NOTE_BODY,
        """      MEASURED (D-087.19): a full live snapshot build is dominated by COLD
      START. The honest operational statement is FIRST build ~46-81s.""",
    ),
]


def run_tests() -> bool:
    """The guard, and the config loader it must not break.

    Two selections on purpose. The first is the guard this sweep exists to
    exercise. The second is the settings-parity test, because the canary breaks
    the YAML *file* and a guard that only read Python would not notice a file
    that no longer loads -- so the sweep would certify a mutation that had
    broken every config read in the project.
    """
    proc = _run_pytest_inproc(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_performance_record.py",
            "tests/test_infrastructure.py",
            "-q",
            "--no-header",
        ],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def _parses(text: str) -> bool:
    """Whether ``text`` is loadable YAML -- used to prove the canary is real.

    Cheap, local, and stdlib-only: it answers the ONE question the canary's
    validity depends on, so a canary that has quietly become inert stops the
    sweep instead of being credited with a kill it did not earn.
    """
    try:
        yaml.safe_load(text)
    except yaml.YAMLError:
        return False
    return True


def _check_targets_only() -> int:
    """Print the anchor verdict and STOP, touching nothing (O-138)."""
    return check_only([(name, SETTINGS, old, new) for name, old, new in MUTATIONS])


def main() -> int:
    # O-138: the check-only mode must be answered BEFORE the lifecycle
    # writes, and before ANY file is read -- see check_only's docstring.
    if check_only_requested():
        return _check_targets_only()
    # The whole interrupt defence in one call (O-103): heal, protect, spend.
    # On win32 no Python signal handler runs for SIGTERM/SIGINT, so the
    # sidecar -- not a handler -- is the defence with real reach here.
    with sweep_lifecycle([SETTINGS]) as originals:
        return _run_sweep(originals)


def _run_sweep(originals: dict[Path, str]) -> int:
    pristine = originals[SETTINGS]

    # Refuse to measure before anything is mutated (D-048, O-29). An anchor that
    # drifted reports as a survivor, which reads as 'the guard has a hole' when
    # the truth is 'the sweep aimed at the wrong text'.
    _table = [(name, SETTINGS, old, new) for name, old, new in MUTATIONS]
    problems = check_targets({SETTINGS: pristine}, _table)
    print(f"check_targets: {len(_table)} mutations, {len(problems)} problem(s)")
    if problems:
        print(format_problems(problems))
        print()
        print("REFUSING TO RUN: fix the anchors above first. A sweep")
        print("that cannot prove it mutates the site it names certifies")
        print("nothing (D-048, O-29).")
        return 4

    # VERIFY THE PROTECTION BEFORE CREDITING IT (lesson 5cl). The canary is only
    # a control if it actually breaks the parse -- an error token inside a folded
    # block scalar is ordinary text and parses fine, which would make the canary
    # inert while still printing KILLED for every behaviour-dependent mutation.
    # So the property is asserted here rather than assumed, and a canary that
    # stopped being structural stops the sweep before it can certify anything.
    canary_old, canary_new = MUTATIONS[0][1], MUTATIONS[0][2]
    if canary_old not in pristine:
        print("REFUSING TO RUN: the canary anchor is absent; the control is")
        print("not installed, so a green run would mean nothing (O-72).")
        return 4
    if _parses(pristine.replace(canary_old, canary_new, 1)):
        print("REFUSING TO RUN: the CANARY no longer breaks the YAML parse.")
        print("  !! A canary that parses is INERT -- it would be reported")
        print("     KILLED while proving nothing about the selection. Make")
        print("     the mutation a real syntax error before trusting a run.")
        return 4

    survivors: list[tuple[str, str]] = []
    for name, old, new in MUTATIONS:
        if old not in pristine:
            print(f"PATTERN MISSING   {name}")
            survivors.append((name, "pattern-not-found"))
            continue
        SETTINGS.write_text(pristine.replace(old, new, 1), encoding="utf-8", newline="")
        caught = not run_tests()
        SETTINGS.write_text(pristine, encoding="utf-8", newline="")
        print(f"{'KILLED' if caught else 'SURVIVED':17} {name}")
        if not caught:
            survivors.append((name, "survived"))

    print()
    print(f"{len(MUTATIONS) - len(survivors)}/{len(MUTATIONS)} killed")
    for name, why in survivors:
        print(f"  SURVIVOR ({why}): {name}")
    # O-72's canary gate. A canary that SURVIVES means the sweep ran but tested
    # nothing: its selection no longer reaches the mutated file, so every
    # "killed" above is a statement about the harness rather than the guard.
    if any(name.startswith("CANARY1 ") for name, _ in survivors):
        print()
        print("REFUSING TO CERTIFY: the honesty canary SURVIVED.")
        print("  !! CANARY1 -- the test selection no longer reaches the mutated")
        print("     file, so no kill above is evidence about the guard (O-72).")
        return 3

    return 0 if not survivors else 1


if __name__ == "__main__":
    raise SystemExit(main())
