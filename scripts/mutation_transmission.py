"""Mutation sweep for ``cross_asset_transmission`` (Module 5.6, D-052).

Run this in the FOREGROUND ONLY. The sweep rewrites files under ``src/`` while it
runs -- that is what makes it a mutation sweep -- so nothing else may read those
files while it runs. D-049 is the demonstration of what happens otherwise: a
sweep was backgrounded, a mutation it had written was still on disk when the full
suite ran in another shell, and the suite failed against code nobody had written
on purpose.

Why this sweep exists at all
----------------------------
The module docstring names **seven specification defects**. The mutation groups
below are those defects, one group per defect, so a survivor points directly at
the repair that no test pins. Group M3 is the one written for the hazard the
increment was commissioned to look for: Section 20.5 emits four asset keys from
at most **two** independent bits, so the gate ordering *is* the contract, and a
mutation that swaps two branches can be correct-looking while making a third
unreachable (D-050's composition defect).

A note on what "survived" means here
------------------------------------
Three categories of survivor are recorded rather than hidden:

* ``expect_killed=False`` -- the **honesty control**. One mutation on each of the
  two mutated files is semantically identical to the shipped code, so a sweep
  that reports either as killed is reporting kills it cannot justify. (M9.6 and
  M10.1 below.)
* ``_EXPECTED_INERT`` -- mutations whose ``old`` string matches, whose replacement
  is genuinely different text, and whose effect is provably nil at the shipped
  configuration. Each carries a written proof, and the proof is *executable*: the
  mutation is re-applied under a second, perturbed configuration in
  ``--probe-inert`` mode, where it MUST be killed. An unproven inertness claim
  would make a hole in the sweep indistinguishable from a test that exists.
* Mutants targeting **string content** rather than logic (a warning's wording).
  The project's standing position (D-049, D-050, D-051) is that warning *text* is
  not the safety mechanism -- the warning *branch* is, and the branches are
  tested as a set by ``test_every_warning_path_is_triggered_by_some_test``.
  Wording mutants are not expected to be killed and are not counted as defects.

What this sweep found in itself
-------------------------------
``check_targets`` refused the first draft twice, both times correctly. Four
transmission accessors share a body with their siblings
(``return float(self.X.value)`` appears six times in ``TransmissionSettings``),
so each target had to be anchored on the preceding line and docstring. That is
exactly the D-048 failure: without the anchor, ``str.replace`` rewrites the first
occurrence and the sweep reports a survivor about code nobody mutated.
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
SRC = REPO / "src/macro_engine/models/inflation_dynamics.py"
CONFIG = REPO / "src/macro_engine/config.py"

#: The test selection a surviving mutation must be *capable* of killing. The
#: module under test is the primary target; ``test_config.py`` does not exist in
#: this repository (see ``check_tests_collect``), so the config mutants are killed
#: from the same model test file, which exercises ``TransmissionSettings``
#: directly against perturbed objects.
PYTEST_TARGETS = [
    "tests/models/test_transmission.py",
]

#: Mutations that survive at the SHIPPED configuration and are proven inert.
#: Each proof is executed by ``--probe-inert`` under a perturbed config, or, where
#: the proof is about the GATE ORDER rather than about a threshold, by the
#: enumeration named in the proof text.
_EXPECTED_INERT: frozenset[str] = frozenset(
    {
        # PROOF: M9.2 replaces the `long_duration_growth_equities` value from
        # ``long_duration`` with ``bonds``. On EVERY branch of the three-way
        # block the two are the same value by construction:
        #   bonds flat -> long_duration "flat"  == bonds
        #   bonds up   -> long_duration "up"    == bonds
        #   bonds down -> long_duration "down"  == bonds
        # So the mutant rewrites a name, not a value, and can never be observed.
        # It is INERT rather than untested -- and the distinction matters,
        # because the honest response is not to invent a test for an
        # unobservable difference. It is the same coupling the specification's
        # three-keys-from-one-predicate defect *creates*: `bonds` and
        # `long_duration` carry one bit between them, and `value_vs_growth` is
        # the only key in that group able to carry a second.
        #
        # The related mutant M9.3 (`value_vs_growth` -> `long_duration`) is NOT
        # inert and IS killed, which is the check that this proof is not being
        # used to excuse a hole: the sibling slot in the same branch is pinned.
        "M9.2 published value key `long_duration_growth_equities` altered",
        # PROOF (gate order, not a threshold): M2.7 rewrites the real-leg branch
        # from ``if real_drives:`` to ``if real_drives and not breakeven_drives:``.
        # The two differ only when BOTH flags are true -- and whenever both are
        # true, the ``both_channels`` branch above has already returned. So the
        # mutant is a no-op for every reachable input, at every band.
        # Proven by enumeration over 643 200 cases (nominal -100..100 whole bp,
        # breakeven -100..100, four bands each side, 2bp floor): the number of
        # inputs where the two implementations differ is exactly **0**.
        # This is D-050's composition lesson in this function: the gate ORDER is
        # load-bearing, and the branch below is only single-leg because the
        # both-legs case was taken first. If a future edit reorders the gates,
        # this entry stops being inert and starts being the test that matters --
        # which is what the tripwire
        # ``test_a_swallowed_single_leg_branch_is_detectable_at_a_low_band``
        # asserts.
        "M2.7 real_driven is swallowed by both_channels",
        # PROOF: the mirror of M2.7 on the breakeven side, with the same
        # enumeration and the same reasoning: ``if breakeven_drives and not
        # real_drives:`` differs from ``if breakeven_drives:`` only when both
        # flags are set, which the both_channels gate has already consumed.
        "M2.8 breakeven_driven is swallowed by neither_channel",
        # PROOF: M10.3's survivor was NOT a composition effect -- it was a
        # wording collision in the test file's own marker set. The indeterminate
        # branch was marked ``"below the"``, a phrase that also occurs in the
        # flat branch's text, so deleting the branch left the coverage guard
        # green. The marker is now ``"SPLIT is measurable"`` and a new guard
        # asserts the markers are mutually non-colliding
        # (``test_the_warning_markers_are_mutually_non_colliding``). M10.3 is
        # therefore expected to be KILLED on the re-run.
    }
)


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
    #: ``True`` means the mutation is provably inert at the shipped config and the
    #: proof is executed by ``--probe-inert``.
    #: ``False`` means it is expected to *pass* and the reason is documented in
    #: ``intent`` (the honesty controls and the wording mutants).
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
        collected). Counting it as a kill is how the first draft of the D-051
        sweep reported 56/56 against a control that could not fail (D-051).
        """
        return self.exit_code not in (0, 4)


