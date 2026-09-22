"""The reachability gate (``docs/DEFECTS_2026-09-19.md`` item 3).

**The defect this guards.** 59 Tier 1-4 model functions were implemented, unit
tested, several with mutation sweeps — and never called by the pipeline. The
suite was green throughout, because a unit test tests the *callee* and a
mutation sweep mutates the *callee*. Nothing asked the one question that would
have caught it: **does anything call it?**

These tests make that question part of the offline suite, so it is asked on
every run rather than only when someone remembers to run a tool. They are
deliberately *static* — they never build a thesis — because the offline suite
must not depend on a network or a FRED key.

**Why a baseline rather than "no unreachable functions".** Every entry in
``config/reachability_baseline.txt`` is a known, triaged finding: Phase 4+ by
endpoint (the risk/portfolio suite) or blocked on data no reachable route
supplies (the FCI). A test asserting zero would fail on day one, and a gate that
is red for a reason nobody intends to fix is a gate people learn to skip. What
these tests assert is the property that actually protects the work: **the
unreachable set does not grow, and every entry in it is accounted for.**
"""

from __future__ import annotations

import pytest
import reachability_audit as ra


@pytest.fixture(scope="module")
def unreachable() -> set[str]:
    """The Tier 1-4 functions with no pipeline caller, measured from the tree.

    Computed once per module — the scan reads every Python file in the repo,
    and the answer cannot change within a run. This calls the tool's own
    ``classify()`` rather than reimplementing its rules: a test that duplicated
    the logic would be free to drift from the thing it is supposed to check.
    """
    return ra.classify()["unreachable"]


@pytest.fixture(scope="module")
def baseline() -> set[str]:
    found = ra.read_baseline()
    assert found is not None, (
        "config/reachability_baseline.txt is missing. Without it a regression "
        "cannot be told apart from the status quo. Regenerate with: "
        "uv run python tools/reachability_audit.py --write-baseline"
    )
    return found


class TestNoRegression:
    """The load-bearing property: the unreachable set must not grow."""

    def test_no_function_became_unreachable(
        self, unreachable: set[str], baseline: set[str]
    ) -> None:
        """A function that was reachable and stopped being is a REGRESSION.

        This is the assertion that would have caught DEF-001 on the commit that
        introduced it, and the one that catches it again if a future refactor
        drops a pipeline call. Wiring work is only safe to do *because* this
        exists — without it, the next un-wiring happens silently and the 59
        becomes 60.
        """
        regressions = sorted(unreachable - baseline)
        assert not regressions, (
            "These functions are Tier 1-4 and no longer reachable from the "
            f"pipeline: {regressions}.\n"
            "Either restore the caller, or — if the removal was deliberate — "
            "record the decision by regenerating the baseline with "
            "`uv run python tools/reachability_audit.py --write-baseline`."
        )


class TestBaselineIsCurrent:
    """The baseline must not drift behind the tree, or it stops meaning anything."""

    def test_baseline_has_no_stale_entries(self, unreachable: set[str], baseline: set[str]) -> None:
        """Every baseline entry must still be unreachable.

        A stale entry is not a correctness bug, but it is how the baseline
        silently rots: if functions get wired and nobody trims the file, the
        baseline grows more permissive than reality and eventually permits a
        real regression through. Keeping it exact is what makes the previous
        test's diff meaningful.
        """
        newly_wired = sorted(baseline - unreachable)
        assert not newly_wired, (
            "These functions are listed as unreachable but are now reachable: "
            f"{newly_wired}.\n"
            "Good news — the baseline is stale. Commit the current truth with "
            "`uv run python tools/reachability_audit.py --write-baseline`."
        )

    def test_baseline_size_is_stable(self, baseline: set[str]) -> None:
        """A tripwire on the headline number, so it has to be changed on purpose.

        The count has moved only when legs were wired (63 to 59, then 59 to 58
        when D-085's ``_balance_sheet_leg`` gave ``qe_qt_stance`` its pipeline
        caller). Any other movement means either new unwired work or a silent
        un-wiring, and both deserve a human looking at the diff rather than a
        green build.
        """
        assert len(baseline) == 58, (
            f"Reachability baseline is {len(baseline)} entries, expected 58. "
            "A change here is a change to the audit's headline number — "
            "confirm it is intended, then update this expectation and the "
            "figures quoted in docs/."
        )


