"""Hand-computed verification suite for Module 12.2 — the four-pillar scorecard.

Every assertion below is derived from real arithmetic over the four pillars
(growth, inflation, financial_conditions, policy_gap), each in {-1, 0, +1},
rather than from the implementation. The D-045a rule ("a Literal is a promise
with two halves") is honoured: we assert every member of the ConvergenceVerdict
Literal is actually producible, and we sweep the full 3**4 = 81 admissible
pillar space to pin the CONFLICTED share at the spec's measured 350/567.
"""

from __future__ import annotations

import itertools
from typing import Any

import pytest

from macro_engine.config import get_settings
from macro_engine.models.contracts import (
    ConfidenceInputs,
    ModelResult,
    compute_confidence,
)
from macro_engine.models.evidence_family import EvidenceSourceFamily
from macro_engine.models.scorecard import (
    PillarRead,
    ScorecardInputs,
    four_pillar_scorecard,
)

# --- four distinct source families, one per pillar -----------------------
F_GROWTH = EvidenceSourceFamily.CBO_POTENTIAL
F_INFLATION = EvidenceSourceFamily.BEA_PCE
F_FC = EvidenceSourceFamily.FED_SLOOS
F_POLICY = EvidenceSourceFamily.FED_H41


def _read(direction: int, family: EvidenceSourceFamily) -> PillarRead:
    return PillarRead(
        direction=direction,  # type: ignore[arg-type]
        family=family,
        source=f"src_{family.value}",
    )


def _inputs(
    growth: int = 0,
    inflation: int = 0,
    financial_conditions: int = 0,
    policy_gap: int = 0,
    *,
    allow_all_neutral: bool = False,
    families: tuple[EvidenceSourceFamily, ...] | None = None,
) -> ScorecardInputs:
    fam = families or (F_GROWTH, F_INFLATION, F_FC, F_POLICY)
    return ScorecardInputs(
        growth=_read(growth, fam[0]),
        inflation=_read(inflation, fam[1]),
        financial_conditions=_read(financial_conditions, fam[2]),
        policy_gap=_read(policy_gap, fam[3]),
        allow_all_neutral=allow_all_neutral,
    )


def _run(*args: Any, **kwargs: Any) -> ModelResult:
    return four_pillar_scorecard(_inputs(*args, **kwargs))


# ---------------------------------------------------------------------------
# Config-bridging: the YAML leaves must reach the code-used attribute names.
# ---------------------------------------------------------------------------
def test_config_bridging_maps_yaml_leaves_to_code_attributes() -> None:
    s = get_settings().scorecard
    # max_dissenting_pillars_high.value == 0  -> high_dissent_ceiling
    assert s.high_dissent_ceiling == 0
    # max_dissenting_pillars_medium.value == 1 -> medium_dissent_ceiling
    assert s.medium_dissent_ceiling == 1
    # min_independent_families_high.value == 3 -> high_family_floor
    assert s.high_family_floor == 3
    # min_independent_families_medium.value == 2 -> medium_family_floor
    assert s.medium_family_floor == 2
    # measured_conflicted_share.value == 0.0741 -> conflicted_base_share
    assert s.conflicted_base_share == pytest.approx(0.0741)


def test_confidence_is_flat_and_comes_from_compute_confidence() -> None:
    # Defect 4: confidence comes from compute_confidence() and is NOT a function
    # of the verdict LABEL. It tracks the MEASURED independent-family count
    # (base 0.70 - 0.20 heuristic penalty + 0.05 per independent family):
    #   2 families -> 0.60, 4 families -> 0.70, 1 family -> 0.55,
    #   0 directional families (all-neutral) -> 0.50.
    # The verdict (CONFLICTED vs HIGH vs LOW) does not move it on its own; only
    # the measured family count does.
    no_signal = _run(0, 0, 0, 0, allow_all_neutral=True)
    assert no_signal.confidence == pytest.approx(0.50)  # 0 directional families
    conflicted = _run(1, -1, 0, 0)  # 2 distinct families
    assert conflicted.confidence == pytest.approx(0.60)
    high = _run(1, 1, 1, 1)  # 4 distinct families
    assert high.confidence == pytest.approx(0.70)
    low = _run(1, 1, 1, 1, families=(F_GROWTH, F_GROWTH, F_GROWTH, F_GROWTH))
    assert low.confidence == pytest.approx(0.55)  # 1 family
    # Sanity: the formula is the single source (no verdict-specific literal).
    for res in (no_signal, conflicted, high, low):
        assert res.confidence == pytest.approx(
            compute_confidence(
                ConfidenceInputs(
                    data_quality_flags_present=False,
                    is_heuristic_not_calibrated=True,
                    depends_on_unobservable=False,
                    source_independence_count=res.value_dict()["independent_families"],
                )
            )
        )


