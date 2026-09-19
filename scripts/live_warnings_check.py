"""Live check: the real thesis inputs -> ``collect_all_warnings`` (D-067).

Not a test. This directory holds operator scripts, deliberately excluded from
the default test run because they hit the network. Run with::

    uv run python scripts/live_warnings_check.py

Section 21.0: unit tests prove the aggregation, this proves the **wiring** and
measures the two classes the specification makes mandatory.

Why this increment needs a live check more than most
----------------------------------------------------
``collect_all_warnings`` answers "what did the models say about their own limits,
and how much of that is shared". Three of its seven measured defects (D-067) are
**not** properties of the function at all:

- **defect 5** — §21.4 says every BLOCKED input "must be ... surfaced in every
  thesis's ``warnings``", and a blocked input is one no model could run on, so it
  is not a ``ModelResult``. Whether that obligation is met depends on whether a
  *caller* routes the blocked entries in.
- **defect 6** — §5.4's ``data_quality_flags`` are the other mandatory class, and
  whether they reach the aggregate depends on the **models layer**, not here.
- **defect 3** — whether de-duplication fires at all depends on whether the model
  authors prefix their warnings with their own name, which is a producer
  convention nothing states.

None of those can be established from a fixture. They are measured here, against
the live registry and a live snapshot, and each is asserted as a **fact about the
current wiring** so that the increment which fixes it fails loudly and updates
the record rather than quietly changing a number.

What is established here, each independently of the function
------------------------------------------------------------
1. **Real models emit warnings, and the aggregate carries a denominator.** An
   aggregate that were always empty would pass every fixture and be useless.
2. **Attribution is total on live data** — every raiser recorded, the census
   matching, which is the invariant the function asserts internally.
3. **How much de-duplication actually collapses, and why.** Today: 5 models,
   8 warnings, 0 collisions, because no live warning names its own model. The
   collapse count is printed as a fact about the data, not asserted, because
   requiring today's number would be the D-064 trap (a fixture pinned to the
   data of the day).
4. **The producer convention is not stated anywhere.** Measured: 0 of the live
   warnings name the model that raised them, so the de-dup behaviour is
   undefined-by-accident rather than chosen (defect 3).
5. **§21.4's blocked class has no route in.** The registry's blocked entries are
   counted and the number that can reach this function as specified (a
   ``ModelResult``) is reported — currently zero (O-81).
6. **§5.4's flags do not reach any model's own warnings.** The live snapshot's
   flags are counted, and the number that appear in the aggregate is reported —
   currently zero (O-82).

**What this check CANNOT establish:** whether de-duplication *should* be the
published semantics. §16.4 specifies it, so it is preserved and the alternative
is carried in ``sources``; choosing between them is a specification decision, not
a wiring fact (D-064's direction-blindness precedent).
"""

from __future__ import annotations

from macro_engine.config import get_registry
from macro_engine.data_layer.snapshot_builder import build_snapshot
from macro_engine.models.contracts import ModelResult
from macro_engine.models.gdp_nowcast import output_gap_from_snapshot
from macro_engine.models.labor_synthesis import (
    InflationSubMeasures,
    LaborInputs,
    inflation_breadth_score,
    labor_tightness_score,
)
from macro_engine.models.policy_rules import (
    FirstDifferenceInputs,
    TaylorRuleInputs,
    first_difference_rule,
    taylor_rule,
)
from macro_engine.thesis_layer.warnings import (
    UnattributedWarning,
    collect_all_warnings,
)


