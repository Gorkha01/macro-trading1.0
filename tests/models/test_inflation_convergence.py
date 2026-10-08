"""Hand-computed tests for Module 5.3 — inflation sub-measure convergence.

Every expected number below is derived from the CONFIG LEAVES, not from running
the code:

    inflation.convergence.high                       = 0.8
    inflation.convergence.medium                     = 0.6
    inflation.convergence.deep_conflict_share        = 0.25
    inflation.convergence.min_independent_families_per_band
                                                     high=2, medium=2, low=1
    inflation.convergence.base_state_warning_threshold = 0.75
    inflation.convergence.measured_base_rates.three_measure_high = 0.866
    inflation.convergence.measured_base_rates.six_measure_high   = 0.895

and from compute_confidence():

    base 0.70 - heuristic 0.20 + min(families * 0.05, 0.25)
    3 families -> 0.65   2 families -> 0.60   1 family -> 0.55   0 -> 0.50

Family map (module's own ``_INPUT_FAMILIES``):

    headline_cpi, core_cpi, median_cpi, sticky_price_cpi -> BLS_CPI
    core_pce                                             -> BEA_PCE
    trimmed_mean                                         -> DALLAS_FED
"""

from __future__ import annotations

from typing import Any

import pytest

from macro_engine.config import get_settings
from macro_engine.models.contracts import ModelResult
from macro_engine.models.inflation_convergence import (
    CONVERGENCE_CLASSES,
    InflationConvergenceInputs,
    inflation_convergence_classifier,
)

# The three required Phase-1 measures; everything else is optional.
REQUIRED = {"headline_cpi_direction": 1, "core_cpi_direction": 1, "core_pce_direction": 1}


def run(**overrides: Any) -> ModelResult:
    """Classify with the three required measures defaulting to +1."""
    kwargs: dict[str, Any] = dict(REQUIRED)
    kwargs.update(overrides)
    return inflation_convergence_classifier(InflationConvergenceInputs(**kwargs))


# ---------------------------------------------------------------------------
# The vocabulary's two halves (D-045a): every declared class is producible
# ---------------------------------------------------------------------------
def test_all_convergence_classes_are_producible() -> None:
    """A Literal member no input can reach is a promise the module cannot keep."""
    produced = set()
    cases = {
        # 6/6 unanimous -> frac 1.0 >= 0.8
        "HIGH": {
            "median_cpi_direction": 1,
            "trimmed_mean_direction": 1,
            "sticky_price_cpi_direction": 1,
        },
        # 4 up, 1 down, 1 flat: losing=1 < 0.25*6=1.5, frac 4/6=0.667 in [0.6,0.8)
        "MEDIUM": {
            "median_cpi_direction": 1,
            "trimmed_mean_direction": -1,
            "sticky_price_cpi_direction": 0,
        },
        # 2 up, 2 flat of 4: losing=0, frac 2/4=0.5 < 0.6
        "LOW": {"core_pce_direction": 0, "median_cpi_direction": 0},
        # headline * core < 0 -> the specification's pair gate
        "CONFLICTED": {"core_cpi_direction": -1},
    }
    for expected, overrides in cases.items():
        got = run(**overrides).value_dict()["classification"]
        assert got == expected, f"{expected} not producible: got {got}"
        produced.add(got)
    assert produced == set(CONVERGENCE_CLASSES)


# ---------------------------------------------------------------------------
# F-IC-001 — a CONFLICTED reading must not be described as "band-ceiled"
# ---------------------------------------------------------------------------
def test_conflicted_does_not_emit_the_band_ceiling_warning() -> None:
    """CONFLICTED is not a band, so no band-ceiling claim applies to it.

    ``bands_available`` only ever contains HIGH/MEDIUM/LOW, so ``classification
    in bands`` is False for every CONFLICTED read and the `elif bands` branch
    fires with text asserting "the agreement fraction satisfied CONFLICTED" and
    "supports no better than HIGH" — both false. CONFLICTED was reached by the
    conflict gates, not by any agreement fraction, and "no better than HIGH" is
    the strongest band, so it describes no ceiling at all.
    """
    res = run(core_cpi_direction=-1)
    assert res.value_dict()["classification"] == "CONFLICTED"
    ceiling = [w for w in res.warnings if "BAND CEILED" in w or "NO BAND SUPPORTED" in w]
    assert ceiling == [], f"CONFLICTED emitted a band- ceiling claim: {ceiling}"


