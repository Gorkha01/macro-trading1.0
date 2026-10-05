"""Smoke verification for models/evidence_family.py (Module 13 vocabulary).

This module is a pure enum — no arithmetic, no model logic. The only defect class
is a wrong or duplicated member value, so the check is: documented members carry
their documented string values, and all values are unique (a duplicated value would
silently merge two independent upstream production processes into one "family").
"""

from __future__ import annotations

from macro_engine.models.evidence_family import EvidenceSourceFamily


def test_documented_members_and_values() -> None:
    assert EvidenceSourceFamily.BLS_CPI.value == "bls_cpi"
    assert EvidenceSourceFamily.BLS_PPI.value == "bls_ppi"
    assert EvidenceSourceFamily.BEA_PCE.value == "bea_pce"
    assert EvidenceSourceFamily.BEA_NIPA.value == "bea_nipa"
    assert EvidenceSourceFamily.FED_H41.value == "fed_h41"
    assert EvidenceSourceFamily.MANUAL_ASSESSMENT.value == "manual_assessment"


def test_cpi_and_ppi_are_distinct_families() -> None:
    # The whole point of the enum: separate surveys => separate families.
    assert EvidenceSourceFamily.BLS_CPI != EvidenceSourceFamily.BLS_PPI  # type: ignore[comparison-overlap]


def test_all_values_unique() -> None:
    values = [m.value for m in EvidenceSourceFamily]
    assert len(values) == len(set(values))


def test_names_and_values_are_unique_and_mechanically_consistent() -> None:
    """Two independent invariants, checked separately.

    A duplicate NAME is impossible in a Python enum (it silently becomes an
    alias), so the real exposure is a duplicate VALUE — which merges two
    upstream production processes into one family and destroys exactly the
    independence the enum exists to encode.

    The name/value correspondence is asserted by CONSTRUCTION rather than by
    listing members, so it cannot drift as members are added: every value must
    be the lowercased name. A new member with a hand-typed value that disagrees
    fails here instead of silently becoming a second spelling of one family.
    """
    members = list(EvidenceSourceFamily)
    names = [m.name for m in members]
    values = [m.value for m in members]

    assert len(names) == len(set(names)), "duplicate member name"
    assert len(values) == len(set(values)), "duplicate member VALUE merges two families"

    mismatched = [(m.name, m.value) for m in members if m.name.lower() != m.value]
    assert not mismatched, f"name/value convention violated by {mismatched}"


def test_the_enum_is_a_str_enum_so_it_serialises_and_compares_as_a_string() -> None:
    """`class EvidenceSourceFamily(str, Enum)` is load-bearing.

    It appears in `ModelResult.source_family`, which is serialised to JSON and
    compared against registry strings. If the `str` base were dropped the
    values would still print, but `==` against a plain string would become
    False and every family census would silently count zero families.
    """
    import json

    assert isinstance(EvidenceSourceFamily.BLS_CPI, str)
    assert EvidenceSourceFamily.BLS_CPI == "bls_cpi"  # type: ignore[comparison-overlap]
    assert json.dumps(EvidenceSourceFamily.BLS_CPI) == '"bls_cpi"'
    # a bare Enum would fail both of the above
    assert EvidenceSourceFamily("bls_cpi") is EvidenceSourceFamily.BLS_CPI


def test_headline_and_core_cpi_are_one_member_as_documented() -> None:
    """The docstring's second worked example: same survey, same family.

    The module argues BLS_CPI and BLS_PPI are separate because they are separate
    surveys with separate samples, while headline and core CPI are one member
    because a BLS survey redesign corrupts both at the same moment. That claim
    is only true if there is NO separate core member — assert its absence
    rather than trusting the prose.
    """
    names = {m.name for m in EvidenceSourceFamily}
    core_inflation_members = {n for n in names if "CORE" in n}
    assert core_inflation_members == set(), (
        f"a core-inflation member {core_inflation_members} contradicts the "
        "documented 'headline and core CPI are one family' rule"
    )
    # and the two that ARE separate are present and distinct
    assert EvidenceSourceFamily.BLS_CPI is not EvidenceSourceFamily.BLS_PPI  # type: ignore[comparison-overlap]
    assert EvidenceSourceFamily.BLS_CPI is not EvidenceSourceFamily.BEA_PCE  # type: ignore[comparison-overlap]


def test_every_census_consumer_gets_a_member_it_can_actually_hold() -> None:
    """Round-trip the vocabulary against its own consumers.

    Every module that census-counts families must build them from THIS enum. A
    string that is not a member would either raise on construction or (worse)
    be dropped from a family count by a `try/except`. Check that the members
    named in the registry's own tag vocabulary all resolve.
    """
    # The tags the series registry uses, as recorded in the module docstring's
    # worked examples plus the ones the censuses rely on.
    expected_present = {
        "bls_cpi",
        "bea_pce",
        "bls_ppi",
        "cleveland_fed",
        "dallas_fed",
        "market_breakeven",
        "survey_expectations",
        "bls_employment_situation",
        "bls_jolts",
        "dol_claims",
        "bea_nipa",
        "cbo_potential",
        "fed_sloos",
        "treasury_official",
        "fed_h41",
        "fed_ny_acm",
        "treasury_auctions",
        "market_credit_spreads",
        "market_equity_vol",
        "market_fx",
        "market_commodity",
        "ny_fed_hlw",
    }
    have = {m.value for m in EvidenceSourceFamily}
    missing = expected_present - have
    assert not missing, f"family vocabulary lost members the censuses use: {missing}"