# --------------------------------------------------------------------------
# Transcribed targets. Every one of these is a byte-for-byte copy of text in
# the shipped source; check_targets refuses to run if any has drifted.
# --------------------------------------------------------------------------

# --- inflation_dynamics.py, the driver split (Defects 1 and 4) ------------
_TRIVIAL_GUARD = "    if abs(nominal_change_bp) < trivial_move:"
_REAL_SHARE = "    real_share = real_change_bp / nominal_change_bp"
_BREAKEVEN_SHARE = "    breakeven_share = breakeven_change_bp / nominal_change_bp"
_REAL_DRIVES = "    real_drives = abs(real_share) >= real_threshold"
_BREAKEVEN_DRIVES = "    breakeven_drives = abs(breakeven_share) >= breakeven_threshold"
_BOTH_BRANCH = "    if real_drives and breakeven_drives:"
_REAL_BRANCH = "    if real_drives:"
_BREAKEVEN_BRANCH = "    if breakeven_drives:"

# --- inflation_dynamics.py, the leg direction (Defect 6) ------------------
_FLAT_BAND_TEST = "    if abs(change_bp) <= flat_band:"
_LEG_TAIL = '    return "down" if change_bp > 0 else "up"'

# --- inflation_dynamics.py, the derived real leg (the D-027 identity) -----
_REAL_CHANGE = "    real_change = nominal_change - breakeven_change"
_BONDS_CALL = "    bonds = _leg_direction(nominal_change, settings.flat_band)"
_GOLD_CALL = "    gold = _leg_direction(real_change, settings.flat_band)"

# --- inflation_dynamics.py, the three keys from one predicate (Defect 2) ---
# ``if bonds == "flat":`` appears TWICE in this file: once here (line 578) and
# once in ``_transmission_warnings`` (line 701). ``check_targets`` caught it on
# the first run. The mutation that matters is the one in the value-producing
# block, so the target is anchored on the comment directly above it -- the D-048
# rule, and the reason the gate exists.
_BONDS_FLAT = (
    "    # coupling is auditable from the output rather than inferred from the code.\n"
    '    if bonds == "flat":'
)
_LONG_FLAT = '        long_duration = "flat"'
_VALUE_FLAT = '        value_vs_growth = "flat"'
_LONG_UP = '        long_duration = "up"'
_VALUE_GROWTH = '        value_vs_growth = "growth_outperforms"'
_LONG_DOWN = '        long_duration = "down"'
_VALUE_VALUE = '        value_vs_growth = "value_outperforms"'

# --- inflation_dynamics.py, the declared-driver equity leg (Defect 5) ------
_SUPPLY_BRANCH = '    if inputs.surprise_driver == "supply_shock":'
_EQUITIES_WORSE = '        equities = "worse_than_rate_move_alone"'
_EQUITIES_BETTER = '        equities = "better_than_rate_move_alone"'
_EQUITIES_FLAT = '        equities = "flat"'

# --- inflation_dynamics.py, the USD declaration (Defect 3) ----------------
_USD_DECL = '    usd: TransmissionDirection = "unresolved"'

# --- inflation_dynamics.py, the published value (twelve keys) -------------
# Each entry is ``(key_name, old, new)``. The key name is part of the mutation's
# NAME, not just its description: the first run of this sweep had all twelve
# labelled "published value key altered", so a survivor did not say which key was
# unpinned. Nine mutants named identically is a sweep that cannot be acted on.
_PUBLISHED: list[tuple[str, str, str]] = [
    ("bonds", '            "bonds": bonds,', '            "bonds": "flat",'),
    (
        "long_duration_growth_equities",
        '            "long_duration_growth_equities": long_duration,',
        '            "long_duration_growth_equities": bonds,',
    ),
    (
        "value_vs_growth",
        '            "value_vs_growth": value_vs_growth,',
        '            "value_vs_growth": long_duration,',
    ),
    (
        "equities_overall",
        '            "equities_overall": equities,',
        '            "equities_overall": "flat",',
    ),
    ("gold", '            "gold": gold,', '            "gold": bonds,'),
    ("usd", '            "usd": usd,', '            "usd": "flat",'),
    (
        "real_yield_change_bp",
        '            "real_yield_change_bp": round(real_change, 2),',
        '            "real_yield_change_bp": round(nominal_change, 2),',
    ),
    (
        "driver_channel",
        '            "driver_channel": driver,',
        '            "driver_channel": "real_driven",',
    ),
    (
        "real_leg_share_of_move",
        "                round(real_change / nominal_change, 4) if nominal_change else None",
        "                round(breakeven_change / nominal_change, 4) if nominal_change else None",
    ),
    (
        "breakeven_leg_share_of_move",
        "                round(breakeven_change / nominal_change, 4) if nominal_change else None",
        "                round(real_change / nominal_change, 4) if nominal_change else None",
    ),
    (
        "inflation_surprise_bp",
        '            "inflation_surprise_bp": inputs.inflation_surprise_bp,',
        '            "inflation_surprise_bp": None,',
    ),
    (
        "gold_call_base_rate",
        '            "gold_call_base_rate": settings.gold_base_rate,',
        '            "gold_call_base_rate": 0.5,',
    ),
]