def test_one_directional_measure_yields_one_family_and_the_low_band() -> None:
    """headline=0 and core=0 are flat; core_pce=1 is the only directional read.

    One directional family -> min_families(low)=1 is met, high/medium=2 are not,
    so bands == ['LOW'].
    """
    res = run(headline_cpi_direction=0, core_cpi_direction=0, core_pce_direction=1)
    assert res.value_dict()["classification"] == "LOW"
    assert res.value_dict()["independent_families"] == 1
    assert res.value_dict()["bands_available"] == ["LOW"]


def test_the_ceiling_warning_is_correct_for_a_real_ceiling() -> None:
    """When a band read genuinely outruns its evidence, the message is right.

    headline=1, core=1 (both BLS_CPI) and core_pce flat -> one directional
    family, so bands == ['LOW'] while frac 2/3 = 0.667 earns MEDIUM.
    """
    res = run(core_pce_direction=0)
    assert res.value_dict()["classification"] == "MEDIUM"
    assert res.value_dict()["independent_families"] == 1
    assert res.value_dict()["bands_available"] == ["LOW"]
    assert any("BAND CEILED" in w and "MEDIUM" in w for w in res.warnings)


# ---------------------------------------------------------------------------
# F-IC-002 — flat readings must not pad the independent-family census
# ---------------------------------------------------------------------------
def test_flat_readings_do_not_pad_the_family_census() -> None:
    """A flat measure has no direction and cannot back a directional verdict.

    Section 15.19-D / D-050, already applied in scorecard.py and convergence.py:
    the census runs over the DIRECTIONAL subset. Here headline and core are both
    flat, so the BLS_CPI family contributes no directional evidence; the only
    directional measure is core_pce (BEA_PCE). The family count must be 1, not 2.
    """
    res = run(headline_cpi_direction=0, core_cpi_direction=0, core_pce_direction=1)
    assert res.value_dict()["flat"] == 2
    assert res.value_dict()["independent_families"] == 1, (
        "two flat BLS readings padded the census to "
        f"{res.value_dict()['independent_families']} families"
    )
    assert res.value_dict()["family_names"] == ["bea_pce"]


def test_flat_readings_do_not_earn_a_higher_confidence() -> None:
    """The padded count buys a confidence credit the evidence did not earn.

    One directional family -> 0.70 - 0.20 + 1*0.05 = 0.55. With the padding the
    count is 2 -> 0.60, i.e. a flat reading buys a 0.05 credit.
    """
    res = run(headline_cpi_direction=0, core_cpi_direction=0, core_pce_direction=1)
    assert res.confidence == pytest.approx(0.55)


def test_flat_readings_do_not_open_the_high_band() -> None:
    """min_families(HIGH) == 2, so a padded count of 2 falsely opens HIGH."""
    res = run(headline_cpi_direction=0, core_cpi_direction=0, core_pce_direction=1)
    assert res.value_dict()["bands_available"] == ["LOW"]


def test_all_flat_month_has_no_family_and_no_band() -> None:
    """Nothing moved -> zero directional measures -> zero families."""
    res = run(headline_cpi_direction=0, core_cpi_direction=0, core_pce_direction=0)
    assert res.value_dict()["classification"] == "LOW"
    assert res.value_dict()["flat"] == 3
    assert res.value_dict()["independent_families"] == 0
    assert res.value_dict()["bands_available"] == []
    assert any("NO BAND SUPPORTED" in w for w in res.warnings)