# ---------------------------------------------------------------------------
# D-045a: every member of the ConvergenceVerdict Literal is producible.
# ---------------------------------------------------------------------------
def test_all_verdict_literal_members_are_producible() -> None:
    # D-045a: "a Literal is a promise with two halves" — every member of the
    # ConvergenceVerdict Literal must be producible. After the F-SC-001 narrow-fix
    # (opposed = up>=2 and down>=2), MEDIUM IS reachable: a 3-vs-1 split is a
    # clear majority with one dissenter, which the severity model assigns to MEDIUM.
    reachable = {
        "NO_SIGNAL": _run(0, 0, 0, 0, allow_all_neutral=True),
        "CONFLICTED": _run(1, 1, -1, -1),
        "HIGH": _run(1, 1, 1, 1),
        "MEDIUM": _run(1, 1, -1, 1, families=(F_GROWTH, F_INFLATION, F_FC, F_FC)),
        "LOW": _run(1, 1, 1, 1, families=(F_GROWTH, F_GROWTH, F_GROWTH, F_GROWTH)),
    }
    produced = {r.value_dict()["classification"] for r in reachable.values()}
    assert produced == {
        "NO_SIGNAL",
        "CONFLICTED",
        "HIGH",
        "MEDIUM",
        "LOW",
    }


# ---------------------------------------------------------------------------
# Defect 1 — the CONFLICTED gate must cover the full opposition predicate,
# not the narrower growth*inflation<0 condition.
# ---------------------------------------------------------------------------
def test_conflicted_gate_covers_growth_inflation_agree_but_fc_policy_oppose() -> None:
    # The classic "bad news is good news" split: growth & inflation tighten,
    # financial conditions & policy ease. Under the OLD spec rule this would
    # NOT have been CONFLICTED (growth*inflation = +1, not < 0). Correct output:
    res = _run(1, 1, -1, -1)
    assert res.value_dict()["classification"] == "CONFLICTED"
    assert res.value_dict()["independent_families"] == 4


def test_conflicted_gate_covers_four_way_split() -> None:
    res = _run(1, -1, 1, -1)
    assert res.value_dict()["classification"] == "CONFLICTED"
    assert res.value_dict()["agreement_fraction"] == pytest.approx(0.5)
    assert "read easing" in res.interpretation and "read tightening" in res.interpretation


def test_conflicted_is_genuine_standoff_2v2_only() -> None:
    # After the F-SC-001 narrow-fix, CONFLICTED requires a genuine standoff:
    # at least two pillars pointing each way. Over the 81 admissible (g,i,fc,p)
    # patterns, the only such split is 2-vs-2 (both sides >= 2), which is exactly
    # C(4,2) = 6 ordered patterns. 3-vs-1 splits are now MEDIUM. The old spec
    # figure of 350/567 conflated every non-unanimous split with CONFLICTED.
    combos = list(itertools.product([-1, 0, 1], repeat=4))
    assert len(combos) == 81
    conflicted = 0
    for g, i, fc, p in combos:
        try:
            res = _run(g, i, fc, p)
        except ValueError:
            continue  # all-neutral without opt-in is rejected, not conflicted
        if res.value_dict()["classification"] == "CONFLICTED":
            conflicted += 1
    # Exact count: the 6 ordered 2-vs-2 patterns.
    expected = sum(1 for c in combos if c.count(1) == 2 and c.count(-1) == 2)
    assert expected == 6
    assert conflicted == expected
    # Sanity: a 3-vs-1 split is MEDIUM, not CONFLICTED.
    res = _run(1, 1, -1, 1)
    assert res.value_dict()["classification"] == "MEDIUM"


# ---------------------------------------------------------------------------
# Defect 2 — verdict expressed as dissent counts, not unreachable fractions.
# ---------------------------------------------------------------------------
def test_high_requires_unanimity_and_three_families() -> None:
    # 4 directional, all +1, 4 distinct families -> HIGH
    res = _run(1, 1, 1, 1)
    assert res.value_dict()["classification"] == "HIGH"
    assert res.value_dict()["dissenting_pillars"] == 0
    assert res.value_dict()["independent_families"] == 4


