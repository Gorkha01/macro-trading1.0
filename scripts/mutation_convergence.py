"""Mutation sweep for ``classify_convergence`` (Module 12, Section 22.10, D-051).

Run this in the FOREGROUND ONLY. D-047's Postscript 2 says it, and D-049
provided the demonstration: a sweep was backgrounded, a mutation it had written
to a source file was still on disk when the full suite ran in another shell, and
the suite failed against code nobody had written on purpose. The failure was
real, the cause was fictional, and ten minutes went into diagnosing it. The
sweep writes to ``src/`` by design -- that is what makes it a mutation sweep --
so nothing else may read those files while it runs.

Why this sweep exists at all
----------------------------
``four_pillar_scorecard``'s sweep (D-050) was the first one to be written after
D-048 established ``check_targets``, and it caught the D-050 composition defect
only because one mutation happened to delete the gate whose order was hiding two
inert thresholds. This sweep is written for that lesson directly: the module
docstring names **seven specification defects**, and the mutation groups below
are those defects, one group per defect. When a mutation survives, the group it
belongs to names the defect whose repair is not pinned by a test.

A note on what "survived" means here
------------------------------------
Two categories of mutation are expected to survive, and both are recorded rather
than hidden:

* ``_EXPECTED_INERT`` -- mutations whose ``old`` string matches but whose effect
  is provably nil, because the composition makes the mutated expression
  unreachable or already-true. Each carries a written proof. These are trapdoors:
  if the proof ever stops holding, ``check_targets`` refuses to run rather than
  reporting a false survivor.
* Mutants targeting **string content** rather than logic (a warning's wording).
  The project's standing position (D-049, D-050) is that warning *text* is not
  the safety mechanism -- the warning *branch* is, and that is tested separately
  by ``test_every_warning_path_is_triggered_by_some_test``. Wording mutants are
  therefore not expected to be killed and are not counted as defects.

The gate order is a real finding, not an oversight
--------------------------------------------------
Mutations M4.2 and M4.3 rewrite the two dissent ceilings. Because ``CONFLICTED``
is tested first (Defect 6), no dissenter ever reaches either gate, so both
mutations are provably inert at the shipped configuration. They are kept as
**canaries**: a tripwire test asserts the reachable dissenter set is exactly
``{0}`` and fails the moment the composition changes, at which point these two
mutations stop being inert and start being the tests that matter. The group is
reported as "inert, disclosed" rather than "survived", and D-051 discloses it in
``config/settings.yaml``'s own note for ``max_dissenting_signals_medium``.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from _sweep_gate import sweep_lifecycle

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src/macro_engine/models/convergence.py"
CONFIG = REPO / "src/macro_engine/config.py"

#: The test selection a surviving mutation must be *capable* of killing. Only the
#: module under test is needed: the four mutants targeting ``config.py`` all land
#: on ``ConvergenceSettings``, whose validators and accessors are tested from
#: ``tests/models/test_convergence.py``. There is no ``tests/test_config.py``.
#:
#: This list is used for the ``check_tests_collect`` gate only. The actual
#: ``subprocess`` call inlines the path as a literal, because ruff's S603 rule
#: treats a variable argument as potentially untrusted input -- the convention
#: the other sweeps in this directory already follow.
PYTEST_TARGETS = [
    "tests/models/test_convergence.py",
]


@dataclass(frozen=True)
class Mutation:
    """One single-substring rewrite of one file."""

    group: str
    name: str
    path: Path
    old: str
    new: str
    intent: str
    #: ``None`` means "expect the tests to fail", which is the normal case.
    #: ``True`` means the mutation is provably inert (see the module docstring);
    #: ``False`` means it is expected to *pass* but for a documented reason.
    expect_killed: bool | None = None
    inert_proof: str = ""


@dataclass
class Result:
    """The outcome of applying and testing one mutation."""

    mutation: Mutation
    applied: bool
    exit_code: int
    output: str = field(default="")

    @property
    def killed(self) -> bool:
        """True only for a genuine test failure.

        Exit 4 is pytest's usage error (a missing path, a plugin crash, no tests
        collected). Counting it as a kill is how the first draft of this sweep
        reported 56/56 against a control that could not fail.
        """
        return self.exit_code not in (0, 4)


# --------------------------------------------------------------------------
# Transcribed targets. Every one of these is a byte-for-byte copy of text in
# the shipped source; check_targets refuses to run if any has drifted.
# --------------------------------------------------------------------------

# --- convergence.py, the direction derivation (Defects 2 and 7) -----------
_DIRECTIONS = "    directions = [_direction(s.value) for s in signals]"
_DIRECTION_BOOL = "    if isinstance(value, bool):"
_DIRECTION_POS = "        if value > 0:"
_DIRECTION_RET_PARENT = "    return 0\n\n\nclass ConvergenceInputs(BaseModel):"

# --- convergence.py, the denominator (Defect 3) ---------------------------
_NON_NEUTRAL_COUNT = "    n = len(non_neutral)"
_UP_COUNT = "    up = sum(1 for d in non_neutral if d > 0)"
_DOWN_COUNT = "    down = sum(1 for d in non_neutral if d < 0)"
_OPPOSED = "    opposed = up > 0 and down > 0"
_AGREE_FRAC = "    agree_frac = max(up, down) / n if n else 0.0"
_MARGIN = "    margin = abs(up - down) / n if n else 0.0"
_DISSENT = "    dissent = n - max(up, down) if n else 0"

# --- convergence.py, the verdict ladder (Defects 4, 5, 6) -----------------
_NO_SIGNAL_BRANCH = '    if n == 0:\n        verdict = "NO_SIGNAL"'
_OPPOSED_BRANCH = '    elif opposed:\n        verdict = "CONFLICTED"'
_HIGH_BRANCH = (
    "    elif dissent <= settings.high_dissent_ceiling and distinct >= settings.high_family_floor:"
)
_MEDIUM_BRANCH = (
    "    elif dissent <= settings.medium_dissent_ceiling and distinct >= "
    "settings.medium_family_floor:"
)
_LOW_REDUNDANCY_BRANCH = "    elif distinct < settings.medium_family_floor:"

# --- convergence.py, the Section 15.19-D census (Defects 1 and 7) ---------
_DIRECTIONAL = "    directional = [s for s, d in zip(signals, directions, strict=True) if d != 0]"
_CENSUS_CALL = "    census = count_independent_families(directional)"
_CENSUS_GUARD = "    if not isinstance(census_value, dict):"
_DISTINCT_GUARD = "    if not isinstance(distinct, int):"
_DISTINCT_READ = '    distinct = census_value.get("distinct_families")'
_FAMILIES_READ = '    directional_families = set(census_value.get("families") or [])'
_EXCLUDED = "    excluded_families = sorted(neutral_families - directional_families)"

# --- convergence.py, confidence (Section 22.8) ----------------------------
_FLAG_ANY = (
    "            data_quality_flags_present=any(s.data_quality_flags_present for s in signals),"
)
_HEURISTIC = "            is_heuristic_not_calibrated=True,"
_UNOBSERVABLE = "            depends_on_unobservable=False,"
_INDEPENDENCE = "            source_independence_count=distinct,"

# --- convergence.py, the published value (nine keys) ---------------------
_PUBLISHED: list[tuple[str, str]] = [
    ('            "classification": verdict,', '            "classification": "LOW",'),
    (
        '            "agreement_fraction": round(agree_frac, 4),',
        '            "agreement_fraction": round(margin, 4),',
    ),
    (
        '            "agreement_margin": round(margin, 4),',
        '            "agreement_margin": round(agree_frac, 4),',
    ),
    ('            "dissenting_signals": dissent,', '            "dissenting_signals": n,'),
    ('            "non_neutral_signals": n,', '            "non_neutral_signals": len(signals),'),
    ('            "total_signals": len(signals),', '            "total_signals": n,'),
    ('            "independent_families": distinct,', '            "independent_families": n,'),
    ('            "untagged_signals": untagged_count,', '            "untagged_signals": 0,'),
    (
        '            "families_excluded_as_neutral": excluded_families,',
        '            "families_excluded_as_neutral": [],',
    ),
    ('            "directions": directions,', '            "directions": sorted(directions),'),
]

# --- convergence.py, warnings ---------------------------------------------
_WARN_CONFLICTED = '    if verdict == "CONFLICTED":'
_WARN_NO_SIGNAL = '    elif verdict == "NO_SIGNAL":'
_WARN_EXCLUDED = "    if excluded_families:"
_WARN_NEUTRAL_DENOM = "    if 0 < n < total:"
_INPUTS_USED = '        inputs_used=[f"signal[{i}]" for i in range(len(signals))],'
_CONTEXT = "        context=("

# --- config.py, the accessors and the validators --------------------------
_ACCESSOR_HIGH_DISSENT = "        return int(self.max_dissenting_signals_high.value)"
_ACCESSOR_MEDIUM_DISSENT = "        return int(self.max_dissenting_signals_medium.value)"
# The two family accessors and two of the validators below appear VERBATIM in
# ``ScorecardSettings`` as well (D-050), so ``check_targets`` flags them as
# ambiguous. Including the preceding line -- which differs between the two
# classes (``signals`` vs ``pillars``) -- makes each target unique without
# weakening what the mutation attacks. This is exactly the failure D-048's gate
# exists to catch: without the extra context, ``str.replace`` would have
# rewritten the SCORECARD accessor and the sweep would have reported a survival
# about code nobody mutated.
_ACCESSOR_HIGH_FAMILY = (
    "    def high_family_floor(self) -> int:\n"
    '        """Independent families required for ``HIGH``."""\n'
    "        return int(self.min_independent_families_high.value)"
)
_ACCESSOR_MEDIUM_FAMILY = (
    "    def medium_family_floor(self) -> int:\n"
    '        """Independent families required for ``MEDIUM``."""\n'
    "        return int(self.min_independent_families_medium.value)"
)
_VALIDATOR_ORDER = (
    "        _high = int(self.max_dissenting_signals_high.value)\n"
    "        _medium = int(self.max_dissenting_signals_medium.value)\n"
    "        if _high > _medium:"
)
_VALIDATOR_NEGATIVE = (
    "        if _high > _medium:\n"
    "            raise ValueError(\n"
    '                f"convergence.max_dissenting_signals_high ({_high}) must not exceed "\n'
    '                f"max_dissenting_signals_medium ({_medium}): HIGH is the STRICTER "\n'
    '                "verdict, so it cannot tolerate more dissent than MEDIUM. Inverting "\n'
    '                "them would make the MEDIUM band unreachable and silently promote "\n'
    '                "every MEDIUM read to HIGH."\n'
    "            )\n"
    "        if _high < 0:"
)
_VALIDATOR_MEDIUM_ONE = "        if _medium > 1:"
_VALIDATOR_FAMILY_ORDER = (
    "        _fam_high = int(self.min_independent_families_high.value)\n"
    "        _fam_medium = int(self.min_independent_families_medium.value)\n"
    "        if _fam_high < _fam_medium:"
)
_VALIDATOR_FAMILY_ZERO = "        if _fam_medium < 1:"


def _m(
    group: str,
    name: str,
    path: Path,
    old: str,
    new: str,
    intent: str,
    *,
    expect_killed: bool | None = None,
    inert_proof: str = "",
) -> Mutation:
    if old == new:
        raise ValueError(f"mutation {name} rewrites nothing")
    return Mutation(
        group=group,
        name=name,
        path=path,
        old=old,
        new=new,
        intent=intent,
        expect_killed=expect_killed,
        inert_proof=inert_proof,
    )


def build_mutations() -> list[Mutation]:
    """Every mutation, grouped by the specification defect it attacks."""
    m: list[Mutation] = []

    # -- M1: position independence (Defect 2) ------------------------------
    # The defect is that the specification reads `directions[0]`. The repair
    # removed the reference entirely, so the mutant re-introduces it. If any
    # test can be fooled by a reordered list, this is the mutation that says so.
    m.append(
        _m(
            "M1",
            "M1.1 direction taken from the FIRST signal",
            SRC,
            _DIRECTIONS,
            "    directions = [_direction(signals[0].value)] * len(signals)",
            "Re-introduces Defect 2: the reference signal is the first one, so the "
            "verdict depends on list order and a neutral first signal collapses "
            "the read.",
        )
    )
    m.append(
        _m(
            "M1",
            "M1.2 sign test reads `>= 0`",
            SRC,
            _DIRECTION_POS,
            "        if value >= 0:",
            "A level of exactly zero becomes tightening. On a list of exact "
            "zeroes this makes NO_SIGNAL unreachable.",
        )
    )
    m.append(
        _m(
            "M1",
            "M1.3 bool guard is re-spelled, semantically identical",
            SRC,
            _DIRECTION_BOOL,
            "    if value.__class__ is bool:",
            "``isinstance(value, bool)`` re-spelled as a class identity test. "
            "Semantically identical for every value the function can receive, so "
            "this MUST survive. It is the harness's honesty control: if the sweep "
            "reports this as killed, it is reporting kills it cannot justify, and "
            "no other number it prints can be trusted. (An earlier version of "
            "this control appended a ``# noqa`` comment instead, which the "
            "project's ruff gate killed -- a real failure, but from a different "
            "gate, which is not what a control is for.)",
            expect_killed=False,
        )
    )

    # -- M2: the denominator (Defect 3) ------------------------------------
    m.append(
        _m(
            "M2",
            "M2.1 denominator is the WHOLE list",
            SRC,
            _NON_NEUTRAL_COUNT,
            "    n = len(directions)",
            "Defect 3 restored: neutral signals dilute the agreement fraction.",
        )
    )
    m.append(
        _m(
            "M2",
            "M2.2 up-count includes neutrals",
            SRC,
            _UP_COUNT,
            "    up = sum(1 for d in directions if d >= 0)",
            "Neutrals vote tightening: an all-neutral list stops being NO_SIGNAL "
            "and a tie stops being a tie.",
        )
    )
    m.append(
        _m(
            "M2",
            "M2.3 down-count includes neutrals",
            SRC,
            _DOWN_COUNT,
            "    down = sum(1 for d in directions if d <= 0)",
            "The mirror of M2.2, to catch a test that only pins one side.",
        )
    )
    m.append(
        _m(
            "M2",
            "M2.4 opposition requires only ONE side",
            SRC,
            _OPPOSED,
            "    opposed = up > 0 or down > 0",
            "Every directional read becomes CONFLICTED. This is the mutation that "
            "turns a blocking verdict into a universal one.",
        )
    )
    m.append(
        _m(
            "M2",
            "M2.5 agreement uses min not max",
            SRC,
            _AGREE_FRAC,
            "    agree_frac = min(up, down) / n if n else 0.0",
            "Agreement is read off the losing side; a unanimous read scores 0.0.",
        )
    )
    m.append(
        _m(
            "M2",
            "M2.6 margin is the agreement fraction",
            SRC,
            _MARGIN,
            "    margin = max(up, down) / n if n else 0.0",
            "The two published quantities become the same number, so the test "
            "that asserts they DISAGREE on a split read must fail.",
        )
    )
    m.append(
        _m(
            "M2",
            "M2.7 dissent counts the neutrals",
            SRC,
            _DISSENT,
            "    dissent = len(signals) - max(up, down)",
            "Neutrals counted as dissenters.",
        )
    )

    # -- M3: the verdict ladder (Defects 4, 5, 6) --------------------------
    m.append(
        _m(
            "M3",
            "M3.1 NO_SIGNAL branch removed",
            SRC,
            _NO_SIGNAL_BRANCH,
            '    if False:  # NO_SIGNAL removed\n        verdict = "NO_SIGNAL"',
            "Defect 4 restored: an all-neutral read falls through to LOW, and the "
            "declared member becomes unproducible.",
        )
    )
    m.append(
        _m(
            "M3",
            "M3.2 CONFLICTED branch removed",
            SRC,
            _OPPOSED_BRANCH,
            '    elif False:  # CONFLICTED removed\n        verdict = "CONFLICTED"',
            "The blocking verdict stops blocking and opposed reads fall through "
            "to the agreement gates.",
        )
    )
    m.append(
        _m(
            "M3",
            "M3.3 HIGH and MEDIUM bands swapped",
            SRC,
            _HIGH_BRANCH,
            _MEDIUM_BRANCH.replace("elif", "elif", 1),
            "The more permissive band is tested first, so every MEDIUM read is promoted to HIGH.",
        )
    )
    m.append(
        _m(
            "M3",
            "M3.4 HIGH gate drops the family floor",
            SRC,
            _HIGH_BRANCH,
            "    elif dissent <= settings.high_dissent_ceiling:",
            "Section 15.19-D's floor removed from the HIGH gate: a unanimous "
            "single-family read becomes HIGH.",
        )
    )
    m.append(
        _m(
            "M3",
            "M3.5 HIGH gate drops the dissent ceiling",
            SRC,
            _HIGH_BRANCH,
            "    elif distinct >= settings.high_family_floor:",
            "The agreement half of the HIGH gate removed.",
        )
    )
    m.append(
        _m(
            "M3",
            "M3.6 MEDIUM gate drops the family floor",
            SRC,
            _MEDIUM_BRANCH,
            "    elif dissent <= settings.medium_dissent_ceiling:",
            "Section 15.19-D's floor removed from the MEDIUM gate.",
        )
    )
    m.append(
        _m(
            "M3",
            "M3.7 the redundancy branch is folded back into LOW",
            SRC,
            _LOW_REDUNDANCY_BRANCH,
            "    elif distinct < settings.medium_family_floor and n > 99:",
            "Defect 5 restored: 'unanimous but single-source' stops being its own "
            "outcome and is reported as weak agreement.",
        )
    )

    # -- M4: the inert thresholds (Defect 6) -------------------------------
    m.append(
        _m(
            "M4",
            "M4.1 the HIGH ceiling becomes permissive",
            SRC,
            _HIGH_BRANCH,
            (
                "    elif dissent <= settings.medium_dissent_ceiling "
                "and distinct >= settings.high_family_floor:"
            ),
            "HIGH now tolerates MEDIUM's dissenters. Provably inert at the "
            "shipped config because no dissenter reaches this gate (Defect 6); "
            "kept as a canary for the day the gate order changes.",
            expect_killed=True,
            inert_proof=(
                "The reachable dissenter count past the CONFLICTED gate is "
                "exactly {0} for every n, so `dissent <= 1` and `dissent <= 0` "
                "select the same set of reachable reads. Proven by enumeration "
                "in tests/models/test_convergence.py::"
                "test_no_read_reaches_the_dissent_gate_with_a_dissenter."
            ),
        )
    )
    m.append(
        _m(
            "M4",
            "M4.2 the MEDIUM ceiling raised to a dead value",
            CONFIG,
            "    max_dissenting_signals_medium: CalibratedValue",
            "    max_dissenting_signals_medium: CalibratedValue  # raised in YAML",
            "Paired with the YAML change below; the accessor is what the module "
            "reads, so without the YAML edit this is a no-op comment.",
            expect_killed=False,
        )
    )
    m.append(
        _m(
            "M4",
            "M4.3 the shape declarations made optional",
            SRC,
            "    signals: list[ModelResult] = Field(\n        min_length=1,",
            "    signals: list[ModelResult] = Field(\n        min_length=0,",
            "An empty signal list is admitted, which the NO_SIGNAL branch then "
            "reports as 'all 0 signal(s) read neutral'.",
        )
    )

    # -- M5: the Section 15.19-D census (Defects 1 and 7) ------------------
    m.append(
        _m(
            "M5",
            "M5.1 the census runs over ALL signals",
            SRC,
            _DIRECTIONAL,
            "    directional = list(signals)",
            "Defect 7 restored: neutral signals import their families into the "
            "independence count, so a read can be promoted by padding with "
            "neutral signals -- Section 15.19-D's failure mode, inverted.",
        )
    )
    m.append(
        _m(
            "M5",
            "M5.2 the census call is removed",
            SRC,
            _CENSUS_CALL,
            "    census = ModelResult(\n"
            '        model_name="stub",\n'
            '        country="us",\n'
            "        as_of=utc_now(),\n"
            '        value={"distinct_families": len(directional), "untagged": 0, '
            '"families": []},\n'
            "        confidence=0.5,\n"
            '        interpretation="stub",\n'
            '        context="stub",\n'
            "        inputs_used=[],\n"
            "    )",
            "Section 15.19-D stops being discharged: the family count is the raw "
            "signal count again, which is the D-046 defect verbatim.",
        )
    )
    m.append(
        _m(
            "M5",
            "M5.3 the census result is ignored",
            SRC,
            _DISTINCT_READ,
            '    distinct = census_value.get("distinct_families")\n    distinct = len(directional)',
            "The supplier is called and its answer discarded.",
        )
    )
    m.append(
        _m(
            "M5",
            "M5.4 the census guard is dropped",
            SRC,
            _CENSUS_GUARD,
            "    if False:  # contract guard removed",
            "A non-dict census value flows into `.get()` and raises "
            "AttributeError instead of the contract error.",
        )
    )
    m.append(
        _m(
            "M5",
            "M5.5 the distinct guard is dropped",
            SRC,
            _DISTINCT_GUARD,
            "    if False:  # contract guard removed",
            "A non-int family count flows into the comparison and raises the "
            "same TypeError the specification suffered from.",
        )
    )
    m.append(
        _m(
            "M5",
            "M5.6 the exclusion set is not computed",
            SRC,
            _EXCLUDED,
            "    excluded_families: list[str] = []",
            "The neutral-only families are silently dropped rather than "
            "published, so the exclusion becomes invisible.",
        )
    )
    m.append(
        _m(
            "M5",
            "M5.7 the families key is read from the wrong side",
            SRC,
            _FAMILIES_READ,
            '    directional_families = set(census_value.get("families") or ["stub"])',
            "A placeholder is injected into the SUBTRAHEND of the set difference. "
            "Found inert, not untested: a member added to the subtrahend can only "
            'remove families the census claims, and ``"stub"`` is never the name '
            "of a neutral signal's family, so the difference is unchanged for "
            "every input. Kept as a trapdoor — it becomes live the moment the "
            "fallback is moved to the LEFT of the subtraction.",
            expect_killed=True,
            inert_proof=(
                "``excluded = neutral_families - directional_families``. The "
                "mutant sets ``directional_families = {'stub'}` (when the census "
                "reports no families) instead of ``set()``. Subtracting a SUPERSET "
                "can only shrink the result, and ``'stub'`` is not a member of any "
                "``EvidenceSourceFamily`` value, so "
                "``neutral_families - {'stub'} == neutral_families - set()`` for "
                "every reachable ``neutral_families``. Verified directly: with a "
                "neutral TREASURY_OFFICIAL signal, both forms yield "
                "``['treasury_official']``. The mutation is a no-op."
            ),
        )
    )

    # -- M6: confidence (Section 22.8) -------------------------------------
    m.append(
        _m(
            "M6",
            "M6.1 confidence hardcoded",
            SRC,
            _INDEPENDENCE,
            "            source_independence_count=0,",
            "The independence credit is switched off: confidence stops moving "
            "with the measured family count.",
        )
    )
    m.append(
        _m(
            "M6",
            "M6.2 heuristic penalty switched off",
            SRC,
            _HEURISTIC,
            "            is_heuristic_not_calibrated=False,",
            "The uncalibrated-threshold penalty is suppressed, inflating every confidence.",
        )
    )
    m.append(
        _m(
            "M6",
            "M6.3 unobservable penalty switched on",
            SRC,
            _UNOBSERVABLE,
            "            depends_on_unobservable=True,",
            "A penalty that does not apply is applied.",
        )
    )
    m.append(
        _m(
            "M6",
            "M6.4 the data-quality flag is not propagated",
            SRC,
            _FLAG_ANY,
            "            data_quality_flags_present=False,",
            "A flagged input stops lowering confidence.",
        )
    )

    # -- M7: the published value -------------------------------------------
    for idx, (old, new) in enumerate(_PUBLISHED, start=1):
        m.append(
            _m(
                "M7",
                f"M7.{idx} published value key altered",
                SRC,
                old,
                new,
                "One of the nine published quantities is replaced. Every key "
                "decides either the verdict or an audit trail, so each must be "
                "pinned by its own assertion.",
            )
        )

    # -- M8: warnings and the result envelope ------------------------------
    m.append(
        _m(
            "M8",
            "M8.1 the CONFLICTED warning is not emitted",
            SRC,
            _WARN_CONFLICTED,
            '    if verdict == "CONFLICTED" and n < 0:',
            "The blocking warning stops firing. Wording is not the safety "
            "mechanism but the BRANCH is, and this removes the branch.",
        )
    )
    m.append(
        _m(
            "M8",
            "M8.2 the NO_SIGNAL warning is not emitted",
            SRC,
            _WARN_NO_SIGNAL,
            '    elif verdict == "NO_SIGNAL" and n < 0:',
            "NO_SIGNAL stops explaining why it is not LOW.",
        )
    )
    m.append(
        _m(
            "M8",
            "M8.3 the neutral-only-family warning is not emitted",
            SRC,
            _WARN_EXCLUDED,
            "    if excluded_families and n < 0:",
            "The disclosure of what the census set aside disappears.",
        )
    )
    m.append(
        _m(
            "M8",
            "M8.4 the denominator-exclusion warning is not emitted",
            SRC,
            _WARN_NEUTRAL_DENOM,
            "    if 0 < n < total and n < 0:",
            "The explanation of why the denominator is smaller than the list disappears.",
        )
    )
    m.append(
        _m(
            "M8",
            "M8.5 inputs_used names the signals",
            SRC,
            "        inputs_used=[s.model_name for s in signals],",
            _INPUTS_USED,
            "The index-addressed input provenance is replaced by model names, "
            "which collide when the same model appears twice.",
        )
    )
    m.append(
        _m(
            "M8",
            "M8.6 the context drops its Section 15.19-D disclosure",
            SRC,
            _CONTEXT,
            '        context=("no provenance note",',
            "The context string is the only place the result states that the "
            "independence weighting is measured over the DIRECTIONAL signals. "
            "A test asserts the phrase is present, so this must be killed.",
        )
    )

    # -- M9: the config accessors and validators ---------------------------
    m.append(
        _m(
            "M9",
            "M9.1 HIGH dissent accessor returns a literal",
            CONFIG,
            _ACCESSOR_HIGH_DISSENT,
            "        return 1",
            "A hardcoded copy of the leaf: the config read becomes decorative.",
        )
    )
    m.append(
        _m(
            "M9",
            "M9.2 MEDIUM dissent accessor returns a literal",
            CONFIG,
            _ACCESSOR_MEDIUM_DISSENT,
            "        return 0",
            "The mirror of M9.1 on the other ceiling.",
        )
    )
    m.append(
        _m(
            "M9",
            "M9.3 HIGH family accessor returns a literal",
            CONFIG,
            _ACCESSOR_HIGH_FAMILY,
            (
                "    def high_family_floor(self) -> int:\n"
                '        """Independent families required for ``HIGH``."""\n'
                "        return 2"
            ),
            "A hardcoded family floor: Section 15.19-D's gate stops reading config.",
        )
    )
    m.append(
        _m(
            "M9",
            "M9.4 MEDIUM family accessor returns a literal",
            CONFIG,
            _ACCESSOR_MEDIUM_FAMILY,
            (
                "    def medium_family_floor(self) -> int:\n"
                '        """Independent families required for ``MEDIUM``."""\n'
                "        return 1"
            ),
            "The mirror of M9.3.",
        )
    )
    m.append(
        _m(
            "M9",
            "M9.5 the dissent-order validator is dropped",
            CONFIG,
            _VALIDATOR_ORDER,
            (
                "        _high = int(self.max_dissenting_signals_high.value)\n"
                "        _medium = int(self.max_dissenting_signals_medium.value)\n"
                "        if False:  # validator removed"
            ),
            "Inverted dissent ceilings are accepted, making MEDIUM unreachable.",
        )
    )
    m.append(
        _m(
            "M9",
            "M9.6 the negative-ceiling validator is dropped",
            CONFIG,
            _VALIDATOR_NEGATIVE,
            (
                "        if _high > _medium:\n"
                "            raise ValueError(\n"
                '                f"convergence.max_dissenting_signals_high ({_high}) '
                'must not exceed "\n'
                '                f"max_dissenting_signals_medium ({_medium}): HIGH is '
                'the STRICTER "\n'
                '                "verdict, so it cannot tolerate more dissent than '
                'MEDIUM. Inverting "\n'
                '                "them would make the MEDIUM band unreachable and '
                'silently promote "\n'
                '                "every MEDIUM read to HIGH."\n'
                "            )\n"
                "        if False:  # validator removed"
            ),
            "A negative dissenter count is accepted.",
        )
    )
    m.append(
        _m(
            "M9",
            "M9.7 the medium-above-one validator is dropped",
            CONFIG,
            _VALIDATOR_MEDIUM_ONE,
            "        if False:  # validator removed",
            "A ceiling above one is accepted, which could promote CONFLICTED reads.",
        )
    )
    m.append(
        _m(
            "M9",
            "M9.8 the family-order validator is dropped",
            CONFIG,
            _VALIDATOR_FAMILY_ORDER,
            (
                "        _fam_high = int(self.min_independent_families_high.value)\n"
                "        _fam_medium = int(self.min_independent_families_medium.value)\n"
                "        if False:  # validator removed"
            ),
            "Inverted family floors are accepted: HIGH demands less independence than MEDIUM.",
        )
    )
    m.append(
        _m(
            "M9",
            "M9.9 the zero-family validator is dropped",
            CONFIG,
            _VALIDATOR_FAMILY_ZERO,
            "        if False:  # validator removed",
            "A zero family floor is accepted, the degenerate case where every read qualifies.",
        )
    )

    return m


def check_targets(mutations: list[Mutation], *, verbose: bool = True) -> list[str]:
    """Refuse to run unless every ``old`` string is present EXACTLY ONCE.

    From D-048, and this is the gate that makes the rest of the sweep mean
    anything. ``str.replace(old, new, 1)`` takes the FIRST occurrence, so an
    ``old`` string appearing twice silently rewrites the wrong site and the
    sweep then reports a surviving test -- a conclusion about code nobody
    mutated. An ``old`` appearing zero times means the target has drifted and
    the mutation is not testing what its name says.

    Returns the list of problems; an empty list means the sweep may run.
    """
    problems: list[str] = []
    by_file: dict[Path, str] = {}
    for path in {mt.path for mt in mutations}:
        by_file[path] = path.read_text(encoding="utf-8")

    for mt in mutations:
        text = by_file[mt.path]
        count = text.count(mt.old)
        if count == 0:
            problems.append(f"{mt.name}: target ABSENT in {mt.path.name} (0 occurrences)")
        elif count > 1:
            problems.append(
                f"{mt.name}: target AMBIGUOUS in {mt.path.name} "
                f"({count} occurrences) -- str.replace would rewrite the first"
            )
    if verbose:
        print(f"check_targets: {len(mutations)} mutations, {len(problems)} problem(s)")
        for p in problems:
            print(f"  !! {p}")
    return problems


def check_tests_collect() -> list[str]:
    """Prove the test selection actually collects tests BEFORE the sweep runs.

    This gate exists because of a defect this sweep found in itself. The first
    version listed ``tests/test_config.py`` as a target. That path does not
    exist. ``pytest`` exits **4** when a named path is missing, and ``run_pytest``
    treats any non-zero exit as "the mutation was killed" -- so with a bad target
    the first draft reported **56 of 56 mutations killed**, including a control
    mutation that was semantically identical to the shipped code and could not
    possibly fail a test. The headline number was an artefact of the harness, and
    only the control exposed it.

    The general rule this adds to the repository's sweep hygiene: a sweep must
    verify that the tests it relies on are *collected*, not merely that they were
    named. ``check_targets`` (D-048) does this for the mutation targets; nothing
    did it for the test selection. A number produced by an error exit code is not
    a mutation score.
    """
    problems: list[str] = []
    for target in PYTEST_TARGETS:
        path = REPO / target
        if not path.exists():
            problems.append(f"test target ABSENT: {target}")
            continue
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                "tests/models/test_convergence.py",
            ],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            problems.append(
                f"test target does not collect (pytest exit {proc.returncode}): {target}"
            )
            continue
        # "N tests collected" / "N/M tests collected" -- take the numerator.
        match = re.search(r"(\d+)\s+tests? collected", proc.stdout)
        if not match or int(match.group(1)) == 0:
            problems.append(f"test target collects ZERO tests: {target}")
    return problems


def run_pytest() -> tuple[int, str]:
    """Run the targeted tests. Non-zero means the mutation was killed.

    Exit code **4** is pytest's "usage error / no tests collected", which is not a
    kill -- it means the harness is broken. It is reported as an error rather than
    folded into the kill count, because that conflation is exactly what produced
    the first draft's false 56/56.
    """
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-x",
            "-q",
            "--no-header",
            "tests/models/test_convergence.py",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, (proc.stdout + proc.stderr)


def apply_and_test(mutation: Mutation) -> Result:
    """Apply one mutation, run the tests, restore the file. Foreground only.

    The restore reads from the in-memory ``original`` rather than a backup file.
    An earlier version copied to a temp file first and Windows refused the
    cleanup (``WinError 32``, the file still held by a process), which aborted
    the sweep after its first mutation. The in-memory restore is not merely
    simpler: it is what makes the ``finally`` unconditional, so a crash inside
    ``run_pytest`` still puts the shipped source back. A sweep that can leave
    ``src/`` mutated is the D-049 failure mode with extra steps.
    """
    original = mutation.path.read_text(encoding="utf-8")
    # The replace is guaranteed-unique by check_targets, which ran first.
    mutated = original.replace(mutation.old, mutation.new, 1)
    if mutated == original:
        return Result(mutation=mutation, applied=False, exit_code=0)

    try:
        mutation.path.write_text(mutated, encoding="utf-8", newline="")
        code, out = run_pytest()
    finally:
        mutation.path.write_text(original, encoding="utf-8", newline="")
    return Result(mutation=mutation, applied=True, exit_code=code, output=out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", help="run only this mutation group, e.g. M5")
    parser.add_argument(
        "--list",
        action="store_true",
        help="print the mutation catalogue and the check_targets verdict, then exit",
    )
    args = parser.parse_args()

    print("=" * 78)
    print("mutation sweep: classify_convergence (Module 12, Section 22.10, D-051)")
    print("FOREGROUND ONLY -- this rewrites files under src/ while it runs.")
    print("=" * 78)

    mutations = build_mutations()
    problems = check_targets(mutations)
    if problems:
        print(
            "\nREFUSING TO RUN: check_targets found absent or ambiguous targets. "
            "A sweep that mutates the wrong site reports survivors that mean "
            "nothing (D-048)."
        )
        return 2

    test_problems = check_tests_collect()
    if test_problems:
        print("\nREFUSING TO RUN: the test selection is broken, so exit codes")
        print("would not distinguish a kill from a harness error:")
        for p in test_problems:
            print(f"  !! {p}")
        return 2
    print(f"test selection collects cleanly: {', '.join(PYTEST_TARGETS)}")

    if args.list:
        for mt in mutations:
            print(f"  {mt.group:3} {mt.path.name:16} {mt.name}")
        return 0

    if args.group:
        mutations = [mt for mt in mutations if mt.group == args.group]
        if not mutations:
            print(f"no mutations in group {args.group}")
            return 2
        print(f"restricted to group {args.group}: {len(mutations)} mutation(s)")

    # O-103: the sidecar is the interrupt defence with real reach on win32,
    # where no Python signal handler runs for SIGTERM/SIGINT and a killed
    # process gets no `finally` turn. This runs after the early returns so a
    # run that mutates nothing leaves no sidecar behind, and it heals a
    # previous kill BEFORE the baseline is read -- reading first would adopt
    # a mutant as the baseline (D-081).
    with sweep_lifecycle(sorted({mt.path for mt in mutations})):
        return _run_sweep(mutations)


def _run_sweep(mutations: list[Mutation]) -> int:
    results: list[Result] = []
    for mt in mutations:
        print(f"\n--- {mt.group} {mt.name}")
        print(f"    intent: {mt.intent}")
        res = apply_and_test(mt)
        results.append(res)
        if not res.applied:
            print("    NOT APPLIED (no-op)")
        elif res.killed:
            first_fail = next(
                (ln for ln in res.output.splitlines() if ln.startswith("FAILED")),
                "(see output)",
            )
            print(f"    KILLED  {first_fail}")
        else:
            print("    SURVIVED")

    killed = sum(1 for r in results if r.applied and r.killed)
    survived = [r for r in results if r.applied and not r.killed]
    noop = [r for r in results if not r.applied]

    print("\n" + "=" * 78)
    print(f"applied {len(results) - len(noop)} / {len(results)}")
    print(f"killed  {killed}")
    print(f"survived {len(survived)}")

    unexplained = [
        r for r in survived if r.mutation.expect_killed is not False and not r.mutation.inert_proof
    ]
    if survived:
        print("\nsurvivors, classified:")
        for r in survived:
            if r.mutation.expect_killed is False:
                print(f"  [expected]  {r.mutation.name}")
            elif r.mutation.inert_proof:
                print(f"  [inert]     {r.mutation.name}")
                print(f"              proof: {r.mutation.inert_proof}")
            else:
                print(f"  [DEFECT]    {r.mutation.name} -- no test pins this")
    if noop:
        print("\nnot applied (target text matched but produced no change):")
        for r in noop:
            print(f"  {r.mutation.name}")

    print("=" * 78)
    if unexplained:
        print(
            f"RESULT: {len(unexplained)} unexplained survivor(s). Each is a "
            "missing test, not a missing mutation."
        )
        return 1
    print("RESULT: every survivor is either expected or proven inert.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