def test_the_flat_warning_names_the_exclusion() -> None:
    """The exclusion is disclosed, not silent."""
    res = run(headline_cpi_direction=0, core_cpi_direction=0, core_pce_direction=1)
    joined = " ".join(res.warnings)
    assert "flat" in joined.lower()
    assert "EXCLUDED" in joined


# ---------------------------------------------------------------------------
# Section 15.19-D's own test — redundancy must not outrank independence
# ---------------------------------------------------------------------------
def test_five_redundant_measures_do_not_outscore_two_independent_ones() -> None:
    """Five measures from two families must not beat four from three.

    A: headline, core, median, sticky (all BLS_CPI) + core_pce (BEA_PCE)
       -> 5 measures, 2 families -> 0.70 - 0.20 + 0.10 = 0.60
    B: headline, core (BLS_CPI) + core_pce (BEA_PCE) + trimmed_mean (DALLAS_FED)
       -> 4 measures, 3 families -> 0.70 - 0.20 + 0.15 = 0.65
    headline/core/core_pce are required, so four measures is the floor for B.
    """
    a = run(median_cpi_direction=1, sticky_price_cpi_direction=1)
    b = run(trimmed_mean_direction=1)
    assert a.value_dict()["measures_used"] == 5
    assert b.value_dict()["measures_used"] == 4
    assert a.value_dict()["independent_families"] == 2
    assert b.value_dict()["independent_families"] == 3
    assert b.confidence > a.confidence, (
        f"redundant read scored {a.confidence} vs independent {b.confidence}"
    )


# ---------------------------------------------------------------------------
# The two conflict gates
# ---------------------------------------------------------------------------
def test_pair_gate_fires_on_headline_core_opposition() -> None:
    res = run(headline_cpi_direction=1, core_cpi_direction=-1, core_pce_direction=1)
    assert res.value_dict()["classification"] == "CONFLICTED"


def test_whole_set_gate_fires_when_headline_and_core_agree() -> None:
    """Correction 1: the pair gate alone would call this convergence.

    headline=+1, core=+1 agree, but median, trimmed and sticky are all -1:
    3 up, 3 down over 6 measures -> losing = 3 >= 0.25*6 = 1.5 -> CONFLICTED.
    """
    res = run(
        median_cpi_direction=-1,
        trimmed_mean_direction=-1,
        sticky_price_cpi_direction=-1,
    )
    assert res.value_dict()["classification"] == "CONFLICTED"
    assert res.value_dict()["agreeing"] == 3
    assert res.value_dict()["opposing"] == 3
    assert any("WHOLE-SET gate" in w for w in res.warnings)


def test_whole_set_gate_does_not_fire_on_a_single_dissenter() -> None:
    """5 up, 1 down over 6: losing = 1 < 1.5, so frac 5/6 = 0.833 -> HIGH."""
    res = run(
        median_cpi_direction=1,
        trimmed_mean_direction=1,
        sticky_price_cpi_direction=-1,
    )
    assert res.value_dict()["classification"] == "HIGH"
    assert res.value_dict()["frac_agreeing"] == pytest.approx(5 / 6)


def test_all_flat_is_not_conflict() -> None:
    """`losing` is 0 when nothing moves, and 0 >= 0.25*n is never true."""
    res = run(headline_cpi_direction=0, core_cpi_direction=0, core_pce_direction=0)
    assert res.value_dict()["classification"] == "LOW"


# ---------------------------------------------------------------------------
# The published arithmetic
# ---------------------------------------------------------------------------
def test_frac_agreeing_is_the_majority_share() -> None:
    res = run(median_cpi_direction=1, trimmed_mean_direction=-1, sticky_price_cpi_direction=0)
    # 4 up, 1 down, 1 flat over 6 measures
    assert res.value_dict()["agreeing"] == 4
    assert res.value_dict()["opposing"] == 1
    assert res.value_dict()["flat"] == 1
    assert res.value_dict()["measures_used"] == 6
    assert res.value_dict()["frac_agreeing"] == pytest.approx(4 / 6, abs=1e-6)


