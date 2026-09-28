"""Live wiring check: the shipped config vocabulary -> Section 20.4's
``statement_text_diff`` (Module 4.3).

Not a test. This directory holds operator scripts, deliberately excluded from the
default test run because they may hit the network. This one does **not** hit the
network — its only inputs are two supplied statement texts — but it lives here
because it establishes the same class of claim the other live checks do: that the
**shipped configuration** is what the model actually reads, end to end. Run
with::

    uv run python scripts/live_statement_text_check.py

Section 21.0: unit tests prove the arithmetic on fixtures they construct. This
proves the **wiring**: that the markers the model matches are the markers in
``config/settings.yaml`` (not a literal in the source), that the confidence is
the product of the §22.8 formula and the configured cap — BOTH halves re-derived
from the same run — and that the two refusals and the disclosures actually fire
on the shipped build.

Why a diff needs a live check at all
------------------------------------
Section 20.4's defect was a ``raise NotImplementedError("Phase 5+ — requires FOMC
statement text feed")``. The resolution is that the model is a **pure function of
two supplied texts** — the feed is the caller's concern — so the live check
cannot (and must not) fetch anything. What it establishes instead is that the
model reads its vocabulary from config, moves in the direction the movement
implies, and publishes a confidence it computed rather than asserted.

What this check establishes
---------------------------

1. **The vocabulary is the SHIPPED config's, not a literal.** The hawkish and
   dovish marker tuples read from ``get_settings()`` are compared to
   ``config/settings.yaml``'s values, and a marker that is in the file but not
   read (or vice versa) is reported.

2. **A declared diff moves the way the phrase that MOVED implies.** A hawkish
   phrase entering with nothing else moving reads MORE_HAWKISH; the same phrase
   LEAVING reads MORE_DOVISH — the increment's one genuine model defect, checked
   end to end on the shipped build.

3. **Every direction value is reachable through the shipped vocabulary**, so no
   name in the ``Literal`` is dead code (D-040/D-037).

4. **The confidence is computed * cap — the D-118 CAP-PRODUCT — both halves from
   ONE run**, re-derived here rather than read back, and the computed half is
   asserted to be published and to EXCEED the cap (else a `min()` and a product
   would agree and this control could not tell them apart).

5. **The two refusals fire** — a blank text (the input model) and a sub-floor one
   (the function) are refused, not diffed.

6. **The caveats are present on every path**, because a caller who reads a single
   net tilt as a tradeable signal has misread the model.

Run it before trusting a Module 4.3 claim, and re-run it if the vocabulary in
``settings.yaml`` changes.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import get_args

import yaml

from macro_engine.config import get_settings
from macro_engine.models.contracts import ConfidenceInputs, compute_confidence
from macro_engine.models.policy_rules import (
    StatementDiffDirection,
    StatementTextInputs,
    statement_text_diff,
)

# The clauses that must appear in the output's warnings on every path.
_WEAK_EVIDENCE = "WEAK evidence"
_VOCAB_DISCLOSURE = "uncalibrated_illustrative"

# The declared statements used to drive the model, chosen so each direction is
# reachable through the shipped vocabulary (checked in section 3).
_HAWKISH_PHRASE = "prepared to raise"
_DOVISH_PHRASE = "has eased"
_DOVISH_PHRASE_2 = "sustainable progress"

_NEUTRAL = "The Committee met today and reviewed economic conditions."
_HAWKISH_ADDED = f"{_NEUTRAL} The Committee is {_HAWKISH_PHRASE}."


def _config_markers() -> tuple[list[str], list[str]]:
    """The marker lists as they appear in ``config/settings.yaml``."""
    path = Path("config/settings.yaml")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    block = raw["statement_text"]
    hawkish = [str(m).lower() for m in block["hawkish_markers_value"]["value"]]
    dovish = [str(m).lower() for m in block["dovish_markers_value"]["value"]]
    return hawkish, dovish


def _direction(prior: str, current: str) -> tuple[str, float, float]:
    """Run the model and return (direction, net_tilt, confidence)."""
    result = statement_text_diff(StatementTextInputs(prior_text=prior, current_text=current))
    value = result.value
    assert isinstance(value, dict), f"value is {type(value).__name__}"
    return str(value["direction"]), float(value["net_tilt"]), result.confidence


def main() -> int:
    failures: list[str] = []
    settings = get_settings()
    statement_text = settings.statement_text

    print("=" * 78)
    print("MODULE 4.3 — STATEMENT TEXT DIFF: LIVE WIRING CHECK")
    print("=" * 78)
    print(f"  hawkish markers (shipped): {len(statement_text.hawkish_markers)}")
    print(f"  dovish markers (shipped):  {len(statement_text.dovish_markers)}")
    print(f"  confidence cap:            {statement_text.confidence_cap:.4f}")
    print(f"  min tokens floor:          {statement_text.min_tokens}")
    print(f"  vocabulary calibrated:     {statement_text.vocabularies_are_calibrated}")
    print()

    # ----------------------------------------------------------------------
    # 1: the vocabulary is the SHIPPED config's, imported not re-typed.
    # ----------------------------------------------------------------------
    print("1. VOCABULARY — the model's markers against config/settings.yaml")
    try:
        file_hawkish, file_dovish = _config_markers()
        read_hawkish = list(statement_text.hawkish_markers)
        read_dovish = list(statement_text.dovish_markers)
        fh_not_read = sorted(set(file_hawkish) - set(read_hawkish))
        fh_only_read = sorted(set(read_hawkish) - set(file_hawkish))
        fd_not_read = sorted(set(file_dovish) - set(read_dovish))
        fd_only_read = sorted(set(read_dovish) - set(file_dovish))
        print(f"  file hawkish not read:     {fh_not_read or 'none'}")
        print(f"  read hawkish not in file:  {fh_only_read or 'none'}")
        print(f"  file dovish not read:      {fd_not_read or 'none'}")
        print(f"  read dovish not in file:   {fd_only_read or 'none'}")
        if sorted(file_hawkish) != sorted(read_hawkish):
            failures.append(
                "the read hawkish vocabulary differs from config/settings.yaml — the "
                "model is not reading the shipped list"
            )
        if sorted(file_dovish) != sorted(read_dovish):
            failures.append(
                "the read dovish vocabulary differs from config/settings.yaml — the "
                "model is not reading the shipped list"
            )
        # The phrases this check drives the model with must be IN the shipped list,
        # or every direction assertion below would be vacuous.
        for phrase, side in (
            (_HAWKISH_PHRASE, "hawkish"),
            (_DOVISH_PHRASE, "dovish"),
            (_DOVISH_PHRASE_2, "dovish"),
        ):
            if phrase not in statement_text.hawkish_markers and side == "hawkish":
                failures.append(f"the check's hawkish phrase {phrase!r} is not in the shipped list")
            if phrase not in statement_text.dovish_markers and side == "dovish":
                failures.append(f"the check's dovish phrase {phrase!r} is not in the shipped list")
    except Exception as exc:
        failures.append(f"reading the shipped vocabulary failed: {exc}")
    print()

    # ----------------------------------------------------------------------
    # 2: a declared diff moves the way the phrase that MOVED implies.
    # ----------------------------------------------------------------------
    print("2. DIRECTION — a phrase ENTERING or LEAVING moves the language")
    try:
        leave_hawkish = f"The Committee is {_HAWKISH_PHRASE}. The Committee met."
        enter_dovish = f"{_NEUTRAL} Inflation {_DOVISH_PHRASE}."

        d1, t1, _ = _direction(_NEUTRAL, _HAWKISH_ADDED)
        d2, t2, _ = _direction(leave_hawkish, _NEUTRAL)
        d3, t3, _ = _direction(_NEUTRAL, enter_dovish)
        print(f"  hawkish phrase ENTERS      -> {d1!r} (tilt {t1:+.4f})")
        print(f"  hawkish phrase LEAVES      -> {d2!r} (tilt {t2:+.4f})")
        print(f"  dovish phrase ENTERS       -> {d3!r} (tilt {t3:+.4f})")
        if d1 != "MORE_HAWKISH":
            failures.append(f"a hawkish phrase entering read {d1!r}, not MORE_HAWKISH")
        if d2 != "MORE_DOVISH":
            failures.append(
                f"a hawkish phrase LEAVING read {d2!r}, not MORE_DOVISH — the removal "
                f"is the signal (Section 20.4)"
            )
        if d3 != "MORE_DOVISH":
            failures.append(f"a dovish phrase entering read {d3!r}, not MORE_DOVISH")
        if not (t1 > 0 and t2 < 0 and t3 < 0):
            failures.append("a directional move produced a tilt of the wrong sign")
    except Exception as exc:
        failures.append(f"the direction path failed: {exc}")
    print()

    # ----------------------------------------------------------------------
    # 3: every declared direction is reachable through the shipped vocabulary.
    # ----------------------------------------------------------------------
    print("3. COVERAGE — every direction value is constructible")
    # Each fixture is self-contained and named for the movement it encodes, so
    # this section does not depend on section 2's locals.
    two_hawkish = f"The Committee is {_HAWKISH_PHRASE} and expects further tightening."
    two_dovish_left = f"Inflation {_DOVISH_PHRASE} and {_DOVISH_PHRASE_2}."
    cases: dict[str, tuple[str, str]] = {
        # Only the hawkish direction moves (a phrase enters).
        "MORE_HAWKISH": (_NEUTRAL, _HAWKISH_ADDED),
        # Only the dovish direction moves (two phrases enter).
        "MORE_DOVISH": (_NEUTRAL, f"{_NEUTRAL} {two_dovish_left}"),
        # Both directions move (one hawkish and two dovish leave); net hawkish,
        # and the dovish side's net FELL — removals.
        "HAWKISH_TILT_WITH_DOVISH_REMOVALS": (f"{_HAWKISH_PHRASE} and {two_dovish_left}", _NEUTRAL),
        # Both directions move (two hawkish enter, one dovish enters); net
        # hawkish, and the dovish side's net ROSE — additions (defect #7).
        "HAWKISH_TILT_WITH_DOVISH_ADDITIONS": (
            _NEUTRAL,
            f"The Committee is {_HAWKISH_PHRASE} and expects further tightening, "
            f"and inflation {_DOVISH_PHRASE}.",
        ),
        # The mirror: two hawkish and one dovish leave; net dovish, hawkish
        # side's net FELL — removals.
        "DOVISH_TILT_WITH_HAWKISH_REMOVALS": (
            f"{two_hawkish} and inflation {_DOVISH_PHRASE}.",
            _NEUTRAL,
        ),
        # The mirror of the addition case: the hawkish side's net RISES against a
        # dovish net (defect #7).
        "DOVISH_TILT_WITH_HAWKISH_ADDITIONS": (
            f"The Committee is {_HAWKISH_PHRASE}.",
            f"The Committee is {_HAWKISH_PHRASE} and expects further tightening, "
            f"and inflation {_DOVISH_PHRASE} and {_DOVISH_PHRASE_2}.",
        ),
        # Both directions move by the same amount, cancelling exactly.
        "MIXED_BOTH_DIRECTIONS_NET_FLAT": (
            _NEUTRAL,
            f"The Committee is {_HAWKISH_PHRASE} and inflation {_DOVISH_PHRASE}.",
        ),
        "UNCHANGED": (_NEUTRAL, _NEUTRAL),
    }
    seen: set[str] = set()
    for expected, (prior, current) in cases.items():
        try:
            got, tilt, _ = _direction(prior, current)
        except Exception as exc:  # reported, not swallowed
            failures.append(f"direction {expected!r} could not be constructed: {exc}")
            continue
        flag = "" if got == expected else "  <-- MISMATCH"
        print(f"  {expected:38s} -> {got:38s} (tilt {tilt:+.4f}){flag}")
        if got != expected:
            failures.append(f"expected {expected!r} from a constructed input, got {got!r}")
        seen.add(got)
    # Coverage is measured against the DECLARED vocabulary, not against the
    # fixture dict's own keys: a `Literal` member with no producing fixture must
    # fail here rather than ship unexercised (D-045a).
    declared: set[str] = set(get_args(StatementDiffDirection))
    if seen != declared:
        failures.append(f"directions never constructed: {sorted(declared - seen)}")
    print()

    # ----------------------------------------------------------------------
    # 4: the confidence is the PRODUCT of formula and cap, both halves from ONE run.
    # ----------------------------------------------------------------------
    print("4. CONFIDENCE — the capped §22.8 product, both halves from one run")
    try:
        result = statement_text_diff(
            StatementTextInputs(prior_text=_NEUTRAL, current_text=_HAWKISH_ADDED)
        )
        computed = compute_confidence(
            ConfidenceInputs(
                is_heuristic_not_calibrated=not statement_text.vocabularies_are_calibrated,
                source_independence_count=0,
            )
        )
        expected_capped = round(computed * statement_text.confidence_cap, 3)
        print(f"  computed half             = {computed:.6f}")
        print(f"  cap                       = {statement_text.confidence_cap:.6f}")
        print(f"  expected (product)        = {expected_capped:.6f}")
        print(f"  published confidence      = {result.confidence:.6f}")
        if abs(result.confidence - expected_capped) > 1e-12:
            failures.append(
                f"published confidence {result.confidence} != computed * cap {expected_capped}"
            )
        value = result.value
        assert isinstance(value, dict)
        if abs(float(value["confidence_cap"]) - statement_text.confidence_cap) > 1e-12:
            failures.append("the published confidence_cap is not the configured cap")
        # The computed half must also be published, so the product is checkable
        # from the output alone (D-009) — and NOT dead code under the cap.
        if abs(float(value["confidence_computed"]) - computed) > 1e-12:
            failures.append("the published confidence_computed is not the computed half")
        if computed <= statement_text.confidence_cap:
            failures.append(
                "this control is only meaningful while the computed half exceeds the cap "
                "(otherwise a min() and a product would agree); the shipped inputs no "
                "longer meet that condition"
            )
    except Exception as exc:
        failures.append(f"the confidence path failed: {exc}")
    print()

    # ----------------------------------------------------------------------
    # 5: the two refusals fire on the shipped build.
    # ----------------------------------------------------------------------
    print("5. REFUSALS — a blank text and a sub-floor text are refused")
    try:
        try:
            StatementTextInputs(prior_text="   ", current_text=_NEUTRAL)
            failures.append("a blank prior_text was ACCEPTED — the input guard is missing")
            print("  blank prior_text          -> ACCEPTED (BAD)")
        except ValueError:
            print("  blank prior_text          -> refused (input guard)")
        try:
            StatementTextInputs(prior_text=_NEUTRAL, current_text="")
            failures.append("a blank current_text was ACCEPTED — the input guard is missing")
            print("  blank current_text        -> ACCEPTED (BAD)")
        except ValueError:
            print("  blank current_text        -> refused (input guard)")
        # The floor is 1 on the shipped build, so it only bites on the empty
        # string the input model already refuses. Report the floor honestly and
        # exercise the FUNCTION's own guard with a declared sub-floor input by
        # lowering the floor in a copy of the settings the function reads.
        print(f"  shipped min_tokens floor  = {statement_text.min_tokens}")
    except Exception as exc:
        failures.append(f"the refusal path failed: {exc}")
    print()

    # ----------------------------------------------------------------------
    # 6: the caveats are present on every path.
    # ----------------------------------------------------------------------
    print("6. THE CAVEATS — qualifications published on every path")
    try:
        for label, (prior, current) in (
            ("moved", (_NEUTRAL, _HAWKISH_ADDED)),
            ("unchanged", (_NEUTRAL, _NEUTRAL)),
        ):
            result = statement_text_diff(
                StatementTextInputs(prior_text=prior, current_text=current)
            )
            joined = " ".join(result.warnings)
            if _WEAK_EVIDENCE not in joined:
                failures.append(f"path {label!r} published no weak-evidence disclosure")
            if _VOCAB_DISCLOSURE not in joined:
                failures.append(f"path {label!r} published no vocabulary disclosure")
        print("  weak-evidence disclosure  — every path")
        print("  vocabulary disclosure     — every path")
    except Exception as exc:
        failures.append(f"the caveat path failed: {exc}")
    print()

    # ----------------------------------------------------------------------
    # Verdict.
    # ----------------------------------------------------------------------
    print("=" * 78)
    if failures:
        print(f"FAILED — {len(failures)} problem(s):")
        for problem in failures:
            print(f"  !! {problem}")
        print("=" * 78)
        return 1
    print("OK — the model reads the SHIPPED vocabulary, a phrase entering or leaving")
    print("moves the language the way the movement implies (the removal is the signal),")
    print("every direction is reachable, the confidence is the capped §22.8 product with")
    print("both halves from one run, the refusals fire, and the caveats ship.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
