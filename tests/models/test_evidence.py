"""Tests for Module 13 — ``tag_evidence_source`` and ``count_independent_families``.

Section 15.19-D. The module exists so that agreement among signals is weighted
by **genuine source independence** rather than by how many ``ModelResult``
objects happen to be in a list. Before it shipped, ``source_independence_count``
was ``0`` at every one of its call sites in ``models/`` — the parameter existed
and nothing could supply it.

Five corrections to the specification are pinned here (D-046):

1. **The tag is a typed field, not a warning string.** §15.19-D appends
   ``source_family=<value>`` to ``warnings`` and parses it back with
   ``startswith``. A warning list is a reporting surface — any caller that
   rewrites, deduplicates or filters warnings destroys the tag *silently*.
2. **``count_independent_families`` returns a ``ModelResult``**, not a bare
   ``int`` (§22.9). Substantively: the count is uninterpretable without the
   number of **untagged** results that went into it.
3. **Tagging does not mutate its argument.** The specification appends to the
   caller's list and returns the same object, so tagging a shared result
   relabels it everywhere.
4. **Re-tagging to a different family is refused**, not silently overwritten.
5. **The enum already existed with 31 members** in ``thesis_layer``, where no
   model-layer code could reach it. It moved to ``models/`` and is re-exported.
"""

from __future__ import annotations

import pytest

from macro_engine.models.contracts import (
    ConfidenceInputs,
    ModelResult,
    compute_confidence,
    utc_now,
)
from macro_engine.models.evidence import (
    EvidenceSourceFamily,
    EvidenceTally,
    count_independent_families,
    tag_evidence_source,
)
from tests.helpers import as_int


def _result(
    name: str = "some_model",
    *,
    value: float = 1.0,
    warnings: list[str] | None = None,
) -> ModelResult:
    return ModelResult(
        model_name=name,
        country="us",
        as_of=utc_now(),
        value=value,
        confidence=0.5,
        interpretation="synthetic",
        context="synthetic",
        inputs_used=["x"],
        warnings=warnings or [],
    )


# ---------------------------------------------------------------------------
# 1. The tag is typed, and it survives what a prose channel would not
# ---------------------------------------------------------------------------


def test_the_family_is_a_typed_field_not_parsed_out_of_warnings() -> None:
    """The provenance must be readable WITHOUT scanning warning text.

    This is the correction to §15.19-D. The specification's tag is a string in
    ``warnings`` that a consumer recovers by prefix match — so anything that
    rewrites the list loses the provenance. Here the field is the record.
    """
    tagged = tag_evidence_source(_result(), EvidenceSourceFamily.BLS_CPI)
    assert tagged.source_family is EvidenceSourceFamily.BLS_CPI


def test_stripping_every_warning_does_not_lose_the_provenance() -> None:
    """The decisive test of the correction, stated as the failure it prevents.

    A pipeline that clears warnings — a dedupe step, a display filter, a
    ``MacroThesis`` that keeps only unique strings — must not thereby erase
    which source family a result came from. Under §15.19-D's string-parsing
    scheme this test fails, and it fails *silently*: the family would just
    vanish from the count.
    """
    tagged = tag_evidence_source(_result(), EvidenceSourceFamily.BEA_PCE)
    stripped = tagged.model_copy(update={"warnings": []})

    assert stripped.source_family is EvidenceSourceFamily.BEA_PCE
    tally = count_independent_families([stripped])
    assert as_int(tally, key="distinct_families") == 1


def test_a_hand_written_warning_cannot_forge_a_family() -> None:
    """Warning text is caller-controlled; the field is not.

    Under the string scheme, any code able to append ``"source_family=fake"``
    to a warning manufactures a family that no data supports. With a typed
    field the only way to set one is to pass the enum.
    """
    forged = _result(warnings=["source_family=treasury_official"])
    assert forged.source_family is None
    assert as_int(count_independent_families([forged]), key="distinct_families") == 0


# ---------------------------------------------------------------------------
# 2. The count is a measurement, and it carries its own denominator
# ---------------------------------------------------------------------------