def test_majority_direction_recovers_the_sign() -> None:
    """A disinflation month: the majority is the DOWN side."""
    res = run(
        headline_cpi_direction=-1,
        core_cpi_direction=-1,
        core_pce_direction=-1,
        median_cpi_direction=-1,
        trimmed_mean_direction=-1,
        sticky_price_cpi_direction=-1,
    )
    assert res.value_dict()["classification"] == "HIGH"
    assert res.value_dict()["majority_direction"] == -1


def test_majority_direction_is_zero_when_no_side_holds_a_majority() -> None:
    res = run(headline_cpi_direction=1, core_cpi_direction=-1, core_pce_direction=0)
    assert res.value_dict()["majority_direction"] == 0


def test_attainable_fracs_are_the_multiples_of_one_over_n() -> None:
    res = run(median_cpi_direction=1, trimmed_mean_direction=1)
    assert res.value_dict()["attainable_fracs"] == [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]


def test_three_measure_attainable_fracs() -> None:
    res = run()
    assert res.value_dict()["measures_used"] == 3
    assert res.value_dict()["attainable_fracs"] == pytest.approx([0.0, 1 / 3, 2 / 3, 1.0])


# ---------------------------------------------------------------------------
# Disclosures
# ---------------------------------------------------------------------------
def test_thresholds_are_flagged_degenerate_below_five_measures() -> None:
    res = run()
    assert any("DEGENERATE" in w and "n=3" in w for w in res.warnings)


def test_no_degeneracy_warning_at_six_measures() -> None:
    res = run(median_cpi_direction=1, trimmed_mean_direction=1, sticky_price_cpi_direction=1)
    assert not any("DEGENERATE" in w for w in res.warnings)


def test_high_is_disclosed_as_the_base_state() -> None:
    """0.866 (three-measure) and 0.895 (six-measure) both exceed 0.75."""
    res = run()
    assert res.value_dict()["classification"] == "HIGH"
    assert res.value_dict()["base_rates"]["current_measure_count_high"] == pytest.approx(0.866)
    assert any("BASE STATE" in w for w in res.warnings)


def test_six_measure_read_carries_the_six_measure_base_rate() -> None:
    res = run(median_cpi_direction=1, trimmed_mean_direction=1, sticky_price_cpi_direction=1)
    assert res.value_dict()["base_rates"]["current_measure_count_high"] == pytest.approx(0.895)


def test_base_state_warning_does_not_fire_when_not_high() -> None:
    res = run(core_cpi_direction=-1)
    assert not any("BASE STATE" in w for w in res.warnings)


def test_inputs_used_lists_only_supplied_measures() -> None:
    res = run(median_cpi_direction=1)
    assert res.value_dict()["measures_used"] == 4
    assert set(res.inputs_used) == {
        "headline_cpi_direction",
        "core_cpi_direction",
        "core_pce_direction",
        "median_cpi_direction",
    }


def test_the_sign_test_caveat_is_always_on() -> None:
    res = run()
    assert any("weak statistic" in w for w in res.warnings)


def test_confidence_tracks_the_family_count_not_the_measure_count() -> None:
    """Two independent families -> 0.70 - 0.20 + 0.10 = 0.60."""
    res = run()
    assert res.value_dict()["independent_families"] == 2
    assert res.confidence == pytest.approx(0.60)


def test_thresholds_come_from_config() -> None:
    """LAW 1: the band boundaries are config leaves, not literals."""
    s = get_settings().inflation.convergence
    assert s.high == pytest.approx(0.8)
    assert s.medium == pytest.approx(0.6)
    assert s.deep_conflict_share == pytest.approx(0.25)
    assert s.min_families("high") == 2
    assert s.min_families("medium") == 2
    assert s.min_families("low") == 1


def test_conflicted_is_not_a_band_in_the_vocabulary() -> None:
    """The reason F-IC-001 exists: CONFLICTED can never appear in bands."""
    res = run(core_cpi_direction=-1)
    assert "CONFLICTED" not in res.value_dict()["bands_available"]
    assert set(res.value_dict()["bands_available"]) <= {"HIGH", "MEDIUM", "LOW"}