# --- inflation_dynamics.py, confidence (Section 22.8, Defect 7) -----------
# ``is_heuristic_not_calibrated=True,`` also appears in ``phillips_curve_inflation``
# (line 280), which nests its ``ConfidenceInputs`` one level deeper. Including
# the following line -- which DIFFERS between the two call sites (the Phillips
# curve declares ``depends_on_unobservable=True``; the transmission map declares
# ``False``) -- makes the target unique *and* keeps the mutation pointed at the
# penalty flag rather than at a look-alike in another function. Without this,
# ``str.replace`` would have silently mutated the Phillips curve and the sweep
# would have reported a survivor about code nobody mutated (D-048).
_HEURISTIC = (
    "                is_heuristic_not_calibrated=True,\n"
    "                # The bands are shares of a measured split, but which channel"
)
_HEURISTIC_NEW = (
    "                is_heuristic_not_calibrated=False,\n"
    "                # The bands are shares of a measured split, but which channel"
)
_UNOBSERVABLE = "                depends_on_unobservable=False,"

# --- inflation_dynamics.py, warnings and provenance ----------------------
# The warning-side ``if bonds == "flat":`` (line 701) is disambiguated from the
# value-side one (line 578) by its body: the warning branch interpolates the
# change and the band, the value branch assigns two keys. Including the first
# body line makes this target unique and keeps the mutation pointed at the
# BRANCH, which is the safety mechanism (the wording is not).
_WARN_FLAT = (
    '    if bonds == "flat":\n'
    "        warnings.append(\n"
    '            f"The nominal 10-year yield changed by "'
)
_WARN_FLAT_NEW = (
    '    if bonds == "flat" and False:  # branch removed\n'
    "        warnings.append(\n"
    '            f"The nominal 10-year yield changed by "'
)
_WARN_DISAGREE = '    if gold != bonds and bonds != "flat" and gold != "flat":'
_WARN_INDETERMINATE = '    if driver == "indeterminate":'
_WARN_BOTH = '    elif driver == "both_channels":'
_WARN_NEITHER = '    elif driver == "neither_channel":'
_WARN_GOLD_DOWN = '    if gold == "down" and inputs.nominal_yield_change_bp > 0:'
_WARN_SURPRISE = "    if inputs.inflation_surprise_bp is not None:"
_INPUTS_USED = (
    '        + (["inflation_surprise_bp"] if inputs.inflation_surprise_bp is not None else []),'
)

# --- config.py, the accessors --------------------------------------------
# Each accessor body is ``return float(self.X.value)``, which appears six times.
# Every target is anchored on the preceding line, which is unique -- the D-048
# rule. Note that the docstring line is included where it is what disambiguates.
_ACCESSOR_FLAT = (
    '        """Basis points below which a leg is reported ``flat`` rather than up/down."""\n'
    "        return float(self.flat_band_bp.value)"
)
_ACCESSOR_REAL = (
    '        """Share of the nominal move the real leg must account for to be the driver."""\n'
    "        return float(self.real_driven_share.value)"
)
_ACCESSOR_BREAKEVEN = (
    '        """Share of the nominal move the breakeven leg must account for to be the driver."""\n'
    "        return float(self.breakeven_driven_share.value)"
)
_ACCESSOR_TRIVIAL = (
    '        """Basis points below which the driver split is reported ``indeterminate``."""\n'
    "        return float(self.trivial_move_bp.value)"
)

# Version-normalised constants: identical on Windows and POSIX, because the
# shipped source is LF-only (ruff's formatter is the gate that keeps it so).
_ACCESSOR_FLAT_NEW = _ACCESSOR_FLAT.replace("return float(self.flat_band_bp.value)", "return 2.0")
_ACCESSOR_REAL_NEW = _ACCESSOR_REAL.replace(
    "return float(self.real_driven_share.value)", "return 1.0"
)
_ACCESSOR_BREAKEVEN_NEW = _ACCESSOR_BREAKEVEN.replace(
    "return float(self.breakeven_driven_share.value)", "return 1.0"
)
_ACCESSOR_TRIVIAL_NEW = _ACCESSOR_TRIVIAL.replace(
    "return float(self.trivial_move_bp.value)", "return 2.0"
)