def test_five_cpi_measures_are_one_vote_not_five() -> None:
    """The whole reason the module exists.

    Headline CPI, core CPI and any BLS-derived sub-measure share one survey, so
    agreement among them is one observation reported five times. Counting them
    as five is the false-convergence failure §22.10 exists to prevent.
    """
    results = [
        tag_evidence_source(_result(f"cpi_{i}"), EvidenceSourceFamily.BLS_CPI) for i in range(5)
    ]
    tally = count_independent_families(results)

    assert as_int(tally, key="distinct_families") == 1
    assert as_int(tally, key="tagged") == 5
    assert as_int(tally, key="duplicate_results") == 4


def test_two_genuinely_independent_sources_beat_five_redundant_ones() -> None:
    """The comparative claim, asserted rather than described.

    This is §15.19-D's own stated requirement: "Five agreeing BLS-CPI-derived
    sub-measures should never produce higher confidence than two genuinely
    independent sources agreeing."
    """
    five_redundant = [
        tag_evidence_source(_result(f"cpi_{i}"), EvidenceSourceFamily.BLS_CPI) for i in range(5)
    ]
    two_independent = [
        tag_evidence_source(_result("cpi"), EvidenceSourceFamily.BLS_CPI),
        tag_evidence_source(_result("pce"), EvidenceSourceFamily.BEA_PCE),
    ]

    redundant_count = as_int(count_independent_families(five_redundant), key="distinct_families")
    independent_count = as_int(count_independent_families(two_independent), key="distinct_families")

    assert redundant_count == 1
    assert independent_count == 2
    assert independent_count > redundant_count


def test_the_tally_reports_which_families_not_only_how_many() -> None:
    """A count alone cannot be audited; the membership can."""
    results = [
        tag_evidence_source(_result("a"), EvidenceSourceFamily.BLS_CPI),
        tag_evidence_source(_result("b"), EvidenceSourceFamily.MARKET_BREAKEVEN),
    ]
    tally = count_independent_families(results)
    assert tally.value is not None and isinstance(tally.value, dict)
    assert tally.value["families"] == ["bls_cpi", "market_breakeven"]
    # Sorted, so the published list is stable and diffable across runs.
    assert tally.value["families"] == sorted(tally.value["families"])


def test_the_count_never_returns_a_bare_int() -> None:
    """§22.9 — no model returns a bare number."""
    tally = count_independent_families(
        [tag_evidence_source(_result(), EvidenceSourceFamily.BLS_CPI)]
    )
    assert isinstance(tally, ModelResult)
    assert not isinstance(tally.value, int)
    assert isinstance(tally.value, dict)
    # And the dict validates as the declared tally shape.
    EvidenceTally.model_validate(tally.value)


def test_the_count_reports_the_untagged_denominator() -> None:
    """Three families from three signals is a different claim from three of nine.

    An untagged result is neither independent nor redundant — it is *unknown* —
    so it must be excluded from the count AND reported, which a bare int cannot
    do.
    """
    results = [
        tag_evidence_source(_result("a"), EvidenceSourceFamily.BLS_CPI),
        _result("b"),
        _result("c"),
    ]
    tally = count_independent_families(results)

    assert as_int(tally, key="distinct_families") == 1
    assert as_int(tally, key="tagged") == 1
    assert as_int(tally, key="untagged") == 2
    assert any("carry no source family" in w for w in tally.warnings)


def test_untagged_results_are_not_assumed_independent() -> None:
    """The dangerous default, stated as a test.

    Treating an untagged result as its own family would restore exactly the
    false convergence the module prevents — it would make provenance ignorance
    look like corroboration.
    """
    untagged = [_result(f"m{i}") for i in range(4)]
    tally = count_independent_families(untagged)
    assert as_int(tally, key="distinct_families") == 0
    assert as_int(tally, key="untagged") == 4


# ---------------------------------------------------------------------------
# 3. Confidence comes from compute_confidence, and independence is not claimed
# ---------------------------------------------------------------------------


def test_confidence_is_not_credited_for_its_own_subject_matter() -> None:
    """The count's OWN confidence must not depend on the count.

    Crediting ``source_independence_count=distinct_families`` here would be
    circular — the census would rate itself more reliable the more families it
    found (D-027's circularity class). It is a heuristic census of a
    hand-assigned vocabulary, so it takes the heuristic penalty and no bonus.
    """
    many = [
        tag_evidence_source(_result(f"m{i}"), family)
        for i, family in enumerate(
            [
                EvidenceSourceFamily.BLS_CPI,
                EvidenceSourceFamily.BEA_PCE,
                EvidenceSourceFamily.BLS_PPI,
            ]
        )
    ]
    one = [tag_evidence_source(_result("m"), EvidenceSourceFamily.BLS_CPI)]

    assert count_independent_families(many).confidence == count_independent_families(one).confidence


