"""Hand-computed verification suite for the general convergence classifier.

This is the D-051 cross-check twin of the scorecard suite: `classify_convergence`
shared the identical `opposed = up>0 and down>0` dead-branch defect (F-SC-001),
so the same narrow-fix (opposed = up>=2 and down>=2) must make MEDIUM reachable
here too. Every expected value is derived independently of the implementation.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from macro_engine.models.contracts import ModelResult, utc_now
from macro_engine.models.convergence import classify_convergence
from macro_engine.models.evidence_family import EvidenceSourceFamily as F

# Four distinct families to draw signals from.
FAM = [
    F.CBO_POTENTIAL,
    F.BEA_PCE,
    F.FED_SLOOS,
    F.FED_H41,
    F.BLS_CPI,
]


def _signal(direction: int, family: EvidenceSourceFamily) -> ModelResult:
    return ModelResult(
        model_name="sig",
        country="us",
        as_of=utc_now(),
        # direction is derived from value sign by _direction(); use ±1 values.
        value=direction,
        confidence=0.5,
        interpretation="signal",
        context="ctx",
        inputs_used=["x"],
        source_family=family,
    )


def _classify(directions: list[int], families: list[EvidenceSourceFamily]):
    assert len(directions) == len(families)
    return classify_convergence(
        __import__("macro_engine.models.convergence", fromlist=["ConvergenceInputs"]).ConvergenceInputs(
            signals=[_signal(d, f) for d, f in zip(directions, families, strict=True)]
        )
    )


# ---------------------------------------------------------------------------
# Config bridging + CONFLICTED as a genuine standoff (narrow-fix).
# ---------------------------------------------------------------------------
def test_config_bridging_convergence_gates():
    from macro_engine.config import get_settings

    s = get_settings().convergence
    assert s.high_dissent_ceiling == 0
    assert s.medium_dissent_ceiling == 1
    assert s.high_family_floor == 3
    assert s.medium_family_floor == 2


def test_2v2_split_is_conflicted():
    res = _classify([1, 1, -1, -1], [FAM[0], FAM[1], FAM[2], FAM[3]])
    assert res.value["classification"] == "CONFLICTED"
    assert res.value["agreement_fraction"] == pytest.approx(0.5)


def test_3v1_split_is_medium_after_narrow_fix():
    # 3 tighten (+1), 1 ease (-1), 3 distinct families. Under the OLD gate this
    # was CONFLICTED (any dissenter). After the narrow-fix it is MEDIUM: a clear
    # majority with a single dissenter, exactly what MEDIUM is reserved for.
    res = _classify([1, 1, -1, 1], [FAM[0], FAM[1], FAM[2], FAM[0]])
    assert res.value["classification"] == "MEDIUM"
    assert res.value["dissenting_signals"] == 1
    assert res.value["independent_families"] == 3


def test_unanimous_high_with_three_families():
    res = _classify([1, 1, 1, 1], [FAM[0], FAM[1], FAM[2], FAM[0]])
    assert res.value["classification"] == "HIGH"
    assert res.value["dissenting_signals"] == 0
    assert res.value["independent_families"] == 3


def test_one_directional_signal_is_low_not_conflicted():
    # n=1, a single +1. Not opposed (only one side), dissent 0, 1 family -> LOW.
    res = _classify([1], [FAM[0]])
    assert res.value["classification"] == "LOW"
    assert res.value["independent_families"] == 1
    assert res.value["non_neutral_signals"] == 1


def test_all_neutral_is_no_signal():
    res = _classify([0, 0, 0, 0], [FAM[0], FAM[1], FAM[2], FAM[3]])
    assert res.value["classification"] == "NO_SIGNAL"
    assert res.value["non_neutral_signals"] == 0


def test_medium_requires_two_families_floor():
    # 3 agree +1, 1 dissenter -1, but all the same family -> not opposed, dissent 1,
    # families 1 < medium floor 2 -> LOW (same family-floor behavior as scorecard).
    res = _classify([1, 1, -1, 1], [FAM[0], FAM[0], FAM[0], FAM[0]])
    assert res.value["classification"] == "LOW"
    assert res.value["independent_families"] == 1


def test_confidence_tracks_measured_family_count():
    # compute_confidence: base 0.70 - 0.20 heuristic + min(nfam*0.05, 0.25).
    # 2-vs-2 CONFLICTED with 4 distinct families -> 0.70 - 0.20 + 0.20 = 0.70.
    res = _classify([1, 1, -1, -1], [FAM[0], FAM[1], FAM[2], FAM[3]])
    assert res.confidence == pytest.approx(0.70)
    # MEDIUM with 3 distinct families -> 0.70 - 0.20 + 0.15 = 0.65
    med = _classify([1, 1, -1, 1], [FAM[0], FAM[1], FAM[2], FAM[0]])
    assert med.confidence == pytest.approx(0.65)
    # LOW with 1 family -> 0.70 - 0.20 + 0.05 = 0.55
    low = _classify([1], [FAM[0]])
    assert low.confidence == pytest.approx(0.55)


def test_order_independence():
    # Defect 2: the verdict must not depend on list order. A 3-vs-1 split in two
    # orders must give the same MEDIUM verdict.
    a = _classify([1, 1, -1, 1], [FAM[0], FAM[1], FAM[2], FAM[0]])
    b = _classify([1, -1, 1, 1], [FAM[2], FAM[0], FAM[0], FAM[1]])
    assert a.value["classification"] == b.value["classification"] == "MEDIUM"


def test_census_counts_directional_only():
    # 1 directional +1 and 3 NEUTRAL signals from 3 NEW families. The neutral
    # families must NOT pad the count (D-050/Defect 7). independent_families == 1.
    signals = [_signal(1, FAM[0])] + [_signal(0, f) for f in [FAM[1], FAM[2], FAM[3]]]
    from macro_engine.models.convergence import ConvergenceInputs

    res = classify_convergence(ConvergenceInputs(signals=signals))
    assert res.value["independent_families"] == 1
    assert res.value["non_neutral_signals"] == 1
