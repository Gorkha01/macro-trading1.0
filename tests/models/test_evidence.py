"""Hand-computed verification tests for models/evidence.py (Module 13).

Two functions:
  tag_evidence_source(result, family) -> RESULT COPY carrying provenance; re-tag
      with a DIFFERENT family is a refusal, same family is idempotent, the
      data_quality_flags_present flag is recorded WITHOUT changing confidence.
  count_independent_families(results) -> ModelResult whose value is an
      EvidenceTally counting DISTINCT families (duplicates collapsed), untagged
      reported separately, all-one-family warned.

Confidence is compute_confidence(is_heuristic_not_calibrated=True,
source_independence_count=0) = base 0.70 - heuristic 0.20 = 0.50 (both Module-13
thresholds are uncalibrated_illustrative). Verified by hand.
"""

from __future__ import annotations

import pytest

from macro_engine.models.contracts import ModelResult, utc_now
from macro_engine.models.evidence import (
    count_independent_families,
    tag_evidence_source,
)
from macro_engine.models.evidence_family import EvidenceSourceFamily


def _res(
    name: str = "m",
    val: float = 1.0,
    family: EvidenceSourceFamily | None = None,
    dq: bool = False,
    confidence: float = 0.7,
) -> ModelResult:
    return ModelResult(
        model_name=name,
        country="us",
        as_of=utc_now(),
        value=val,
        confidence=confidence,
        interpretation="x",
        context="x",
        inputs_used=["x"],
        source_family=family,
        data_quality_flags_present=dq,
    )


def test_tag_is_copy_not_mutation() -> None:
    r = _res()
    tagged = tag_evidence_source(r, EvidenceSourceFamily.BLS_CPI)
    assert r.source_family is None
    assert tagged.source_family == EvidenceSourceFamily.BLS_CPI
    assert tagged is not r
    assert any("bls_cpi" in w for w in tagged.warnings)


def test_retag_different_family_refused() -> None:
    r = _res(family=EvidenceSourceFamily.BLS_CPI)
    with pytest.raises(ValueError):
        tag_evidence_source(r, EvidenceSourceFamily.BEA_PCE)


def test_retag_same_family_idempotent() -> None:
    r = _res(family=EvidenceSourceFamily.BLS_CPI)
    tagged = tag_evidence_source(r, EvidenceSourceFamily.BLS_CPI)
    assert tagged.source_family == EvidenceSourceFamily.BLS_CPI
    # Note is not duplicated.
    assert sum("bls_cpi" in w for w in tagged.warnings) == 1


def test_data_quality_flag_recorded_not_confidence_changed() -> None:
    r = _res(confidence=0.9)
    tagged = tag_evidence_source(r, EvidenceSourceFamily.BLS_CPI, data_quality_flags_present=True)
    assert tagged.data_quality_flags_present is True
    assert r.data_quality_flags_present is False  # original untouched
    assert tagged.confidence == 0.9  # confidence VALUE never rewritten here


def test_count_single_family_merges_and_warns() -> None:
    results = [_res(family=EvidenceSourceFamily.BLS_CPI) for _ in range(5)]
    res = count_independent_families(results)
    t = res.value_dict()
    assert t["distinct_families"] == 1
    assert t["families"] == ["bls_cpi"]
    assert t["tagged"] == 5
    assert t["untagged"] == 0
    assert t["duplicate_results"] == 4
    assert any("ALL 5" in w for w in res.warnings)  # all-one-family warning
    assert res.confidence == 0.50


def test_count_mixed_families() -> None:
    results = [
        _res(family=EvidenceSourceFamily.BLS_CPI),
        _res(family=EvidenceSourceFamily.BLS_CPI),
        _res(family=EvidenceSourceFamily.BEA_PCE),
        _res(family=EvidenceSourceFamily.MARKET_BREAKEVEN),
    ]
    res = count_independent_families(results)
    t = res.value_dict()
    assert t["distinct_families"] == 3
    assert t["families"] == ["bea_pce", "bls_cpi", "market_breakeven"]
    assert t["duplicate_results"] == 1
    assert t["tagged"] == 4
    assert t["untagged"] == 0
    assert not any("ALL" in w for w in res.warnings)
    assert res.confidence == 0.50


def test_count_untagged_reported_separately() -> None:
    results = [
        _res(family=EvidenceSourceFamily.BLS_CPI),
        _res(),  # untagged
        _res(),  # untagged
    ]
    res = count_independent_families(results)
    t = res.value_dict()
    assert t["distinct_families"] == 1
    assert t["untagged"] == 2
    assert t["tagged"] == 1
    assert any("no source family" in w for w in res.warnings)


def test_count_empty_no_results_warning() -> None:
    res = count_independent_families([])
    t = res.value_dict()
    assert t["distinct_families"] == 0
    assert any("NO RESULTS SUPPLIED" in w for w in res.warnings)
    assert res.confidence == 0.50