def test_the_census_confidence_is_the_heuristic_penalised_value() -> None:
    """Pin the ABSOLUTE confidence, not a comparison between two calls.

    The invariance test above compares two calls of the same function, so it
    moves together with any change to how the census computes confidence — it
    cannot detect the heuristic penalty being dropped. This one derives the
    expected value from ``compute_confidence`` with the documented factors and
    asserts the census matches it exactly.

    A mutation that drops ``is_heuristic_not_calibrated=True`` therefore fails
    here, which the invariance test alone would not catch.
    """
    expected = compute_confidence(
        ConfidenceInputs(is_heuristic_not_calibrated=True, source_independence_count=0)
    )
    unpenalised = compute_confidence(
        ConfidenceInputs(is_heuristic_not_calibrated=False, source_independence_count=0)
    )

    tally = count_independent_families(
        [tag_evidence_source(_result(), EvidenceSourceFamily.BLS_CPI)]
    )

    assert tally.confidence == expected
    assert tally.confidence != unpenalised


# ---------------------------------------------------------------------------
# 4. Tagging is a copy, and the re-tag is refused
# ---------------------------------------------------------------------------


def test_tagging_does_not_mutate_its_argument() -> None:
    """A provenance fact attaches to a value; it does not relabel the original.

    §15.19-D appends to the caller's ``warnings`` and returns the SAME object,
    so tagging a result that is referenced elsewhere silently re-tags every
    reference to it.
    """
    original = _result("shared")
    tagged = tag_evidence_source(original, EvidenceSourceFamily.BLS_CPI)

    assert original.source_family is None
    assert original.warnings == []
    assert tagged is not original
    assert tagged.source_family is EvidenceSourceFamily.BLS_CPI


def test_retagging_to_a_different_family_is_refused() -> None:
    """Provenance is decided once; a conflicting tag is a bug, not a preference."""
    tagged = tag_evidence_source(_result(), EvidenceSourceFamily.BLS_CPI)
    with pytest.raises(ValueError, match="already tagged"):
        tag_evidence_source(tagged, EvidenceSourceFamily.BEA_PCE)


def test_retagging_idempotently_is_allowed() -> None:
    """A pipeline may legitimately apply the same tag twice."""
    once = tag_evidence_source(_result(), EvidenceSourceFamily.BLS_CPI)
    twice = tag_evidence_source(once, EvidenceSourceFamily.BLS_CPI)
    assert twice.source_family is EvidenceSourceFamily.BLS_CPI
    # And the note is not duplicated.
    assert sum(1 for w in twice.warnings if "Evidence source family" in w) == 1


def test_a_data_quality_flag_is_recorded_without_rewriting_confidence() -> None:
    """§22.8 — compute_confidence is the only producer; the tagger is not one.

    The flag is recorded so a convergence caller can price it. Rewriting the
    confidence of an already-built result here would create a second producer.
    """
    before = _result()
    after = tag_evidence_source(
        before, EvidenceSourceFamily.BLS_CPI, data_quality_flags_present=True
    )
    assert after.confidence == before.confidence
    assert after.data_quality_flags_present is True
    assert before.data_quality_flags_present is False


# ---------------------------------------------------------------------------
# 5. Degenerate and adversarial inputs
# ---------------------------------------------------------------------------


def test_an_empty_list_is_zero_families_and_disclosed() -> None:
    """ "Nothing to count" is a state, not an error — but it must say which it is.

    Raising would force every incremental pipeline into exception handling;
    silently returning 0 would let an empty list read as a measured absence of
    independence.
    """
    tally = count_independent_families([])
    assert as_int(tally, key="distinct_families") == 0
    assert any("NO RESULTS SUPPLIED" in w for w in tally.warnings)


def test_one_family_reported_many_times_is_called_out() -> None:
    """The single most likely false-positive: internal agreement sold as convergence."""
    results = [
        tag_evidence_source(_result(f"m{i}"), EvidenceSourceFamily.BLS_CPI) for i in range(3)
    ]
    tally = count_independent_families(results)
    assert any("ONE family" in w for w in tally.warnings)