def _live_results() -> tuple[list[ModelResult], list[str]]:
    """Five real models through the real plumbing, plus the snapshot's flags.

    The growth leg goes through ``output_gap_from_snapshot`` rather than
    ``output_gap`` fed from each series' own last observation: ``GDPPOT`` is a CBO
    **projection** series whose last point is 2036-10-01, so the shortcut returns
    an output gap of roughly -17% (the O-7 / D-009 trap D-066's check
    documents). The snapshot's flags are returned separately because defect 6 is
    precisely that they do **not** reach the models.
    """
    snapshot, _report = build_snapshot(country="us")
    growth, gap_report = output_gap_from_snapshot(snapshot)
    print(
        f"      snapshot as_of={snapshot.as_of:%Y-%m-%d} "
        f"withheld_forward={gap_report.withheld_forward_points} "
        f"staleness={gap_report.staleness_quarters}q"
    )
    gap_value = float(growth.value) if isinstance(growth.value, (int, float)) else 0.0

    results: list[ModelResult] = [
        growth,
        inflation_breadth_score(
            InflationSubMeasures(cpi_headline_mom=0.2, cpi_core_mom=0.3, pce_core_mom=0.1)
        ),
        labor_tightness_score(
            LaborInputs(
                initial_claims_4wk_avg_change_pct=-0.4,
                jolts_openings_yoy_pct=3.0,
                jolts_quits_level_percentile=60.0,
                nfp_3m_avg=180.0,
            )
        ),
        taylor_rule(
            TaylorRuleInputs(r_star=0.5, pi_current=2.4, pi_target=2.0, output_gap=gap_value)
        ),
        first_difference_rule(
            FirstDifferenceInputs(i_prev=3.5, pi_current=2.4, pi_target=2.0, output_gap_change=0.15)
        ),
    ]
    return results, list(snapshot.data_quality_flags)


def _blocked_entries() -> list[tuple[str, str]]:
    """The registry's blocked members, as ``(name, reason)``.

    Read from the live registry rather than transcribed: the count is the point,
    and a stale literal would make the check pass after the registry changed.
    """
    registry = get_registry()
    entries: list[tuple[str, str]] = []
    for entry in registry.blocked:
        name = getattr(entry, "series_id", None) or getattr(entry, "name", None) or repr(entry)
        reason = getattr(entry, "reason", None) or getattr(entry, "note", None) or ""
        entries.append((str(name), str(reason)))
    return entries