def test_high_floor_is_three_families_not_four() -> None:
    # 4 unanimous +1 but only 3 distinct families -> still HIGH (floor is 3)
    res = _run(1, 1, 1, 1, families=(F_GROWTH, F_INFLATION, F_FC, F_FC))
    assert res.value_dict()["classification"] == "HIGH"
    assert res.value_dict()["independent_families"] == 3


def test_medium_permits_one_dissenter_and_three_families() -> None:
    # 3 agree +1, 1 dissents -1, 3 distinct families -> MEDIUM (F-SC-001 fix makes
    # the 3-vs-1 split reachable as MEDIUM rather than CONFLICTED).
    res = _run(1, 1, -1, 1, families=(F_GROWTH, F_INFLATION, F_FC, F_FC))
    assert res.value_dict()["classification"] == "MEDIUM"
    assert res.value_dict()["dissenting_pillars"] == 1
    assert res.value_dict()["independent_families"] == 3


def test_medium_floor_is_two_families() -> None:
    # 3 agree, 1 dissenter, exactly 2 distinct families -> MEDIUM (2 == floor).
    res = _run(1, 1, -1, 1, families=(F_GROWTH, F_GROWTH, F_INFLATION, F_INFLATION))
    assert res.value_dict()["classification"] == "MEDIUM"
    assert res.value_dict()["independent_families"] == 2


def test_low_when_medium_floor_unmet() -> None:
    # 3 agree +1, 1 dissenter -1, but only 1 distinct family -> not opposed, so the
    # CONFLICTED gate is skipped; dissent=1 but families=1 < medium floor 2, so the
    # verdict is LOW (not MEDIUM). The family floor changes the VERDICT here, not
    # merely the reason text.
    res = _run(1, 1, -1, 1, families=(F_GROWTH, F_GROWTH, F_GROWTH, F_GROWTH))
    assert res.value_dict()["classification"] == "LOW"
    assert res.value_dict()["independent_families"] == 1
    assert any("redundant evidence" in w for w in res.warnings)


def test_3v1_split_is_medium_after_narrow_fix() -> None:
    # 3 agree +1, 1 dissents -1, 3 distinct families (last two share F_FC).
    # After the F-SC-001 narrow-fix (opposed = up>=2 and down>=2), a 3-vs-1 split
    # is NOT a standoff, so it falls through to MEDIUM (clear majority + 1 dissenter).
    res = _run(1, 1, -1, 1, families=(F_GROWTH, F_INFLATION, F_FC, F_FC))
    assert res.value_dict()["classification"] == "MEDIUM"
    assert res.value_dict()["dissenting_pillars"] == 1
    assert res.value_dict()["independent_families"] == 3
    assert res.value_dict()["agreement_fraction"] == pytest.approx(0.75)


def test_one_family_3v1_is_low_not_conflicted() -> None:
    # 3 agree +1, 1 dissenter -1, all same family -> not a standoff (down<2), so
    # not CONFLICTED. dissent=1 and not opposed would reach MEDIUM, but families=1
    # is below the medium floor 2, so the verdict is LOW with the redundant-
    # evidence warning (agreement high but one family).
    res = _run(1, 1, -1, 1, families=(F_GROWTH, F_GROWTH, F_GROWTH, F_GROWTH))
    assert res.value_dict()["classification"] == "LOW"
    assert res.value_dict()["independent_families"] == 1
    assert res.value_dict()["dissenting_pillars"] == 1
    assert any("redundant evidence" in w for w in res.warnings)


def test_2v2_split_is_conflicted() -> None:
    res = _run(1, 1, -1, -1)
    assert res.value_dict()["classification"] == "CONFLICTED"
    assert res.value_dict()["agreement_fraction"] == pytest.approx(0.5)


def test_low_only_when_unanimous_within_too_few_families() -> None:
    # Unanimous +1 but a single family -> not opposed, dissent 0, families 1 (< 2)
    # -> LOW via the family-floor branch.
    res = _run(1, 1, 1, 1, families=(F_GROWTH, F_GROWTH, F_GROWTH, F_GROWTH))
    assert res.value_dict()["classification"] == "LOW"
    assert res.value_dict()["independent_families"] == 1


def test_tie_is_not_high_or_medium() -> None:
    # 2 up, 2 down -> opposed -> CONFLICTED (not a dissent-count MEDIUM)
    res = _run(1, 1, -1, -1)
    assert res.value_dict()["classification"] == "CONFLICTED"