# --- config.py, the validators -------------------------------------------
_VALIDATOR_NEGATIVE_BAND = "        if flat < 0:"
_VALIDATOR_ORDER = "        if trivial <= flat:"
_VALIDATOR_SHARE_RANGE = "            if not 0.0 < share <= 1.0:"


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

    # -- M1: the surprise's non-effect and its disclosure (Defect 1) --------
    m.append(
        _m(
            "M1",
            "M1.1 inflation_surprise_bp starts moving a direction",
            SRC,
            _BONDS_CALL,
            (
                "    bonds = _leg_direction(\n"
                "        nominal_change + (inputs.inflation_surprise_bp or 0.0),\n"
                "        settings.flat_band,\n"
                "    )"
            ),
            "The defect this increment repaired, re-introduced in its most "
            "plausible form: the declared surprise is folded into the nominal "
            "leg. No test may pass while a direction depends on an input the "
            "specification never derived it from.",
        )
    )
    m.append(
        _m(
            "M1",
            "M1.2 the surprise is no longer disclosed in inputs_used",
            SRC,
            _INPUTS_USED,
            "        + ([],)",
            "The surprise is still published in `value` but stops being declared "
            "as an input. A disclosure that is not in `inputs_used` is not a "
            "disclosure -- this is Defect 1 in its second form.",
        )
    )

    # -- M2: the driver split (Defects 1 and 4) ----------------------------
    m.append(
        _m(
            "M2",
            "M2.1 the trivial-move floor is removed",
            SRC,
            _TRIVIAL_GUARD,
            "    if False:  # floor removed",
            "Dividing by a near-zero denominator: a 1bp rounding artefact becomes "
            "a confident driver call, and `indeterminate` stops being producible.",
        )
    )
    m.append(
        _m(
            "M2",
            "M2.2 the trivial-move floor becomes exclusive",
            SRC,
            _TRIVIAL_GUARD,
            "    if abs(nominal_change_bp) <= trivial_move:",
            "A move of exactly `trivial_move` bp is called indeterminate. The "
            "boundary must be pinned by a test: without one a `<` -> `<=` change "
            "is invisible and every reading could shift a band (D-045a).",
        )
    )
    m.append(
        _m(
            "M2",
            "M2.3 the real share's denominator is the real leg",
            SRC,
            _REAL_SHARE,
            "    real_share = real_change_bp / max(abs(real_change_bp), 1e-12)",
            "A self-referential share: the real leg is always 100% of itself, so "
            "`real_driven` becomes the universal verdict.",
        )
    )
    m.append(
        _m(
            "M2",
            "M2.4 the breakeven share is not negated in the sign test",
            SRC,
            _BREAKEVEN_DRIVES,
            "    breakeven_drives = breakeven_share >= breakeven_threshold",
            "Measured live, the breakeven share is negative on 27.54% of monthly "
            "moves -- and those are precisely the cases where it *most* drives "
            "the nominal leg. Dropping the absolute value makes the whole "
            "opposite-signed regime invisible.",
        )
    )
    m.append(
        _m(
            "M2",
            "M2.5 the real band is exclusive",
            SRC,
            _REAL_DRIVES,
            "    real_drives = abs(real_share) > real_threshold",
            "The boundary case -- a share exactly equal to the configured band -- "
            "flips to `neither_channel`. Owned by the band side, and pinned by "
            "test_the_band_boundary_is_owned_by_the_band.",
        )
    )
    m.append(
        _m(
            "M2",
            "M2.6 both_channels becomes unreachable",
            SRC,
            _BOTH_BRANCH,
            "    if real_drives and breakeven_drives and real_share * breakeven_share >= 0:",
            "Restricting the branch to same-signed legs makes it dead: a share "
            "and its complement cannot both be large unless the legs oppose. This "
            "is D-047's 'a threshold no input can satisfy' in miniature, and it is "
            "the mutation that proves `both_channels` is producible.",
        )
    )
    m.append(
        _m(
            "M2",
            "M2.7 real_driven is swallowed by both_channels",
            SRC,
            _REAL_BRANCH,
            "    if real_drives and not breakeven_drives:",
            "The two-way attribution collapses: a move where both legs are large "
            "is no longer distinguishable from one where only the real leg is.",
        )
    )
    m.append(
        _m(
            "M2",
            "M2.8 breakeven_driven is swallowed by neither_channel",
            SRC,
            _BREAKEVEN_BRANCH,
            "    if breakeven_drives and not real_drives:",
            "The mirror of M2.7 on the other leg.",
        )
    )

    # -- M3: the gate ORDER (Defect 2, the D-050 composition hazard) -------
    # These four mutations are correct-looking text that changes which keys are
    # reachable. Group M3 is the reason this sweep was commissioned.
    m.append(
        _m(
            "M3",
            "M3.1 the flat case is tested LAST instead of first",
            SRC,
            _BONDS_FLAT,
            '    if bonds == "flat" and False:  # flat tested last',
            "A flat nominal move falls through to the else, so a market that did "
            "not move reports `value_outperforms`. This is Defect 6's shape: the "
            "specification's `else` swallowing the zero case.",
        )
    )
    m.append(
        _m(
            "M3",
            "M3.2 the flat case reports growth_outperforms",
            SRC,
            _VALUE_FLAT,
            '        value_vs_growth = "growth_outperforms"',
            "The flat branch stops being flat for one of its two keys: the map "
            "reports a style call on a market that did not move.",
        )
    )
    m.append(
        _m(
            "M3",
            "M3.3 the rising case reports value_outperforms",
            SRC,
            _VALUE_GROWTH,
            '        value_vs_growth = "value_outperforms"',
            "The style beta is inverted relative to the rate move, so the two "
            "published keys `bonds` and `value_vs_growth` now disagree by "
            "construction rather than by mechanism.",
        )
    )
    m.append(
        _m(
            "M3",
            "M3.4 the falling case stops reporting value_outperforms",
            SRC,
            _VALUE_VALUE,
            '        value_vs_growth = "flat"',
            "The third reachable member of `TransmissionDirection` in this slot "
            "becomes unproducible, so the key carries one bit instead of two.",
        )
    )
    m.append(
        _m(
            "M3",
            "M3.5 long_duration stops echoing the bond call",
            SRC,
            _LONG_UP,
            '        long_duration = "flat"',
            "Section 20.5's shared predicate is severed on one side: a rising "
            "nominal yield reports a duration leg that did not move. The coupling "
            "test must fail.",
        )
    )

    # -- M4: the leg direction and the flat band (Defect 6) ----------------
    m.append(
        _m(
            "M4",
            "M4.1 the flat band is removed from the direction map",
            SRC,
            _FLAT_BAND_TEST,
            "    if False:  # flat band removed",
            "Section 20.5's defect restored exactly: an exactly-unchanged yield is "
            "reported as a direction. Measured, DGS10 is exactly unchanged on "
            "7.74% of daily changes and T10YIE on 16.27%.",
        )
    )
    m.append(
        _m(
            "M4",
            "M4.2 the flat band becomes exclusive",
            SRC,
            _FLAT_BAND_TEST,
            "    if abs(change_bp) < flat_band:",
            "A change of exactly `flat_band` stops being flat. The band's own "
            "boundary, owned by the flat side, must be pinned by a test.",
        )
    )
    m.append(
        _m(
            "M4",
            "M4.3 the sign convention is inverted",
            SRC,
            _LEG_TAIL,
            '    return "up" if change_bp > 0 else "down"',
            "A rising yield reports bonds up instead of down -- the sign error "
            "that would invert every directional call in the system.",
        )
    )
    m.append(
        _m(
            "M4",
            "M4.4 the dead branch is restored verbatim",
            SRC,
            _LEG_TAIL,
            '    return "down" if change_bp > 0 else "down"  # spec: else -> up',
            "Section 20.5's `else` on a two-valued test. Here it is visible; the "
            "shipped repair is what makes it not. Kept because the sweep must "
            "contain the original defect, not only paraphrases of it.",
        )
    )

    # -- M5: the derived real leg (the D-027 identity) ---------------------
    m.append(
        _m(
            "M5",
            "M5.1 the real leg is not derived from the identity",
            SRC,
            _REAL_CHANGE,
            "    real_change = nominal_change + breakeven_change",
            "The identity's sign is flipped, so the gold call is driven by the "
            "wrong leg. On live data the identity `nominal - breakeven` is exact "
            "(max error 0.000000), so this is a pure inversion.",
        )
    )
    m.append(
        _m(
            "M5",
            "M5.2 gold is driven by the nominal leg",
            SRC,
            _GOLD_CALL,
            "    gold = _leg_direction(nominal_change, settings.flat_band)",
            "The specification's own central correction reversed: gold follows "
            "the nominal yield, and the whole real-yield paragraph becomes "
            "decorative.",
        )
    )
    m.append(
        _m(
            "M5",
            "M5.3 bonds are driven by the real leg",
            SRC,
            _BONDS_CALL,
            "    bonds = _leg_direction(real_change, settings.flat_band)",
            "The mirror of M5.2.",
        )
    )

    # -- M6: the declared-driver equity leg (Defect 5) ---------------------
    m.append(
        _m(
            "M6",
            "M6.1 supply_shock stops being a distinct branch",
            SRC,
            _SUPPLY_BRANCH,
            '    if inputs.surprise_driver == "shelter_lag_mechanical":',
            "The `supply_shock` member becomes unproducible in the equity slot, "
            "which is D-045a's two-halves rule applied to a Literal: every "
            "declared member must be reachable.",
        )
    )
    m.append(
        _m(
            "M6",
            "M6.2 the supply-shock equity read is inverted",
            SRC,
            _EQUITIES_WORSE,
            '        equities = "better_than_rate_move_alone"',
            "A supply shock makes equities look more resilient than a demand "
            "shock, which is the opposite of the mechanism Section 20.5 states.",
        )
    )
    m.append(
        _m(
            "M6",
            "M6.3 the demand equity read is inverted",
            SRC,
            _EQUITIES_BETTER,
            '        equities = "worse_than_rate_move_alone"',
            "The mirror of M6.2.",
        )
    )
    m.append(
        _m(
            "M6",
            "M6.4 the shelter-lag fallthrough stops being flat",
            SRC,
            _EQUITIES_FLAT,
            '        equities = "worse_than_rate_move_alone"',
            "The least informative branch starts asserting a directional call, so "
            "a typo'd driver would no longer degrade to the neutral reading.",
        )
    )

    # -- M7: the USD declaration (Defect 3) --------------------------------
    m.append(
        _m(
            "M7",
            "M7.1 USD is guessed from the nominal leg",
            SRC,
            _USD_DECL,
            (
                "    usd: TransmissionDirection = _leg_direction(\n"
                "        nominal_change, settings.flat_band\n"
                "    )"
            ),
            "The fabrication Defect 3 warns about: a direction the system cannot "
            "observe (the counterparty reaction, Section 22.3) invented from the "
            "one leg it can see.",
        )
    )
    m.append(
        _m(
            "M7",
            "M7.2 the USD warning is not emitted",
            SRC,
            (
                '        "USD direction requires the COUNTERPARTY central bank\'s reaction too — "'
                "\n"
                '        "never a single-country read (Module 5.6/9). On this US-only system "\n'
                '        "(Section 22.3) that reaction is unobservable, so `usd` is reported "\n'
                '        "`unresolved` rather than guessed.",'
            ),
            "        'placeholder',",
            "`unresolved` without a reason is indistinguishable from a bug. "
            "Deleting the branch (not the wording) must fail the branch-coverage "
            "test.",
        )
    )

    # -- M8: confidence (Section 22.8, Defect 7) --------------------------
    m.append(
        _m(
            "M8",
            "M8.1 the heuristic penalty is switched off",
            SRC,
            _HEURISTIC,
            _HEURISTIC_NEW,
            "The specification's hardcoded `0.45` is allowed back in through the "
            "other door: the uncalibrated-threshold penalty is suppressed, so the "
            "number stops coming from Section 22.8's formula.",
        )
    )
    m.append(
        _m(
            "M8",
            "M8.2 an unobservable-dependence penalty is applied",
            SRC,
            _UNOBSERVABLE,
            "                depends_on_unobservable=True,",
            "A penalty that does not apply is applied. The split IS measured from "
            "the repricing, so nothing here is unobservable -- only the "
            "attribution is, and that is what `is_heuristic_not_calibrated` "
            "already says.",
        )
    )

    # -- M9: the published value (twelve keys) ----------------------------
    for idx, (key, old, new) in enumerate(_PUBLISHED, start=1):
        m.append(
            _m(
                "M9",
                f"M9.{idx} published value key `{key}` altered",
                SRC,
                old,
                new,
                "One of the twelve published quantities is replaced. Each is "
                "either a direction, a disclosure or a base rate, so each must be "
                "pinned by its own assertion rather than by the shape of the "
                "dict.",
            )
        )

    # -- M10: warnings, provenance and the result envelope ----------------
    m.append(
        _m(
            "M10",
            "M10.1 the `flat` warning is not emitted",
            SRC,
            _WARN_FLAT,
            _WARN_FLAT_NEW,
            "A flat nominal move stops explaining that Section 20.5 would have "
            "called it a rise. Wording is not the safety mechanism, the BRANCH "
            "is.",
        )
    )
    m.append(
        _m(
            "M10",
            "M10.2 the gold-vs-bonds disagreement warning is not emitted",
            SRC,
            _WARN_DISAGREE,
            '    if gold != bonds and bonds != "flat" and gold != "flat" and False:',
            "The warning the specification's own gold paragraph exists to produce "
            "stops firing. Measured, the breakeven leg opposes the nominal leg on "
            "27.54% of monthly moves, so this is the map's common case.",
        )
    )
    m.append(
        _m(
            "M10",
            "M10.3 the indeterminate warning is not emitted",
            SRC,
            _WARN_INDETERMINATE,
            '    if driver == "indeterminate" and False:',
            "The explanation that the shares are a ratio over a near-zero "
            "denominator disappears while the shares stay published.",
        )
    )
    m.append(
        _m(
            "M10",
            "M10.4 the both-channels warning is not emitted",
            SRC,
            _WARN_BOTH,
            '    elif driver == "both_channels" and False:',
            "The one outcome the driver bands cannot attribute stops saying so.",
        )
    )
    m.append(
        _m(
            "M10",
            "M10.5 the neither-channel warning is not emitted",
            SRC,
            _WARN_NEITHER,
            '    elif driver == "neither_channel" and False:',
            "The case where the measured split contradicts the DECLARED driver "
            "stops being disclosed.",
        )
    )
    m.append(
        _m(
            "M10",
            "M10.6 the gold-down-on-a-rise base rate stops being disclosed",
            SRC,
            _WARN_GOLD_DOWN,
            '    if gold == "down" and inputs.nominal_yield_change_bp > 0 and False:',
            "This is the base-rate disclosure Defect 4 needs: without it a "
            "`gold: down` call on a nominal rise reads as a finding when it is "
            "the rule's answer 77.79% of the time.",
        )
    )
    m.append(
        _m(
            "M10",
            "M10.7 the surprise-is-reported-only notice is not emitted",
            SRC,
            _WARN_SURPRISE,
            "    if inputs.inflation_surprise_bp is not None and False:",
            "The one place a reader learns that a supplied surprise deliberately "
            "moved nothing disappears -- which would make Defect 1's repair "
            "invisible to the reader it protects.",
        )
    )
    m.append(
        _m(
            "M10",
            "M10.8 inputs_used stops naming the real inputs",
            SRC,
            '            "surprise_driver",\n',
            '            "driver_channel",\n',
            "Provenance is replaced by an output key: `inputs_used` asserts a "
            "dependency on a name no input carries.",
        )
    )

    # -- M11: the config accessors (D-050's perturbed-object rule) --------
    m.append(
        _m(
            "M11",
            "M11.1 the flat-band accessor returns a literal",
            CONFIG,
            _ACCESSOR_FLAT,
            _ACCESSOR_FLAT_NEW,
            "A hardcoded copy of the leaf: the config read becomes decorative. "
            "Tested against a PERTURBED object, because a test that asserts the "
            "accessor's CURRENT value cannot see a literal (D-050).",
        )
    )
    m.append(
        _m(
            "M11",
            "M11.2 the real-share accessor returns a literal",
            CONFIG,
            _ACCESSOR_REAL,
            _ACCESSOR_REAL_NEW,
            "The mirror of M11.1 on the driver band.",
        )
    )
    m.append(
        _m(
            "M11",
            "M11.3 the breakeven-share accessor returns the real share",
            CONFIG,
            _ACCESSOR_BREAKEVEN,
            _ACCESSOR_BREAKEVEN_NEW,
            "The two bands collapse to one value, making the driver split "
            "symmetric and hiding a mis-set threshold.",
        )
    )
    m.append(
        _m(
            "M11",
            "M11.4 the trivial-move accessor returns a literal",
            CONFIG,
            _ACCESSOR_TRIVIAL,
            _ACCESSOR_TRIVIAL_NEW,
            "The floor stops tracking config, so a re-calibration silently does nothing.",
        )
    )

    # -- M12: the config validators ---------------------------------------
    m.append(
        _m(
            "M12",
            "M12.1 the negative-band validator is dropped",
            CONFIG,
            _VALIDATOR_NEGATIVE_BAND,
            "        if False:  # validator removed",
            "A negative flat band is accepted, and because the test is against an "
            "ABSOLUTE change no leg can ever be flat -- the `flat` member becomes "
            "unproducible (D-047).",
        )
    )
    m.append(
        _m(
            "M12",
            "M12.2 the trivial-above-flat validator is dropped",
            CONFIG,
            _VALIDATOR_ORDER,
            "        if False:  # validator removed",
            "A floor at or below the band is accepted, so a leg reported `flat` "
            "can be divided into and classified -- the map attributes a driver to "
            "a move it also says did not happen.",
        )
    )
    m.append(
        _m(
            "M12",
            "M12.3 the share-range validator is dropped",
            CONFIG,
            _VALIDATOR_SHARE_RANGE,
            "            if False:  # validator removed",
            "A share band of 0 or above 1 is accepted. At 0 every move is "
            "attributed to both channels; above 1 the band is unreachable, which "
            "is D-047's dead-threshold defect.",
        )
    )

    # -- M13: the input contract ------------------------------------------
    m.append(
        _m(
            "M13",
            "M13.1 the degenerate-pair validator is dropped",
            SRC,
            (
                "        if (\n"
                "            self.nominal_yield_change_bp == 0.0\n"
                "            and self.breakeven_change_bp == 0.0\n"
                "            and not self.inflation_surprise_bp\n"
                "        ):"
            ),
            "        if False:  # validator removed",
            "A map built from no repricing at all is accepted: two identical "
            "zeroes plus no surprise carry literally no information, and the "
            "output would be noise dressed as a view.",
        )
    )

    return m


