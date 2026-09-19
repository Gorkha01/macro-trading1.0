"""Tests for ``collect_all_warnings`` (§16.4, D-067).

The defects this file exists to pin
-----------------------------------
§16.4's sample is nine lines and returns a flat ``list[str]``. Seven defects were
measured against it (``.probe/probe_warnings_defects.py``,
``.probe/probe_warnings_live.py``, ``.probe/probe_warnings_section21.py``); each
has a pin here.

1. **De-duplication destroys the count, and the count is the signal.** Four
   models raising the identical string aggregate to one entry.
   ``test_the_count_of_raisers_survives_de_duplication`` and
   ``test_shared_warnings_exposes_only_the_multiply_raised``.
2. **The output cannot attribute a warning to its source.** Two models with
   identical warnings produce a one-element list with no trace of the second.
   ``test_every_warning_records_which_models_raised_it``.
3. **Whether de-dup fires is decided by an unstated producer convention.**
   ``test_a_prefixed_warning_does_not_collapse_but_an_unprefixed_one_does``.
4. **"No warnings" and "not passed" are the same value.**
   ``test_a_warning_free_model_is_distinguishable_from_a_missing_one`` and
   ``test_an_empty_call_still_reports_its_denominator``.
5. **Section 21.4's blocked class has no route in.**
   ``test_a_blocked_input_is_carried_without_a_model_result``.
6. **Section 5.4's disclosures do not reach the aggregate.**
   ``test_a_quality_flag_is_carried_as_an_unattributed_warning``.
7. **Defects 1 and 6 are coupled** — fixing 6 activates 1.
   ``test_routing_a_shared_flag_through_every_model_is_then_counted`` provokes
   exactly that, so the coupling is a test rather than a note.

Plus the structural pins: §16.4's ``warnings`` is unchanged in content and
order, the census is total, the records are frozen, the origin vocabulary is
closed, and the two §21.4/§5.4 origins are the ones the specification names.
"""

from __future__ import annotations

import typing
from collections.abc import Iterator

import pytest
from pydantic import ValidationError