class TestAuditInternals:
    """Properties of the audit itself, since a wrong audit is a wrong answer."""

    def test_the_caller_detector_ignores_prose_and_imports(self) -> None:
        """The tool once counted docstring prose as a caller and lied about wiring.

        Pinned because the failure is silent and flattering: counting a mention
        as a call makes the system look better wired than it is, which is the
        single most dangerous direction for this tool to be wrong in.
        """
        hits = ra._references("compute_confidence", ra.MODELS / "contracts.py")
        for line in hits["pipeline"]:
            rel, _, lineno = line.partition(":")
            source = (ra.ROOT / rel).read_text(encoding="utf-8").splitlines()
            text = source[int(lineno) - 1]
            assert "compute_confidence(" in text, (
                f"{line} does not contain a call to compute_confidence, so the "
                "detector is matching something other than a call expression"
            )

    def test_tier_parsing_finds_both_tier_1_and_tier_5(self) -> None:
        """Tier 5 is what keeps the tool from demanding Phase 5 work."""
        tiers = ra.spec_tiers()
        assert tiers, "no tiers parsed from the spec — the regex has drifted"
        assert 1 in tiers.values(), "no Tier 1 functions parsed"
        assert 5 in tiers.values(), (
            "no Tier 5 functions parsed; without them the tool would count "
            "legitimately-deferred stubs as Phase 0-3 obligations"
        )

    def test_the_defining_module_is_still_scanned_for_local_calls(self) -> None:
        """The bug fixed 2026-09-19: skipping the module hid same-module calls.

        ``regime_tension`` is called from ``classify_regime_rule_based`` in the
        same file, and a wholesale skip reported it as a true orphan.
        """
        local = ra._local_calls("regime_tension", ra.MODELS / "regime.py")
        assert "classify_regime_rule_based" in local, (
            "the same-module call to regime_tension was not found — the "
            "defining-module skip has been reintroduced"
        )

    def test_a_basetemp_tree_inside_the_repo_is_not_scanned_as_source(self) -> None:
        """A throwaway gate-run tree must not be searched for callers.

        **The defect this guards (measured 2026-09-22).** The gate recipe runs
        ``pytest --basetemp=.gate_pt`` and hand-run probes have left
        ``.probe/pt*/`` — both INSIDE the project root, and each holding sandbox
        COPIES of real ``src/`` modules. ``_candidate_files`` walks ``ROOT`` with
        ``rglob("*.py")`` and excluded only ``.venv``/``build``/``dist``/``node_modules``,
        so it was counting those copies as first-party source. Measured on the
        live tree: **306 candidates, 63 of them phantom** (``.probe`` 44,
        ``.gate_pt`` 11, ``.iso_pt`` 8) — **21 % of the search surface**.

        Why that matters even though the baseline gate still passed: a copy
        carries the SAME function names as its original, so a *rename* in the
        real tree can be satisfied by a stale duplicate. That is a false
        negative, which is the direction this audit must never fail in — it is
        the identical shape as the docstring-prose bug pinned above, a stale
        second copy of the truth standing in for the real one.

        Asserted on the REAL tree, not a fixture, because the property is about
        the repository as it exists when the gate runs. Every path here is one
        the project's own tooling creates, so the test is stable anywhere the
        gate has ever been run; if none exist the loop is vacuously true and the
        third assertion still checks the rule directly.
        """
        for rel in (
            ".gate_pt/some_test0/module.py",
            ".gate_pt/test_x/thing.py",
            ".probe/pt5/diag.py",
            ".iso_pt/a.py",
            ".venv/lib/python3.13/site-packages/x.py",
            "build/thing.py",
        ):
            assert not ra._is_scannable_relative(rel), (
                f"{rel} would be scanned as first-party source; a gate run's "
                "sandbox copy of src/ is not project source"
            )

        # The rule must not over-reach: real source and a real dotted config dir
        # must still be scanned, or the exclusion would silently blind the audit.
        for rel in (
            "src/macro_engine/models/regime.py",
            "tests/test_reachability_gate.py",
            "tools/reachability_audit.py",
            ".github/workflows/quality.yml",
        ):
            assert ra._is_scannable_relative(rel), (
                f"{rel} is real source and must remain scannable — the temp-tree "
                "exclusion has been widened into a blind spot"
            )

        leaked = [rel for _path, rel in ra._candidate_files() if not ra._is_scannable_relative(rel)]
        assert leaked == [], (
            f"the candidate list contains non-source paths: {leaked[:5]} — the "
            "walk and the predicate have drifted apart"
        )