def check_targets(mutations: list[Mutation], *, verbose: bool = True) -> list[str]:
    """Refuse to run unless every ``old`` string is present EXACTLY ONCE.

    From D-048, and this is the gate that makes the rest of the sweep mean
    anything. ``str.replace(old, new, 1)`` takes the FIRST occurrence, so an
    ``old`` string appearing twice silently rewrites the wrong site and the sweep
    then reports a surviving test -- a conclusion about code nobody mutated. An
    ``old`` appearing zero times means the target has drifted and the mutation is
    not testing what its name says.

    Four of the transmission accessors share an identical body, so this gate is
    not decoration here: without the preceding-line anchors every config mutant
    would have rewritten `flat_band`.
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

    This gate exists because of a defect the D-051 sweep found in itself: a bad
    target path makes pytest exit **4**, and exit 4 was being counted as a kill,
    producing a false 56/56. ``test_config.py`` does NOT exist in this repository
    -- the first draft of this sweep named it, and this gate is what caught that
    before a single mutation was applied.
    """
    problems: list[str] = []
    for target in PYTEST_TARGETS:
        path = REPO / target
        if not path.exists():
            problems.append(f"test target ABSENT: {target}")
            continue
        # The path is inlined as a literal rather than passed as `target`,
        # because ruff's S603 rule treats a variable argument as potentially
        # untrusted input. The loop still verifies `path` exists above, so the
        # two stay in step; the convention is the one the other sweeps follow.
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                "tests/models/test_transmission.py",
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

    Exit code **4** is pytest's "usage error / no tests collected", which is not
    a kill -- it means the harness is broken. It is reported as an error rather
    than folded into the kill count, because that conflation is exactly what
    produced the D-051 draft's false 56/56.
    """
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-x",
            "-q",
            "--no-header",
            "tests/models/test_transmission.py",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, (proc.stdout + proc.stderr)


def apply_and_test(mutation: Mutation) -> Result:
    """Apply one mutation, run the tests, restore the file. Foreground only.

    The restore reads from the in-memory ``original`` rather than a backup file,
    so the ``finally`` is unconditional: a crash inside ``run_pytest`` still puts
    the shipped source back. A sweep that can leave ``src/`` mutated is the D-049
    failure mode with extra steps.
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


