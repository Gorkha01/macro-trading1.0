"""Smoke verification for models/evidence_family.py (Module 13 vocabulary).

This module is a pure enum — no arithmetic, no model logic. The only defect class
is a wrong or duplicated member value, so the check is: documented members carry
their documented string values, and all values are unique (a duplicated value would
silently merge two independent upstream production processes into one "family").
"""

from __future__ import annotations

from macro_engine.models.evidence_family import EvidenceSourceFamily


def test_documented_members_and_values():
    assert EvidenceSourceFamily.BLS_CPI.value == "bls_cpi"
    assert EvidenceSourceFamily.BLS_PPI.value == "bls_ppi"
    assert EvidenceSourceFamily.BEA_PCE.value == "bea_pce"
    assert EvidenceSourceFamily.BEA_NIPA.value == "bea_nipa"
    assert EvidenceSourceFamily.FED_H41.value == "fed_h41"
    assert EvidenceSourceFamily.MANUAL_ASSESSMENT.value == "manual_assessment"


def test_cpi_and_ppi_are_distinct_families():
    # The whole point of the enum: separate surveys => separate families.
    assert EvidenceSourceFamily.BLS_CPI != EvidenceSourceFamily.BLS_PPI


def test_all_values_unique():
    values = [m.value for m in EvidenceSourceFamily]
    assert len(values) == len(set(values))