from macro_engine.models.contracts import ModelResult, utc_now
from macro_engine.thesis_layer.warnings import (
    UnattributedWarning,
    WarningSource,
    WarningSummary,
    collect_all_warnings,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _result(model_name: str, *warnings: str) -> ModelResult:
    """A minimal but schema-valid ``ModelResult`` carrying ``warnings``."""
    return ModelResult(
        model_name=model_name,
        country="us",
        as_of=utc_now(),
        value=1.0,
        confidence=0.5,
        interpretation="a reading",
        context="test",
        inputs_used=[],
        warnings=list(warnings),
    )


def _blocked(text: str, detail: str | None = "registry reason") -> UnattributedWarning:
    return UnattributedWarning(text=text, origin="blocked_input", detail=detail)


def _flag(text: str, detail: str | None = "CPIAUCSL @2026-09-01") -> UnattributedWarning:
    return UnattributedWarning(text=text, origin="data_quality_flag", detail=detail)


# ---------------------------------------------------------------------------
# Defect 1 — de-duplication destroys the count
# ---------------------------------------------------------------------------


def test_the_count_of_raisers_survives_de_duplication() -> None:
    """Four models raising one identical string: the list has 1, the count has 4.

    ``warnings`` must still be §16.4's one-element de-duplicated list — that is
    the contract, and changing it would silently change what the published field
    means. The count lives in ``sources`` instead, which is the whole repair.
    """
    shared = "CPIAUCSL revision pending"
    summary = collect_all_warnings(
        _result("output_gap", shared),
        _result("inflation_breadth_score", shared),
        _result("labor_tightness_score", shared),
        _result("regime_classifier", shared),
    )

    assert summary.warnings == (shared,), "§16.4's de-duplicated list must be unchanged"
    assert len(summary.sources) == 1
    source = summary.sources[0]
    assert source.text == shared
    assert source.model_names == (
        "output_gap",
        "inflation_breadth_score",
        "labor_tightness_score",
        "regime_classifier",
    )
    assert source.raised_by_multiple_models is True


def test_a_single_raiser_is_not_reported_as_shared() -> None:
    """The flag the flat list cannot express must be False here, not absent."""
    summary = collect_all_warnings(_result("only_one", "solo"))
    assert summary.sources[0].model_names == ("only_one",)
    assert summary.sources[0].raised_by_multiple_models is False


def test_shared_warnings_exposes_only_the_multiply_raised() -> None:
    """``shared_warnings`` is the subset a reader wants, and it must be exact."""
    summary = collect_all_warnings(
        _result("a", "solo_a", "shared"),
        _result("b", "solo_b", "shared"),
        _result("c", "solo_c"),
    )
    assert summary.warnings == ("solo_a", "shared", "solo_b", "solo_c")
    assert [s.text for s in summary.shared_warnings] == ["shared"]


# ---------------------------------------------------------------------------
# Defect 2 — the output cannot attribute a warning to its source
# ---------------------------------------------------------------------------


def test_every_warning_records_which_models_raised_it() -> None:
    """Two models, byte-identical warnings, and the trace must survive."""
    summary = collect_all_warnings(
        _result("growth", "stale vintage"),
        _result("inflation", "stale vintage"),
    )
    assert summary.warnings == ("stale vintage",)
    assert summary.sources[0].model_names == ("growth", "inflation")


def test_the_raiser_order_follows_the_argument_order() -> None:
    """Determinism: two runs with the same input order give the same raiser order."""
    results = [
        _result("z_model", "shared"),
        _result("a_model", "shared"),
    ]
    first = collect_all_warnings(*results).sources[0].model_names
    second = collect_all_warnings(*results).sources[0].model_names
    assert first == ("z_model", "a_model"), "first-appearance order, not sorted"
    assert first == second


def test_model_warnings_groups_by_source() -> None:
    """A reader must be able to group by model, which flat order alone cannot."""
    summary = collect_all_warnings(
        _result("growth", "g1", "g2"),
        _result("labor"),
        _result("inflation", "i1"),
    )
    assert summary.model_warnings == {
        "growth": ("g1", "g2"),
        "labor": (),
        "inflation": ("i1",),
    }


# ---------------------------------------------------------------------------
# Defect 3 — de-dup behaviour depends on an unstated producer convention
# ---------------------------------------------------------------------------


def test_a_prefixed_warning_does_not_collapse_but_an_unprefixed_one_does() -> None:
    """The measured fact: the SAME logical warning aggregates two ways.

    A producer that prefixes its ``model_name`` makes the strings differ, so
    nothing collapses; one that does not makes them identical, so everything
    does. The consumer cannot control which, and the contract does not say.
    Both are pinned so that a change to either behaviour is visible.
    """
    prefixed = collect_all_warnings(
        _result("model_a", "model_a: input unavailable"),
        _result("model_b", "model_b: input unavailable"),
    )
    assert len(prefixed.warnings) == 2, "prefixed warnings must NOT collapse"

    unprefixed = collect_all_warnings(
        _result("model_a", "input unavailable"),
        _result("model_b", "input unavailable"),
    )
    assert len(unprefixed.warnings) == 1, "identical unprefixed warnings DO collapse"
    # ...but the attribution records both, which is why the collapse is no
    # longer a loss.
    assert unprefixed.sources[0].model_names == ("model_a", "model_b")


def test_no_live_authored_warning_is_expected_to_prefix() -> None:
    """The convention is not stated anywhere, so the module must not assume it.

    This pins the module's own choice: it treats the text as opaque. A warning
    that happens to look prefixed is not parsed; one that does not is not
    augmented. If a future increment adds prefixing, this test is where the
    change has to be acknowledged.
    """
    summary = collect_all_warnings(_result("growth", "output_gap: something"))
    assert summary.warnings == ("output_gap: something",), "text passes through verbatim"
    assert summary.sources[0].model_names == ("growth",)


# ---------------------------------------------------------------------------
# Defect 4 — "no warnings" and "not passed" are the same value
# ---------------------------------------------------------------------------


def test_a_warning_free_model_is_distinguishable_from_a_missing_one() -> None:
    """One quiet model: 1 contributing, 0 with warnings — not an empty result."""
    quiet = collect_all_warnings(_result("quiet_model"))
    nothing = collect_all_warnings()

    assert quiet.warnings == () and nothing.warnings == ()
    assert quiet.contributing_models == 1
    assert nothing.contributing_models == 0
    assert quiet.models_with_warnings == 0
    assert quiet != nothing, "the two states must not be the same object value"


def test_an_empty_call_still_reports_its_denominator() -> None:
    """The denominator is the field that makes ``warnings`` readable as severity."""
    summary = collect_all_warnings()
    assert summary.contributing_models == 0
    assert summary.models_with_warnings == 0
    assert summary.model_warnings == {}


def test_the_denominators_are_reported_separately() -> None:
    """'3 of 9 models warned' is a different statement from '3 models warned'."""
    results = [_result(f"m{i}", "w") for i in range(3)] + [_result(f"quiet{i}") for i in range(6)]
    summary = collect_all_warnings(*results)
    assert summary.contributing_models == 9
    assert summary.models_with_warnings == 3


# ---------------------------------------------------------------------------
# Defect 5 — Section 21.4's blocked class has no route in
# ---------------------------------------------------------------------------


def test_a_blocked_input_is_carried_without_a_model_result() -> None:
    """§21.4: blocked inputs 'must be ... surfaced in every thesis's warnings'.

    A blocked input is one no model could run on, so it is not a ModelResult and
    §16.4's signature cannot express it. It is passed as an unattributed warning
    and must appear in the aggregate.
    """
    summary = collect_all_warnings(
        _result("growth", "growth caveat"),
        unattributed=[
            _blocked(
                "iron_ore_change_pct unavailable",
                "No clean free source for iron ore prices.",
            ),
            _blocked("conference_board_lei unavailable", "Licensed product, no free API."),
        ],
    )
    assert len(summary.unattributed) == 2
    assert {w.origin for w in summary.unattributed} == {"blocked_input"}
    assert "iron_ore_change_pct unavailable" in summary.all_texts
    assert summary.unattributed[0].detail == "No clean free source for iron ore prices."


def test_a_blocked_input_is_not_merged_into_warnings() -> None:
    """§16.4's list is the models' own; a blocked input is a different claim.

    Merging them would make ``warnings`` mean two things at once and would hide
    which class was raised — the same confusion D-066 refused when it kept
    ``unreadable`` out of ``signals``.
    """
    summary = collect_all_warnings(
        _result("growth", "model said so"),
        unattributed=[_blocked("blocked thing")],
    )
    assert summary.warnings == ("model said so",)
    assert tuple(w.text for w in summary.unattributed) == ("blocked thing",)


# ---------------------------------------------------------------------------
# Defect 6 — Section 5.4's disclosures do not reach the aggregate
# ---------------------------------------------------------------------------


def test_a_quality_flag_is_carried_as_an_unattributed_warning() -> None:
    """§5.4's flags are a mandatory disclosure class and are not model results."""
    flag_text = "[ERROR] iorb @2026-09-20: FUTURE_OBSERVATION_DATE"
    summary = collect_all_warnings(
        _result("growth"),
        unattributed=[_flag(flag_text)],
    )
    assert summary.unattributed[0].origin == "data_quality_flag"
    assert summary.unattributed[0].text == flag_text
    assert flag_text in summary.all_texts


def test_the_two_mandatory_origins_are_the_ones_the_specification_names() -> None:
    """The origin vocabulary must contain §21.4's and §5.4's classes."""
    from typing import get_args

    from macro_engine.thesis_layer.warnings import WarningOrigin

    origins = set(get_args(WarningOrigin))
    assert "blocked_input" in origins, "§21.4's class must have an origin"
    assert "data_quality_flag" in origins, "§5.4's class must have an origin"


def test_an_unlisted_origin_is_refused() -> None:
    """A closed vocabulary: a typo is a ValidationError, not a new string."""
    with pytest.raises(ValidationError):
        UnattributedWarning(text="x", origin="not_a_real_origin")  # type: ignore[arg-type]


def test_the_caller_origin_exists_for_everything_else() -> None:
    """A third member, so a caller is not forced to mislabel."""
    w = UnattributedWarning(text="builder-level caveat", origin="caller")
    assert w.origin == "caller"


def test_unattributed_order_is_preserved() -> None:
    """Order as given — the caller's ordering carries meaning, as §16.4's does."""
    summary = collect_all_warnings(
        unattributed=[_blocked("first"), _flag("second"), _blocked("third")],
    )
    assert tuple(w.text for w in summary.unattributed) == ("first", "second", "third")
    assert summary.all_texts == ("first", "second", "third")


def test_all_texts_puts_the_models_warnings_first() -> None:
    """``all_texts`` is ``warnings`` **then** the unattributed texts — ordered.

    The order is not cosmetic. ``all_texts`` is the union a caller reads when
    asking "is anything being disclosed at all", and §16.4's list is the part
    that has a published meaning; the unattributed class is the supplement. A
    version that puts the supplement first reorders the answer without changing
    its contents, which is exactly the kind of change no content assertion sees.

    Found by the D-067 sweep: reversing the concatenation **survived** the whole
    selection, because ``test_unattributed_order_is_preserved`` above passes only
    unattributed warnings (so the two halves cannot interleave) and every other
    ``all_texts`` assertion is either a membership test or a case with one half
    empty. The mutation was a real blind spot in this file, not an inert change.
    """
    summary = collect_all_warnings(
        _result("growth", "model_warning"),
        unattributed=[_blocked("blocked_thing"), _flag("flag_thing")],
    )
    assert summary.all_texts == ("model_warning", "blocked_thing", "flag_thing")
    assert summary.warnings == ("model_warning",)
    assert tuple(w.text for w in summary.unattributed) == ("blocked_thing", "flag_thing")


# ---------------------------------------------------------------------------
# Defect 7 — defects 1 and 6 are COUPLED
# ---------------------------------------------------------------------------


def test_routing_a_shared_flag_through_every_model_is_then_counted() -> None:
    """The natural fix for defect 6 activates defect 1 — measured, not asserted.

    Routing a snapshot flag into every model's own ``warnings`` (the obvious way
    to honour §21.4) makes all N models raise the same string. §16.4's de-dup
    then collapses N to 1. This test provokes exactly that and shows the
    attribution is what keeps the information, so a repair that fixes the two
    defects separately will reintroduce one.
    """
    snapshot_flag = "[ERROR] CPIAUCSL: STALE — 32 days beyond tolerance"
    # Every model built from the degraded snapshot carries the same flag.
    results = [_result(f"model_{i}", snapshot_flag, f"local_{i}") for i in range(5)]
    summary = collect_all_warnings(*results)

    assert len(summary.warnings) == 6, "one shared text + five local ones"
    shared = summary.shared_warnings
    assert len(shared) == 1
    assert shared[0].model_names == tuple(f"model_{i}" for i in range(5))
    print(f"\n  the shared flag was raised by {len(shared[0].model_names)} models")
    print("  and §16.4's list shows it exactly once — the count survives in sources")


# ---------------------------------------------------------------------------
# Section 16.4's list, structurally
# ---------------------------------------------------------------------------


def test_warnings_is_de_duplicated_and_order_preserved() -> None:
    """§16.4's two stated properties, on an interleaved input."""
    summary = collect_all_warnings(
        _result("growth", "G1", "SHARED"),
        _result("inflation", "SHARED", "I1"),
        _result("labor", "L1", "G1"),
    )
    assert summary.warnings == ("G1", "SHARED", "I1", "L1"), "first-seen order, de-duplicated"


def test_no_input_warning_is_dropped() -> None:
    """'Never dropped' (Section 7.2 step 9), in the strongest form available."""
    results = [
        _result("a", "w1", "w2"),
        _result("b", "w2", "w3"),
        _result("c"),
        _result("d", "w4"),
    ]
    summary = collect_all_warnings(*results)
    every_own = [w for r in results for w in r.warnings]
    assert set(summary.warnings) == set(every_own)
    total_recorded = sum(len(s.model_names) for s in summary.sources)
    assert total_recorded == len(every_own), "every raiser is attributed exactly once"


def test_sources_align_one_to_one_with_warnings() -> None:
    """The two must never desynchronise — the census is asserted in the function."""
    summary = collect_all_warnings(
        _result("a", "x", "y"),
        _result("b", "y", "z"),
    )
    assert len(summary.warnings) == len(summary.sources)
    assert tuple(s.text for s in summary.sources) == summary.warnings


def test_the_summary_is_frozen() -> None:
    """Published records are immutable, as the other thesis-layer models are."""
    summary = collect_all_warnings(_result("a", "w"))
    with pytest.raises(ValidationError):
        summary.warnings = ()


def test_the_models_are_frozen_and_forbid_extra() -> None:
    """Both published records: frozen, and no silent extra fields.

    Note ``WarningSource(text="x", model_names=())`` is **valid** — an empty
    raiser tuple is a legal (if useless) value, so it is not the way to test
    ``extra="forbid"``. The extra field is.
    """
    with pytest.raises(ValidationError):
        WarningSource(text="x", model_names=("m",), not_a_field=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        UnattributedWarning(text="x", origin="caller", not_a_field=1)  # type: ignore[call-arg]

    for model in (
        WarningSource(text="x", model_names=("m",)),
        UnattributedWarning(text="x", origin="caller"),
    ):
        with pytest.raises(ValidationError):
            model.text = "y"


def test_the_return_type_is_the_summary_not_a_list() -> None:
    """The type change IS the repair — a list has nowhere to put either answer."""
    summary = collect_all_warnings(_result("a", "w"))
    assert isinstance(summary, WarningSummary)

    # The structural half: a list has no attribute for either answer, which is
    # the literal reason the return type had to change. Checked by syntax
    # because mypy proves the type case unreachable — `isinstance(summary,
    # list)` after `isinstance(summary, WarningSummary)` is a subclass that
    # "cannot exist" (it would need incompatible method signatures), so the
    # runtime assertion mypy rejects is replaced by one it cannot.
    annotations = typing.get_type_hints(collect_all_warnings)["return"]
    assert annotations is WarningSummary, (
        f"collect_all_warnings returns {annotations!r}; Section 16.4's flat "
        f"list[str] cannot carry attribution, denominators or the unattributed "
        f"class (D-067 defects 1, 2 and 4)"
    )
    assert not hasattr(summary, "append"), (
        "the summary must not be list-like: an append would silently accept an "
        "unattributed warning into Section 16.4's published list"
    )


def test_the_spec_signature_still_works_positionally() -> None:
    """§16.4's call form must not break: ``collect_all_warnings(a, b, c)``."""
    summary = collect_all_warnings(
        _result("growth", "g"),
        _result("inflation", "i"),
        _result("labor", "l"),
    )
    assert summary.warnings == ("g", "i", "l")


def test_unattributed_defaults_to_empty_so_existing_callers_are_unaffected() -> None:
    """A caller that passes only results gets an empty unattributed tuple."""
    summary = collect_all_warnings(_result("a", "w"))
    assert summary.unattributed == ()
    assert summary.all_texts == ("w",)


def test_unattributed_accepts_any_iterable() -> None:
    """A generator must work, not only a list — the annotation says so."""

    def gen() -> Iterator[UnattributedWarning]:
        yield _blocked("one")
        yield _flag("two")

    summary = collect_all_warnings(unattributed=gen())
    assert tuple(w.text for w in summary.unattributed) == ("one", "two")


# ---------------------------------------------------------------------------
# Live (deselected by default)
# ---------------------------------------------------------------------------


@pytest.mark.live
def test_live_models_produce_a_warning_summary_with_a_denominator() -> None:
    """Aggregate the warnings of real models, and measure the two §21.4 classes.

    The live claims an offline test cannot make:

    1. **Real models emit warnings, and they are non-empty.** A summariser over
       real results must return something; an aggregate that is always empty
       would pass every fixture and be useless.
    2. **The attribution is total on live data** — every raiser recorded, the
       census matching, which is the invariant the function asserts internally.
    3. **The two mandatory classes genuinely do not reach the aggregate.**
       Measured: the live snapshot's ``data_quality_flags`` do **not** appear in
       the models' own warnings, and the registry's blocked entries have no
       ``ModelResult`` behind them at all (defects 5 and 6). This is asserted as
       a *fact about the current wiring*, not as desired behaviour, so the
       increment that wires them will fail here and have to say so.
    4. **Whether de-duplication collapses anything is a fact about the data.**
       Today it collapses nothing (5 models, 8 warnings, 0 collisions); the test
       records that without requiring it, because requiring it would be the
       D-064 trap — a fixture pinned to today's numbers.

    Deselected unless ``-m live``.
    """
    from macro_engine.config import get_registry
    from macro_engine.data_layer.snapshot_builder import build_snapshot
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

    snapshot, _report = build_snapshot(country="us")
    growth, _gap_report = output_gap_from_snapshot(snapshot)
    gap_value = float(growth.value) if isinstance(growth.value, (int, float)) else 0.0

    results = [
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

    # (1) real models emit warnings.
    with_warnings = [r for r in results if r.warnings]
    assert with_warnings, "no live model emitted a warning; the aggregate is untested"

    summary = collect_all_warnings(*results)

    # (2) the attribution is total.
    assert summary.contributing_models == len(results)
    assert summary.models_with_warnings == len(with_warnings)
    assert sum(len(s.model_names) for s in summary.sources) == sum(len(r.warnings) for r in results)
    assert len(summary.sources) == len(summary.warnings)

    print(f"\n  {summary.models_with_warnings} of {summary.contributing_models} live models warned")
    print(f"  {len(summary.warnings)} de-duplicated text(s), {len(summary.shared_warnings)} shared")
    for s in summary.sources:
        print(f"    [{len(s.model_names)}] {s.text[:78]}")

    # (3) the two mandatory classes really are unreachable today.
    snapshot_flags = list(snapshot.data_quality_flags)
    leaked = [f for f in snapshot_flags if f in summary.warnings]
    assert not leaked, (
        f"{len(leaked)} snapshot data_quality_flag(s) now reach the models' own "
        f"warnings — Section 5.4's disclosure class has been wired in, so "
        f"defect 6 is fixed and this test (and O-82) must be updated rather "
        f"than deleted"
    )
    print(f"  {len(snapshot_flags)} snapshot flag(s), 0 reaching the aggregate (defect 6, open)")

    blocked = get_registry().blocked
    assert blocked, "the registry has no blocked entries; §21.4's class is empty"
    print(f"  {len(blocked)} blocked registry entr(y/ies), 0 with a ModelResult (defect 5, open)")

    # (4) the collision count is reported, not required.
    total_instances = sum(len(r.warnings) for r in results)
    collapsed = total_instances - len(summary.warnings)
    print(
        f"  de-duplication collapsed {collapsed} of {total_instances} warning(s) "
        f"on today's live data — a fact about the data, not a property of the code"
    )