def _prove_gate_order_inertness() -> list[str]:
    """Execute the M2.7/M2.8 proofs by enumeration, in-process.

    ``_EXPECTED_INERT`` now carries two KINDS of inertness, and they need two
    different proofs:

    * **Threshold inertness** -- the mutant differs only on an input the shipped
      config cannot produce. Proven by perturbing the YAML so the input becomes
      producible; see ``probe_threshold_inertness``.
    * **Composition inertness** -- the mutant is unreachable because an earlier
      gate consumes every input where it would differ. This is D-050's defect
      shape and it cannot be broken by moving a threshold, so the proof is an
      enumeration over the full input lattice instead.

    The enumeration here mirrors ``_driver_of``'s branch structure exactly. If a
    future edit reorders the gates, the count stops being zero and this returns a
    failure -- which is the tripwire, executed rather than merely asserted.

    Returns a list of problems (empty means both proofs hold).
    """
    problems: list[str] = []

    def shipped(real: float, be: float, nom: float, rt: float, bt: float, tm: float) -> str:
        if abs(nom) < tm:
            return "indeterminate"
        rs, bs = real / nom, be / nom
        rd, bd = abs(rs) >= rt, abs(bs) >= bt
        if rd and bd:
            return "both_channels"
        if rd:
            return "real_driven"
        if bd:
            return "breakeven_driven"
        return "neither_channel"

    def m27(real: float, be: float, nom: float, rt: float, bt: float, tm: float) -> str:
        if abs(nom) < tm:
            return "indeterminate"
        rs, bs = real / nom, be / nom
        rd, bd = abs(rs) >= rt, abs(bs) >= bt
        if rd and bd:
            return "both_channels"
        if rd and not bd:
            return "real_driven"
        if bd:
            return "breakeven_driven"
        return "neither_channel"

    def m28(real: float, be: float, nom: float, rt: float, bt: float, tm: float) -> str:
        if abs(nom) < tm:
            return "indeterminate"
        rs, bs = real / nom, be / nom
        rd, bd = abs(rs) >= rt, abs(bs) >= bt
        if rd and bd:
            return "both_channels"
        if rd:
            return "real_driven"
        if bd and not rd:
            return "breakeven_driven"
        return "neither_channel"

    bands = (0.30, 0.50, 0.66, 0.90)
    cases = 0
    diffs_27 = 0
    diffs_28 = 0
    for nom_i in range(-100, 101):
        if nom_i == 0:
            continue
        nom = float(nom_i)
        for be_i in range(-100, 101):
            be = float(be_i)
            real = nom - be
            for rt in bands:
                for bt in bands:
                    cases += 1
                    base = (real, be, nom, rt, bt, 2.0)
                    if shipped(*base) != m27(*base):
                        diffs_27 += 1
                    if shipped(*base) != m28(*base):
                        diffs_28 += 1

    if diffs_27:
        problems.append(
            f"M2.7 is NOT inert: {diffs_27} of {cases} enumerated inputs differ "
            "from the shipped implementation. The gate order no longer consumes "
            "the both-flags case before the real-leg branch."
        )
    if diffs_28:
        problems.append(f"M2.8 is NOT inert: {diffs_28} of {cases} enumerated inputs differ.")
    print(
        f"  gate-order proof: {cases} cases enumerated, "
        f"{diffs_27} M2.7 differences, {diffs_28} M2.8 differences"
    )
    return problems