def test_every_warning_path_is_triggered_by_some_test() -> None:
    """§21.2 Step 5 — an untested warning path is an untested safety mechanism.

    Collects the warnings each fixture produces and asserts all four branches
    are exercised somewhere in this file.
    """
    observed: set[str] = set()

    def add(results: list[ModelResult]) -> None:
        observed.update(count_independent_families(results).warnings)

    add([])
    add([_result("a")])
    add([tag_evidence_source(_result("a"), EvidenceSourceFamily.BLS_CPI)])
    add(
        [
            tag_evidence_source(_result("a"), EvidenceSourceFamily.BLS_CPI),
            tag_evidence_source(_result("b"), EvidenceSourceFamily.BLS_CPI),
        ]
    )

    assert any("NO RESULTS SUPPLIED" in w for w in observed)
    assert any("carry no source family" in w for w in observed)
    assert any("collapsed to a single vote" in w for w in observed)
    assert any("ONE family" in w for w in observed)


def test_the_family_field_preserves_the_enum_type_on_a_round_trip() -> None:
    """A `str` annotation would silently DEMOTE the tag to a bare string.

    Pydantic coerces a ``str``-Enum value to a plain ``str`` when the field is
    annotated ``str | None``. The tag would survive as text but stop being the
    enum, so ``is`` comparisons against ``EvidenceSourceFamily`` members — which
    the counter relies on for its set keys — would quietly degrade to string
    equality, and a typo in a family name would read as a new family.
    """
    tagged = tag_evidence_source(_result(), EvidenceSourceFamily.BLS_CPI)

    # Must be the enum, not its value.
    assert isinstance(tagged.source_family, EvidenceSourceFamily)
    assert tagged.source_family is EvidenceSourceFamily.BLS_CPI
    assert not isinstance(tagged.source_family, str) or isinstance(
        tagged.source_family, EvidenceSourceFamily
    )

    # And it must survive a serialise/reload cycle, since the thesis layer
    # receives it through JSON.
    reloaded = ModelResult.model_validate(tagged.model_dump())
    assert reloaded.source_family is EvidenceSourceFamily.BLS_CPI


def test_the_enum_keeps_its_str_base_so_values_round_trip() -> None:
    """The `str` base is load-bearing, not decorative.

    Without it the enum would not deserialise from its own value, and the
    vocabulary could not arrive through JSON at all.
    """
    assert issubclass(EvidenceSourceFamily, str)
    assert EvidenceSourceFamily("bls_cpi") is EvidenceSourceFamily.BLS_CPI
    for member in EvidenceSourceFamily:
        assert EvidenceSourceFamily(member.value) is member


def test_the_family_vocabulary_has_no_declared_but_unreachable_member() -> None:
    """Every member must be constructible from its own string value (D-045a).

    A vocabulary is a promise in both directions: each declared member must be
    producible, and each value must round-trip. The round-trip is what the
    thesis layer's ``source_family`` field relies on when it arrives from JSON.
    """
    for member in EvidenceSourceFamily:
        assert EvidenceSourceFamily(member.value) is member
        assert member.value == member.value.lower()


def test_the_enum_is_reachable_from_both_layers_as_one_object() -> None:
    """The move must not fork the vocabulary into two types.

    ``thesis_layer`` re-exports it; a copy left behind would compare unequal to
    the models-layer enum and every tag comparison would silently fail.
    """
    from macro_engine.thesis_layer.schemas import EvidenceSourceFamily as ThesisLayerFamily

    assert ThesisLayerFamily is EvidenceSourceFamily
    assert len(list(EvidenceSourceFamily)) == 31


def test_an_integer_value_is_still_counted_as_a_signal() -> None:
    """Non-float values are results too — the count must not skip them.

    A ``ModelResult`` whose value is a string or a dict is still evidence, and
    the family census is about provenance, not about value type. This guards the
    temptation to filter by numeric value.
    """
    odd = _result("categorical").model_copy(update={"value": "late_expansion"})
    tagged = tag_evidence_source(odd, EvidenceSourceFamily.BLS_CPI)
    tally = count_independent_families([tagged, _result("other")])
    assert as_int(tally, key="tagged") == 1
    assert as_int(tally, key="untagged") == 1