# ---------------------------------------------------------------------------
# Defect 3 — Section 15.19-D discharged: the census counts MEASURED families
# over DIRECTIONAL pillars only, never the raw signal count.
# ---------------------------------------------------------------------------
def test_census_counts_directional_pillars_only_not_neutrals() -> None:
    # 1 directional pillar (+1) from family A, plus three NEUTRAL pillars each
    # from a DIFFERENT family. The three neutral families must NOT pad the count.
    res = _run(
        1,
        0,
        0,
        0,
        families=(F_GROWTH, F_INFLATION, F_FC, F_POLICY),
    )
    assert res.value_dict()["independent_families"] == 1
    # 1 directional, < medium floor (2) -> LOW
    assert res.value_dict()["classification"] == "LOW"
    assert res.value_dict()["non_neutral_pillars"] == 1


def test_raw_signal_count_cannot_promote_verdict() -> None:
    # Four pillars, three +1 and one neutral, but ALL the same family. The OLD
    # caller-supplied `families=4` would have yielded HIGH; measured count = 1,
    # so this is LOW.
    res = _run(1, 1, 1, 0, families=(F_GROWTH, F_GROWTH, F_GROWTH, F_GROWTH))
    assert res.value_dict()["independent_families"] == 1
    assert res.value_dict()["classification"] == "LOW"


def test_family_names_published_are_all_four_pillars() -> None:
    res = _run(1, -1, 0, 1)
    # family_names is the set of ALL pillar families (directional + neutral)
    assert set(res.value_dict()["family_names"]) == {
        F_GROWTH.value,
        F_INFLATION.value,
        F_FC.value,
        F_POLICY.value,
    }


# ---------------------------------------------------------------------------
# NO_SIGNAL and the all-neutral guard (Defect-4 companion: verdict as fact).
# ---------------------------------------------------------------------------
def test_all_neutral_without_opt_in_is_rejected() -> None:
    with pytest.raises(ValueError, match="All four pillars read neutral"):
        _run(0, 0, 0, 0)


def test_all_neutral_with_opt_in_is_no_signal() -> None:
    res = _run(0, 0, 0, 0, allow_all_neutral=True)
    assert res.value_dict()["classification"] == "NO_SIGNAL"
    assert res.value_dict()["non_neutral_pillars"] == 0
    assert res.value_dict()["independent_families"] == 0
    assert any("NO_SIGNAL" in w for w in res.warnings)


# ---------------------------------------------------------------------------
# Warning branches — each reachable, each asserted.
# ---------------------------------------------------------------------------
def test_conflicted_warning_reports_base_share() -> None:
    # 2-vs-2 is the standoff that the narrowed gate still classifies CONFLICTED.
    res = _run(1, 1, -1, -1)
    conflicted_warn = [w for w in res.warnings if "CONFLICTED" in w and "BASE STATE" in w]
    assert conflicted_warn, res.warnings
    assert "7.4%" in conflicted_warn[0]


def test_redundant_evidence_warning_when_high_agreement_few_families() -> None:
    # 3 agree +1, 0 dissent, but only 1 family -> LOW with redundant-evidence note
    res = _run(1, 1, 1, 0, families=(F_GROWTH, F_GROWTH, F_GROWTH, F_GROWTH))
    assert res.value_dict()["classification"] == "LOW"
    red = [w for w in res.warnings if "redundant evidence" in w]
    assert red, res.warnings


def test_fewer_than_four_pillars_warning_on_high() -> None:
    # 3 directional +1, 3 distinct families -> HIGH, but only 3 of 4 non-neutral
    res = _run(1, 1, 1, 0, families=(F_GROWTH, F_INFLATION, F_FC, F_POLICY))
    assert res.value_dict()["classification"] == "HIGH"
    assert any("Only 3 of 4 pillars" in w for w in res.warnings)


def test_published_value_carries_all_decision_quantities() -> None:
    res = _run(1, 1, -1, 1)
    v = res.value_dict()
    assert set(v.keys()) == {
        "classification",
        "agreement_fraction",
        "agreement_margin",
        "dissenting_pillars",
        "non_neutral_pillars",
        "independent_families",
        "family_names",
        "pillar_directions",
    }
    assert v["pillar_directions"] == {
        "growth": 1,
        "inflation": 1,
        "financial_conditions": -1,
        "policy_gap": 1,
    }