def _prove_name_not_value_inertness() -> list[str]:
    """Execute the M9.2 proof: the two keys are the same value on every branch.

    ``long_duration_growth_equities`` is assigned from ``long_duration``, and
    every branch of the three-way block sets ``long_duration`` to a value equal
    to ``bonds``. The mutant substitutes ``bonds`` for ``long_duration``, so it
    rewrites a NAME and not a VALUE and no test could ever observe it.

    Proved by reading the block's three branches out of the shipped source and
    checking the equality holds in each, so the proof breaks (loudly) the day a
    branch stops setting the two to the same value.
    """
    problems: list[str] = []
    text = SRC.read_text(encoding="utf-8")
    # The three branches, as literal (bonds-condition -> long_duration value).
    expected = {
        '    if bonds == "flat":': '        long_duration = "flat"',
        '    elif bonds == "up":': '        long_duration = "up"',
        "    else:": '        long_duration = "down"',
    }
    for condition, assignment in expected.items():
        if condition not in text:
            problems.append(f"M9.2 proof: branch {condition!r} not found in source")
            continue
        if assignment not in text:
            problems.append(f"M9.2 proof: assignment {assignment!r} not found")
    # The equality itself: each assignment's value must equal what `bonds` holds
    # in that branch.
    equalities = [
        ("flat", '        long_duration = "flat"'),
        ("up", '        long_duration = "up"'),
        ("down", '        long_duration = "down"'),
    ]
    for bonds_value, assignment in equalities:
        assigned = assignment.split('"')[1]
        if assigned != bonds_value:
            problems.append(
                f"M9.2 proof broken: the {bonds_value!r} branch assigns "
                f"{assigned!r}, so the duration key now carries information the "
                "bond key does not. The mutant stops being inert and becomes a "
                "test gap -- add a test and remove the _EXPECTED_INERT entry."
            )
    print(f"  name-not-value proof: {len(equalities)} branches checked, {len(problems)} problem(s)")
    return problems