def _check() -> None:
    results, snapshot_flags = _live_results()

    # --- (1) real models emit warnings, and the denominator exists. ---------
    print("\n  (1) five live models -> one aggregate, with a denominator")
    with_warnings = [r for r in results if r.warnings]
    assert with_warnings, (
        "no live model emitted a warning; this aggregate is untested against "
        "real data and an always-empty result would pass every fixture"
    )
    summary = collect_all_warnings(*results)
    print(f"      {summary.models_with_warnings} of {summary.contributing_models} models warned")
    print(
        f"      {len(summary.warnings)} de-duplicated text(s), "
        f"{len(summary.shared_warnings)} shared"
    )
    for source in summary.sources:
        print(f"      [{len(source.model_names)}] {source.text[:72]}")
    for model_name, own in summary.model_warnings.items():
        print(f"      {model_name:32} {len(own)} warning(s)")

    # --- (2) the attribution is total on live data. -------------------------
    print("\n  (2) the census is total -- 'never dropped', measured")
    assert summary.contributing_models == len(results)
    assert summary.models_with_warnings == len(with_warnings)
    total_raisers = sum(len(s.model_names) for s in summary.sources)
    total_own = sum(len(r.warnings) for r in results)
    print(f"      {total_raisers} raiser(s) recorded against {total_own} input warning(s)")
    assert total_raisers == total_own, "attribution lost a raiser on live data"
    assert len(summary.sources) == len(summary.warnings)

    # --- (3) how much de-duplication collapses, and why. -------------------
    print("\n  (3) de-duplication, measured rather than assumed")
    total_instances = sum(len(r.warnings) for r in results)
    collapsed = total_instances - len(summary.warnings)
    prefixed = [
        r.model_name for r in results for text in r.warnings if text.startswith(r.model_name)
    ]
    print(f"      {collapsed} of {total_instances} warning(s) collapsed on today's data")
    print(f"      {len(prefixed)} of {total_instances} warning(s) name their own model")
    assert isinstance(collapsed, int), "the count must be a number, not a phrase"
    # Reported, never required: pinning today's 0 would be the D-064 trap.
    if collapsed == 0:
        print("      -> nothing collapsed today, because no live warning is a duplicate")
    else:
        print("      -> a collision occurred; the raiser count is the only trace of it")

    # --- (4) the producer convention is unstated. --------------------------
    print("\n  (4) the prefix convention (defect 3) is not stated anywhere")
    print(f"      {len(prefixed)} of {total_instances} live warning(s) prefix their model name")
    if not prefixed:
        print("      -> whether de-dup fires is decided by an accident of authoring,")
        print("         not by a contract -- the consumer cannot control it")
    assert total_own >= 0  # the measurement is the output, not an assertion

    # --- (5) Section 21.4's blocked class has no route in. ----------------
    print("\n  (5) Section 21.4's blocked inputs (defect 5, O-81)")
    blocked = _blocked_entries()
    assert blocked, (
        "the registry has no blocked entries; Section 21.4's mandatory class is "
        "empty, so this check would be vacuous -- update it rather than delete it"
    )
    print(f"      {len(blocked)} blocked registry entr(y/ies):")
    for name, reason in blocked[:8]:
        print(f"        {name:42} {reason[:44]}")
    if len(blocked) > 8:
        print(f"        ... and {len(blocked) - 8} more")
    # A blocked input is one no model could run on, so it is not a ModelResult.
    routable = [r for r in results if r.model_name in {name for name, _ in blocked}]
    print(f"      {len(routable)} of them arrive as a ModelResult (the §16.4 signature)")
    assert not routable, (
        "a blocked registry series now produces a ModelResult; the class may have "
        "been unblocked, and O-81 and this check must be updated rather than "
        "having the assertion relaxed"
    )
    # The route this module provides, exercised on the real reasons.
    routed = collect_all_warnings(
        *results,
        unattributed=[
            UnattributedWarning(text=f"{name} unavailable", origin="blocked_input", detail=reason)
            for name, reason in blocked
        ],
    )
    print(
        f"      with `unattributed` passed: {len(routed.unattributed)} blocked entr(y/ies) routed"
    )
    assert len(routed.unattributed) == len(blocked)
    assert routed.warnings == summary.warnings, (
        "routing the blocked class must not disturb Section 16.4's published list"
    )

    # --- (6) Section 5.4's flags do not reach the models. -----------------
    print("\n  (6) Section 5.4's quality flags (defect 6, O-82)")
    assert snapshot_flags, (
        "the live snapshot carries no data_quality_flags; the disclosure class "
        "this check measures is empty, so update it rather than delete it"
    )
    leaked = [flag for flag in snapshot_flags if flag in summary.warnings]
    print(f"      {len(snapshot_flags)} snapshot flag(s):")
    for flag in snapshot_flags[:6]:
        print(f"        {flag[:88]}")
    print(f"      {len(leaked)} of them appear in the models' own warnings")
    assert not leaked, (
        "a snapshot data_quality_flag now reaches the models' own warnings; "
        "Section 5.4's disclosure class has been wired in, so defect 6 is fixed "
        "and O-82 must be closed rather than this assertion relaxed"
    )
    # The route the builder will use, exercised on the real flags.
    flagged = collect_all_warnings(
        *results,
        unattributed=[
            UnattributedWarning(text=flag, origin="data_quality_flag") for flag in snapshot_flags
        ],
    )
    print(f"      with `unattributed` passed: {len(flagged.unattributed)} flag(s) routed")
    print(f"      all_texts now carries {len(flagged.all_texts)} entr(y/ies) total")
    assert set(snapshot_flags) <= set(flagged.all_texts)

    # --- (7) the coupling of defects 1 and 6 is real. ---------------------
    print("\n  (7) the coupling (defect 7): the fix for 6 activates 1")
    coupled = [r.model_copy(update={"warnings": [*r.warnings, snapshot_flags[0]]}) for r in results]
    coupled_summary = collect_all_warnings(*coupled)
    shared_after = [s for s in coupled_summary.sources if s.text == snapshot_flags[0]]
    print("      routing flag 1 into every model's warnings:")
    print(f"        Section 16.4's list shows it {len(shared_after)} time(s)")
    print(f"        its WarningSource records {len(shared_after[0].model_names)} raiser(s)")
    assert len(shared_after) == 1, "the shared flag must appear once (it is de-duplicated)"
    assert len(shared_after[0].model_names) == len(results), (
        "the raiser count is the only surviving trace of how many models saw the "
        "flag; if this fails, the coupling measurement is stale"
    )
    print("        -> de-dup shows it once; the count is what keeps the information")

    print()
    print("  D-067 live check: PASSED")


def main() -> int:
    print("=" * 72)
    print("LIVE check: real models + real registry -> collect_all_warnings (D-067)")
    print("=" * 72)
    _check()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