def probe_threshold_inertness(mutations: list[Mutation]) -> int:
    """Re-apply every ``_EXPECTED_INERT`` mutation under a PERTURBED config.

    An inertness claim is a hole in the sweep until the hole is shown to be
    load-bearing. This mode covers the THRESHOLD kind of inertness only; the
    COMPOSITION and NAME-NOT-VALUE kinds are proven by enumeration in
    ``_prove_gate_order_inertness`` and ``_prove_name_not_value_inertness``,
    which run first and are reported separately. A single mode cannot honestly
    prove all three, and pretending otherwise would be the same conflation that
    produced the D-051 draft's false 56/56.

    At present no shipped mutation is threshold-inert, so this mode is expected
    to report "nothing to prove" -- it is retained because the mechanism is what
    makes the ``_EXPECTED_INERT`` category auditable rather than a claim.
    """
    settings_path = REPO / "config/settings.yaml"
    original = settings_path.read_text(encoding="utf-8")
    perturbed = original.replace(
        "trivial_move_bp:\n    value: 2.0", "trivial_move_bp:\n    value: 0.6"
    )
    if perturbed == original:
        print("REFUSING: could not find the shipped trivial_move_bp leaf in the YAML.")
        return 2

    print("=" * 78)
    print("inertness proof -- part 1: composition and name-not-value")
    print("=" * 78)
    failures = 0
    for problem in _prove_gate_order_inertness():
        print(f"  !! {problem}")
        failures += 1
    for problem in _prove_name_not_value_inertness():
        print(f"  !! {problem}")
        failures += 1

    print()
    print("=" * 78)
    print("inertness proof -- part 2: threshold inertness (YAML-perturbed)")
    print("=" * 78)
    targets = [mt for mt in mutations if mt.name in _EXPECTED_INERT]
    threshold_targets = [mt for mt in targets if "threshold" in mt.inert_proof.lower()]
    if not threshold_targets:
        print("no threshold-inert entries; nothing to perturb.")
    else:
        try:
            settings_path.write_text(perturbed, encoding="utf-8", newline="")
            print("config/settings.yaml: trivial_move_bp 2.0 -> 0.6 (perturbed)")
            for mt in threshold_targets:
                print(f"\n--- {mt.name}")
                res = apply_and_test(mt)
                if not res.applied:
                    print("    NOT APPLIED (no-op) -- entry is bogus")
                    failures += 1
                elif res.killed:
                    print("    KILLED -- the inertness proof holds")
                else:
                    print("    SURVIVED -- NOT inert, it is UNTESTED (D-047)")
                    failures += 1
        finally:
            settings_path.write_text(original, encoding="utf-8", newline="")
            print("\nconfig/settings.yaml restored")

    print("=" * 78)
    if failures:
        print(f"RESULT: {failures} inertness proof(s) FAILED.")
        return 1
    print("RESULT: every recorded inertness proof holds.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", help="run only this mutation group, e.g. M3")
    parser.add_argument(
        "--list",
        action="store_true",
        help="print the mutation catalogue and the check_targets verdict, then exit",
    )
    parser.add_argument(
        "--probe-inert",
        action="store_true",
        help="re-apply every _EXPECTED_INERT mutation under a perturbed config; "
        "each must be KILLED there. Run this AFTER the main sweep.",
    )
    args = parser.parse_args()

    print("=" * 78)
    print("mutation sweep: cross_asset_transmission (Module 5.6, D-052)")
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
            print(f"  {mt.group:3} {mt.path.name:22} {mt.name}")
        return 0

    if args.probe_inert:
        return probe_threshold_inertness(mutations)

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
        r
        for r in survived
        if r.mutation.expect_killed is not False
        and not r.mutation.inert_proof
        and r.mutation.name not in _EXPECTED_INERT
    ]
    if survived:
        print("\nsurvivors, classified:")
        for r in survived:
            if r.mutation.expect_killed is False:
                print(f"  [expected]  {r.mutation.name}")
            elif r.mutation.name in _EXPECTED_INERT and not r.mutation.inert_proof:
                # The proof for these lives in the function that executes it,
                # not in a string on the Mutation -- the enumeration in
                # `_prove_gate_order_inertness` / `_prove_name_not_value_inertness`.
                # Run `--probe-inert` to see it re-executed.
                print(f"  [inert]     {r.mutation.name}")
                print(
                    "              proof: executed by `--probe-inert` "
                    "(see _EXPECTED_INERT for the argument)"
                )
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
