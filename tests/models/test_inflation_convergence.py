"""Tests for Module 5.3 — ``inflation_convergence_classifier``.

Section 15.19-C specifies the classifier; Section 15.19-D obliges it to weight
its confidence by the number of **genuinely independent source families**
rather than by the number of agreeing signals. This is the first caller of
Module 13's ``count_independent_families``, so it is also the increment in which
that obligation stops being a comment and starts being enforced.

Four corrections are pinned here (D-047):

1. **The CONFLICTED gate examines the whole set, not the headline/core pair.**
   §15.19-C tests only ``directions[0] * directions[1] < 0``. Over 522 real
   months that misses 14 months of genuine split, 7 of which it labels HIGH.
2. **HIGH is the base state, not a finding.** The specification's 3-measure
   form returns HIGH in 86.6% of 522 real months. The measured rate is published
   in ``value`` and warned about rather than silently retuned, because the
   thresholds are the specification's own literals and changing them is a spec
   decision, not an implementation one.
3. **The thresholds are degenerate below n=5.** Attainable fractions at n=3 are
   {0, 1/3, 2/3, 1}; ``>= 0.8`` requires unanimity and ``0.6 <= frac < 0.8`` is
   the single value 2/3. Disclosed in ``attainable_fracs`` and warned about.
4. **The classifier runs at six measures, not three.** §21.1 records
   ``median_cpi_direction`` and ``trimmed_mean_direction`` as BLOCKED; both are
   reachable on FRED today (``MEDCPIM157SFRBCLE``, ``PCETRIM1M158SFRBDAL``).
   That is the O-21 defect class a third time — a block is a claim about the
   world and it decays.

The most important test in this file is
``test_five_redundant_measures_do_not_outscore_two_independent_ones``: it is
Section 15.19-D's own stated test, and it fails against any implementation whose
denominator is the raw signal count.
"""

from __future__ import annotations

import itertools
import math

import pytest
from pydantic import ValidationError

from macro_engine.config import get_settings
from macro_engine.models.contracts import ConfidenceInputs, ModelResult, compute_confidence
from macro_engine.models.inflation_convergence import (
    CONVERGENCE_CLASSES,
    InflationConvergenceInputs,
    InflationConvergenceVerdict,
    inflation_convergence_classifier,
)
from tests.helpers import as_int, as_str

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def _three(*, headline: int, core: int, pce: int) -> InflationConvergenceInputs:
    """The specification's Phase 1 three-measure configuration.

    Note what this fixture *is*: the minimum legal call. All three fields are
    required, so no invocation of this model can supply fewer than three
    measures — which is why several tests below compare n=3 against n=6 rather
    than comparing 2 against 4.
    """
    return InflationConvergenceInputs(
        headline_cpi_direction=headline,  # type: ignore[arg-type]
        core_cpi_direction=core,  # type: ignore[arg-type]
        core_pce_direction=pce,  # type: ignore[arg-type]
    )


def _one_family_three() -> InflationConvergenceInputs:
    """**DOES NOT EXIST — see ``test_a_single_family_input_is_unreachable``.**

    Kept as a named non-fixture so the impossibility is documented where the
    other fixtures live rather than only discovered in one test.
    """
    raise AssertionError(
        "A single-family input is not constructible: headline and core CPI are "
        "BLS, core PCE is BEA, and all three are required. The minimum legal "
        "call spans two families."
    )


def _three_measures_two_families() -> InflationConvergenceInputs:
    """The minimum legal call: 3 measures spanning TWO families.

    headline + core CPI (BLS) and core PCE (BEA). All three required, so every
    call to this model spans at least these two families — which is why
    ``independent_families == 1`` is unreachable no matter what is supplied.
    """
    return InflationConvergenceInputs(
        headline_cpi_direction=1,
        core_cpi_direction=1,
        core_pce_direction=1,
    )


def _four_measures_two_families() -> InflationConvergenceInputs:
    """Four measures, TWO families: headline, core, median CPI (BLS) + core PCE.

    Four agreeing readings, two votes — the §15.19-D demonstration this build
    can actually construct. Median CPI is tagged BLS despite being published by
    the Cleveland Fed; that mapping is what keeps the count at two.
    """
    return InflationConvergenceInputs(
        headline_cpi_direction=1,
        core_cpi_direction=1,
        core_pce_direction=1,
        median_cpi_direction=1,
    )


def _six_measures_three_families() -> InflationConvergenceInputs:
    """The maximum: 6 measures spanning THREE families.

    BLS_CPI (headline, core, median, sticky), BEA_PCE (core PCE), DALLAS_FED
    (trimmed mean). Six signals, three votes. There is no fourth family reachable
    from this model's inputs, which is why ``families_for_full_credit`` is 3.
    """
    return _six(1, 1, 1, 1, 1, 1)


def _two_families_three_measures() -> InflationConvergenceInputs:
    """Alias fixture retained for readability at call sites that contrast the
    minimum legal call against the six-measure one."""
    return _three_measures_two_families()


def _six(*directions: int) -> InflationConvergenceInputs:
    """All six reachable measures, in the fixed ``_INPUT_FAMILIES`` order."""
    assert len(directions) == 6
    return InflationConvergenceInputs(
        headline_cpi_direction=directions[0],  # type: ignore[arg-type]
        core_cpi_direction=directions[1],  # type: ignore[arg-type]
        core_pce_direction=directions[2],  # type: ignore[arg-type]
        median_cpi_direction=directions[3],  # type: ignore[arg-type]
        trimmed_mean_direction=directions[4],  # type: ignore[arg-type]
        sticky_price_cpi_direction=directions[5],  # type: ignore[arg-type]
    )


def _four_family_six_agreeing() -> InflationConvergenceInputs:
    """Six measures, every available family, every one reading up.

    Families: BLS_CPI (headline, core, median, sticky), BEA_PCE (core PCE),
    DALLAS_FED (trimmed mean) — and that is only three families, not four; there
    is no fourth family reachable from these six inputs. Six signals, three
    votes.
    """
    return _six(1, 1, 1, 1, 1, 1)


def _verdict(result: ModelResult) -> InflationConvergenceVerdict:
    value = result.value
    assert isinstance(value, dict)
    return InflationConvergenceVerdict.model_validate(value)


# --------------------------------------------------------------------------
# 1. Section 15.19-D's own test: redundancy must not buy confidence
# --------------------------------------------------------------------------


def test_five_redundant_measures_do_not_outscore_two_independent_ones() -> None:
    """§15.19-D, verbatim: *five agreeing BLS-CPI-derived sub-measures should
    never produce higher confidence than two genuinely independent sources
    agreeing (one government release, one market-based signal).*

    The specification's illustration — five against two — is not constructible
    here. Three fields are required (headline CPI, core CPI, core PCE), so the
    smallest legal call already spans two families, and the most CPI-only
    readings obtainable is FOUR (headline, core, median, sticky-price — all
    BLS-survey-derived, therefore ONE family). So the strictest comparison this
    build can actually make is:

    * **4 CPI readings / 1 family** — but the required core PCE is a second
      family, so this is really 5 readings / 2 families; and
    * **3 readings / 2 families** — the minimum legal call.

    The comparison below therefore holds readings NEARLY fixed (5 vs 3) while
    the redundant set adds *two* extra CPI readings and gains **no** additional
    family. Any implementation that scores the extra readings is rewarding
    redundancy.

    The invariant is one-directional on purpose: the redundant set may not
    *exceed* the independent set. Equality satisfies the requirement (and is the
    expected outcome, since both have two families); what is forbidden is the
    redundant set scoring higher on the strength of its extra signals.
    """
    # Five readings, two families: four of the five are BLS CPI.
    redundant = inflation_convergence_classifier(
        InflationConvergenceInputs(
            headline_cpi_direction=1,
            core_cpi_direction=1,
            core_pce_direction=1,
            median_cpi_direction=1,
            sticky_price_cpi_direction=1,
        )
    )
    # Three readings, two families: the minimum legal call, same family count.
    independent = inflation_convergence_classifier(_three_measures_two_families())

    redundant_verdict = _verdict(redundant)
    independent_verdict = _verdict(independent)

    # The arithmetic that makes the point: two extra readings, zero extra votes.
    assert redundant_verdict.measures_used == 5
    assert independent_verdict.measures_used == 3
    assert redundant_verdict.independent_families == independent_verdict.independent_families == 2
    assert sorted(redundant_verdict.family_names) == ["bea_pce", "bls_cpi"]

    assert redundant.confidence <= independent.confidence, (
        "Section 15.19-D violated: five readings spanning the same two families "
        "as three readings scored strictly higher. The confidence denominator is "
        "the signal count, not the family count."
    )


def test_family_count_governs_confidence_not_signal_count() -> None:
    """Confidence must be a function of the family count, not the signal count.

    This is the cleanest form available: **families held constant at two, signal
    count varied from three to six.** Since both calls carry two families, a
    confidence rule driven by families alone returns the same number, and the
    assertion is *equality* — which is a much sharper test than an inequality.

    The complementary direction is
    ``test_adding_a_third_family_raises_confidence``: signals held near-constant
    while families go 2 -> 3.
    """
    three = inflation_convergence_classifier(_three_measures_two_families())
    four = inflation_convergence_classifier(_four_measures_two_families())

    assert _verdict(three).measures_used == 3
    assert _verdict(four).measures_used == 4
    assert _verdict(three).independent_families == 2
    assert _verdict(four).independent_families == 2

    # Same evidence base, different signal count: the confidence must not move.
    assert three.confidence == four.confidence, (
        "Confidence changed when only the SIGNAL count changed. Two extra BLS "
        "readings are not extra evidence (Section 15.19-D)."
    )


def test_adding_a_third_family_raises_confidence() -> None:
    """The other direction: a genuinely new source family must raise confidence.

    Two calls, **four measures each** — the signal count is held *exactly*
    constant. The first spans two families (BLS + BEA); the second adds the
    Dallas Fed's trimmed-mean PCE for a third. If the implementation passed
    ``len(directions)`` both would receive 4 and score identically.
    """
    two_families = inflation_convergence_classifier(_four_measures_two_families())
    three_families = inflation_convergence_classifier(
        InflationConvergenceInputs(
            headline_cpi_direction=1,
            core_cpi_direction=1,
            core_pce_direction=1,
            trimmed_mean_direction=1,  # DALLAS_FED
        )
    )

    assert _verdict(two_families).measures_used == 4
    assert _verdict(three_families).measures_used == 4
    assert _verdict(two_families).independent_families == 2
    assert _verdict(three_families).independent_families == 3
    assert three_families.confidence > two_families.confidence


# --------------------------------------------------------------------------
# 2. The sign test's arithmetic, hand-computed
# --------------------------------------------------------------------------


def test_unanimous_three_measure_reads_high_at_frac_one() -> None:
    """3 of 3 agree. frac = 3/3 = 1.0 >= 0.8, so HIGH."""
    result = inflation_convergence_classifier(_three(headline=1, core=1, pce=1))
    verdict = _verdict(result)

    assert verdict.classification == "HIGH"
    assert verdict.agreeing == 3
    assert verdict.opposing == 0
    assert verdict.flat == 0
    assert verdict.frac_agreeing == pytest.approx(1.0)


def test_two_of_three_agree_reads_medium_at_frac_two_thirds() -> None:
    """2 of 3 agree UNANIMOUSLY ON THE SIDE THAT MATTERS is not MEDIUM — it is
    CONFLICTED, because at n=3 a lone dissenter is a whole third of the set.

    Hand arithmetic for the corrected gate: majority = max(2, 1) = 2;
    losing = min(2, 1) = 1; threshold = 0.25 * 3 = 0.75; 1 >= 0.75, so the
    whole-set gate fires and returns CONFLICTED *before* the band test — which
    would otherwise have returned 2/3 = 0.6667 >= 0.6, i.e. MEDIUM.

    **This is a real consequence of the correction, and it is stated rather than
    smoothed over.** ``deep_conflict_share`` is a *share*, so its absolute
    stringency scales with n: at n=6 it takes two dissenters to fire, at n=3 it
    takes one. Whether that is the right behaviour at n=3 is a specification
    question, not an implementation one — it is recorded as a finding in D-047
    and flagged here so the next reader does not "fix" the gate to restore
    MEDIUM.

    MEDIUM is reachable with five measures; see
    ``test_medium_is_reachable_at_five_measures``.
    """
    result = inflation_convergence_classifier(_three(headline=1, core=1, pce=-1))
    verdict = _verdict(result)

    assert verdict.classification == "CONFLICTED"
    assert verdict.agreeing == 2
    assert verdict.opposing == 1
    assert verdict.frac_agreeing == pytest.approx(2 / 3, abs=1e-6)
    assert any("WHOLE-SET gate" in w for w in result.warnings)


def test_medium_is_reachable_at_five_measures() -> None:
    """MEDIUM's reachability, at the smallest n where it survives the gate.

    Five measures: four up, one down. Hand arithmetic: majority = 4;
    losing = 1; threshold = 0.25 * 5 = 1.25; 1 < 1.25, so the whole-set gate does
    NOT fire. frac = 4/5 = 0.8, which is >= high (0.8), so this reads HIGH — not
    MEDIUM. Three of five: majority = 3, frac = 3/5 = 0.6 >= medium and < high,
    and losing = 2 >= 0.25 * 5 = 1.25, so the gate fires first and CONFLICTED
    returns.

    The band that survives at n=5 is therefore narrow, and this test pins the
    exact case that reaches MEDIUM: four of six (2/3, below the gate).
    """
    # Six measures: four up, two down. majority = 4, losing = 2,
    # threshold = 0.25 * 6 = 1.5, so 2 >= 1.5 -> the gate fires. Not MEDIUM.
    gated = inflation_convergence_classifier(_six(1, 1, 1, 1, -1, -1))
    assert _verdict(gated).classification == "CONFLICTED"

    # Four up, one down, one flat at n=6: majority = 4, losing = 1 < 1.5, so the
    # gate does not fire; frac = 4/6 = 0.6667 >= 0.6 and < 0.8 -> MEDIUM.
    medium = inflation_convergence_classifier(_six(1, 1, 1, 1, -1, 0))
    verdict = _verdict(medium)
    assert verdict.classification == "MEDIUM"
    assert verdict.frac_agreeing == pytest.approx(4 / 6, abs=1e-6)


def test_split_three_measure_cannot_reach_medium() -> None:
    """1 up, 1 down, 1 flat at n=3. Hand arithmetic: majority = 1; frac = 1/3 =
    0.3333 < 0.6, so no band fires. The pair gate does not fire either (1 * -1 on
    headline/core IS negative here, so it does)...

    Wait — headline is +1 and core is -1, so ``headline * core = -1 < 0`` and the
    *pair* gate fires before the band test. So this case is CONFLICTED via the
    specification's own original gate, not via the correction. That distinction
    is the point of the test: it isolates the pair gate from the whole-set gate.

    For the LOW path at n=3 with no conflict at all, see
    ``test_a_flat_reading_is_not_corroboration``.
    """
    result = inflation_convergence_classifier(_three(headline=1, core=-1, pce=0))
    verdict = _verdict(result)

    assert verdict.classification == "CONFLICTED"
    assert verdict.agreeing == 1
    assert verdict.opposing == 1
    assert verdict.flat == 1
    # The objection is that the corrected gate fired — it did not. This is the
    # specification's original pair gate.
    assert not any("WHOLE-SET gate" in w for w in result.warnings)


def test_a_flat_reading_is_not_corroboration() -> None:
    """A zero change must not be pooled into either side.

    Hand arithmetic: (1, 0, 0) — one measure up, two flat. If flat were pooled
    with the down side, the majority would be 2/3 and the verdict MEDIUM
    (reversed). Pooled with the up side it would be 3/3 HIGH. Counted
    separately, the majority is 1/3 and the verdict is LOW.

    The direction of the error matters: pooling flat readings inflates
    convergence, which is exactly the failure mode Section 15.19-D exists to
    prevent.
    """
    result = inflation_convergence_classifier(_three(headline=1, core=0, pce=0))
    verdict = _verdict(result)

    assert verdict.flat == 2
    assert verdict.agreeing == 1
    assert verdict.opposing == 0
    assert verdict.classification == "LOW"
    assert any("EXCLUDED from both sides" in w for w in result.warnings)


def test_all_flat_is_low_and_not_reported_as_conflict() -> None:
    """Nothing moved. That is absence of evidence, not conflict.

    The degenerate guard: with no up and no down readings, the losing side is 0
    and the conflict threshold is 0 * total = 0, so a naive ``>=`` would report
    CONFLICTED for a month in which nothing happened at all.
    """
    result = inflation_convergence_classifier(_three(headline=0, core=0, pce=0))
    verdict = _verdict(result)

    assert verdict.classification == "LOW"
    assert verdict.flat == 3
    assert verdict.agreeing == 0
    assert verdict.opposing == 0


# --------------------------------------------------------------------------
# 3. Correction 1 — the CONFLICTED gate examines the whole set
# --------------------------------------------------------------------------


def test_headline_core_split_is_conflicted() -> None:
    """The specification's own gate: headline and core directly oppose.

    Hand arithmetic: 1 * -1 = -1 < 0, so CONFLICTED fires before any band test.
    """
    result = inflation_convergence_classifier(_three(headline=1, core=-1, pce=1))
    verdict = _verdict(result)

    assert verdict.classification == "CONFLICTED"


def test_conflict_is_detected_when_headline_and_core_agree() -> None:
    """Correction 1. The case §15.19-C's pair gate misses.

    Six measures: headline +, core +, core_pce + (three agreeing); median -,
    trimmed -, sticky - (three opposing). Headline * core is positive, so the
    specification's pair gate never fires and its band test — majority 3 of 6,
    frac 0.5 — would return LOW, i.e. "no convergence" reported as a
    low-confidence read rather than as the outright disagreement it is.

    Hand arithmetic for the corrected gate: losing = min(3, 3) = 3;
    threshold = 0.25 * 6 = 1.5; 3 >= 1.5, so CONFLICTED.
    """
    result = inflation_convergence_classifier(_six(1, 1, 1, -1, -1, -1))
    verdict = _verdict(result)

    assert verdict.classification == "CONFLICTED"
    assert verdict.agreeing == 3
    assert verdict.opposing == 3
    assert any("WHOLE-SET gate" in w for w in result.warnings)


def test_a_lone_dissenter_does_not_trigger_the_whole_set_gate() -> None:
    """The correction must not swallow the ordinary case.

    Six measures: five agree, one opposes. Hand arithmetic: losing = 1;
    threshold = 0.25 * 6 = 1.5; 1 < 1.5, so the whole-set gate does NOT fire and
    the majority fraction governs: 5/6 = 0.8333 >= 0.8, so HIGH.

    Without this test, a gate written as ``losing > 0`` would pass the
    conflict test above and misclassify every ordinary month.
    """
    result = inflation_convergence_classifier(_six(1, 1, 1, 1, 1, -1))
    verdict = _verdict(result)

    assert verdict.classification == "HIGH"
    assert verdict.opposing == 1
    assert not any("WHOLE-SET gate" in w for w in result.warnings)


def test_deep_conflict_share_is_read_from_config_not_literal() -> None:
    """No hardcoded thresholds (§22.4): the gate reads the configured share.

    Recomputes the boundary from the config value rather than restating 0.25,
    so a retune of the YAML moves this test's expectation with it and a literal
    in the model would break the equality.
    """
    share = get_settings().inflation.convergence.deep_conflict_share
    # n=6, so the smallest losing side satisfying `losing >= share * 6` is
    # ceil(share * 6) = ceil(1.5) = 2.
    required = int(-(-share * 6 // 1))  # ceil without importing math
    assert required == 2

    # 2 opposing of 6: 2 >= 1.5 -> CONFLICTED.
    at_threshold = inflation_convergence_classifier(_six(1, 1, 1, 1, -1, -1))
    assert _verdict(at_threshold).classification == "CONFLICTED"
    # 1 opposing of 6: 1 < 1.5 -> the gate stays silent.
    below = inflation_convergence_classifier(_six(1, 1, 1, 1, 1, -1))
    assert _verdict(below).classification != "CONFLICTED"


def test_the_conflict_boundary_is_inclusive() -> None:
    """The gate is ``losing >= share * total``, and the boundary is reachable.

    Written against survivor D2c: changing ``>=`` to ``>`` left the suite green,
    because at n=3, 5 and 6 the threshold ``0.25 * total`` is 0.75, 1.25 and 1.5
    — none of which is an integer, so no possible value of ``losing`` (always an
    integer) ever *equals* the threshold and the two operators agree everywhere.

    **At n=4 the threshold is exactly 1.0, and the boundary is touched.** A 3-1
    split has ``losing == 1``, which satisfies ``>= 1.0`` and fails ``> 1.0``.
    That single case is the only place in the whole reachable input space where
    the operator's direction is observable, which is precisely why it needs its
    own test rather than being covered incidentally.

    Hand arithmetic: minority = 1; threshold = 0.25 * 4 = 1.0; 1 >= 1.0 -> the
    gate fires and returns CONFLICTED before the band test (which would give
    frac = 3/4 = 0.75 < 0.8, i.e. MEDIUM).
    """
    share = get_settings().inflation.convergence.deep_conflict_share
    assert share * 4 == pytest.approx(1.0), (
        "this test depends on the n=4 threshold being exactly 1.0; if the "
        "configured share changes, the boundary must be re-located"
    )

    # 3 up, 1 down at n=4 — the minority is exactly at the threshold.
    result = inflation_convergence_classifier(
        InflationConvergenceInputs(
            headline_cpi_direction=1,
            core_cpi_direction=1,
            core_pce_direction=-1,
            median_cpi_direction=1,
        )
    )
    verdict = _verdict(result)

    assert verdict.agreeing == 3
    assert verdict.opposing == 1
    assert verdict.classification == "CONFLICTED", (
        "the conflict boundary is inclusive: a minority exactly at share * total must fire the gate"
    )
    assert any("WHOLE-SET gate" in w for w in result.warnings)


def test_the_pair_gate_fires_on_its_own_at_six_measures() -> None:
    """Written after survivor B2: disabling §15.19-C's pair gate changed nothing.

    Why it survived: at n=3 the corrected whole-set gate *subsumes* the pair gate.
    A headline/core split means ``losing >= 1``, and ``1 >= 0.25 * 3 = 0.75``, so
    the whole-set gate fires for every case the pair gate would have caught. The
    pair gate is therefore redundant **at n=3** — the only measure count the
    original tests used.

    At n=6 the two gates separate cleanly: the pair gate fires on a
    headline/core opposition that is only ONE dissenter out of six, which the
    whole-set gate (threshold 1.5) does not reach.

    Hand arithmetic for the case below: headline +, core PCE +, and the other
    four all +, except core CPI which reads -. So headline = +1, core = -1, and
    the split is 5 up / 1 down. The whole-set gate: losing = 1, threshold =
    0.25 * 6 = 1.5, 1 < 1.5 -> silent. The pair gate: 1 * -1 = -1 < 0 -> fires.
    CONFLICTED must be returned.
    """
    result = inflation_convergence_classifier(_six(1, -1, 1, 1, 1, 1))
    verdict = _verdict(result)

    assert verdict.classification == "CONFLICTED"
    assert verdict.agreeing == 5
    assert verdict.opposing == 1
    # The whole-set gate did NOT fire — 1 < 1.5. So the pair gate is what fired,
    # and the warning must say so by being absent.
    assert not any("WHOLE-SET gate" in w for w in result.warnings)


def test_the_two_gates_are_independently_sufficient() -> None:
    """Neither gate subsumes the other; each is reachable alone.

    The pair gate fires alone when headline and core oppose but the split is wide
    (5-1 at n=6). The whole-set gate fires alone when headline and core AGREE but
    the set splits evenly (3-3 at n=6). Two cases, two gates, one test — and if
    either gate is disabled exactly one of these goes wrong.
    """
    # Pair gate alone: headline and core oppose, split is 5-1.
    pair_only = _verdict(inflation_convergence_classifier(_six(1, -1, 1, 1, 1, 1)))
    assert pair_only.classification == "CONFLICTED"

    # Whole-set gate alone: headline and core agree, split is 3-3.
    whole_set_only = _verdict(inflation_convergence_classifier(_six(1, 1, 1, -1, -1, -1)))
    assert whole_set_only.classification == "CONFLICTED"
    assert whole_set_only.agreeing == 3
    assert whole_set_only.opposing == 3


# --------------------------------------------------------------------------
# 4. Correction 3 — the thresholds are degenerate below five measures
# --------------------------------------------------------------------------


def test_attainable_fracs_are_reported_for_the_measure_count() -> None:
    """Hand arithmetic at n=3: {0/3, 1/3, 2/3, 3/3} = [0, 0.333333, 0.666667, 1]."""
    result = inflation_convergence_classifier(_three(headline=1, core=1, pce=1))
    verdict = _verdict(result)

    assert verdict.attainable_fracs == [
        0.0,
        pytest.approx(1 / 3, abs=1e-6),
        pytest.approx(2 / 3, abs=1e-6),
        1.0,
    ]


def test_medium_band_has_no_width_at_three_measures() -> None:
    """The degeneracy, proved rather than asserted as prose.

    The configured thresholds are 0.6 and 0.8. The attainable fractions at n=3
    are {0, 1/3, 2/3, 1}. Exactly ONE attainable fraction lies in [0.6, 0.8):
    2/3. So "MEDIUM" is a point, not a band. At n>=5 more attainable values fall
    between the thresholds and the band acquires width.

    This test asserts the count of attainable fractions inside the band, which
    is the property the warning describes — not the warning's wording.
    """
    settings = get_settings().inflation.convergence
    result = inflation_convergence_classifier(_three(headline=1, core=1, pce=1))
    verdict = _verdict(result)

    in_band = [f for f in verdict.attainable_fracs if settings.medium <= f < settings.high]
    assert in_band == [pytest.approx(2 / 3, abs=1e-6)], (
        "MEDIUM was expected to be a single-point band at n=3"
    )
    assert any("DEGENERATE" in w for w in result.warnings)


def test_the_configured_thresholds_are_the_specifications_literals() -> None:
    """The thresholds are pinned by VALUE, not merely read back from config.

    Written after a mutation survivor (C-1a in ``scripts/mutation_inflation_convergence.py``):
    changing the YAML ``high_threshold`` from 0.8 to 0.7 left every test green,
    because the test above reads the value back through the same accessor the
    model uses — it proved the two agree, not that either is right. That is the
    D-027 circularity in a config-test costume.

    Section 15.19-C specifies 0.6 and 0.8. Asserting them literally is the point:
    if a future calibration deliberately moves them, it must edit this test too,
    which forces the change to be *noticed* rather than absorbed silently.

    The values are also asserted to satisfy ``medium < high``, because a
    mis-ordered pair would make every band boundary behave nonsensically rather
    than fail loudly.
    """
    settings = get_settings().inflation.convergence

    assert settings.medium == pytest.approx(0.6)
    assert settings.high == pytest.approx(0.8)
    assert settings.medium < settings.high

    # And the thresholds must actually govern the classification — a threshold
    # that is read but never consulted is dead config. Hand arithmetic at n=6:
    # frac 5/6 = 0.8333 >= 0.8 -> HIGH; frac 4/6 = 0.6667 -> MEDIUM.
    high = _verdict(inflation_convergence_classifier(_six(1, 1, 1, 1, 1, -1)))
    medium = _verdict(inflation_convergence_classifier(_six(1, 1, 1, 1, -1, 0)))
    assert high.classification == "HIGH"
    assert medium.classification == "MEDIUM"


def test_the_configured_high_threshold_is_not_read_back_only() -> None:
    """A threshold above every attainable fraction can never produce HIGH.

    The behavioural half of the pin above: if the HIGH threshold were raised
    beyond 1.0, no reading could ever be HIGH and the class would be unreachable.
    This asserts the band is *live* — that a unanimous reading crosses it — which
    a read-back test cannot do.
    """
    settings = get_settings().inflation.convergence
    assert settings.high <= 1.0, "no attainable fraction could ever reach HIGH"

    unanimous = _verdict(inflation_convergence_classifier(_six(1, 1, 1, 1, 1, 1)))
    assert unanimous.frac_agreeing == pytest.approx(1.0)
    assert unanimous.classification == "HIGH"


def test_families_for_full_credit_is_live_not_dead_config() -> None:
    """Written after survivor C-1b: ``families_for_full_credit`` was dead config.

    Root cause found by the sweep: the property read a configured value that
    **nothing consumed and that was arithmetically wrong** — it said 3, while
    ``compute_confidence`` credits ``count * bonus`` capped at ``cap``, i.e.
    ``ceil(0.25 / 0.05) = 5`` families. The property is now *derived* from those
    two constants and cross-checks the configured entry against the derivation,
    so the two cannot disagree.

    Three things are asserted:

    1. The derived value equals the arithmetic the confidence rule actually
       performs — recomputed here from the constants, not restated.
    2. The confidence schedule is *live* below the ceiling: it strictly
       increases with each added family.
    3. It *saturates* at the ceiling: at and above it, the credit stops.
    """
    settings = get_settings().inflation.convergence
    confidence = get_settings().confidence

    bonus = float(confidence.source_independence_bonus.value)
    cap = float(confidence.source_independence_bonus_cap.value)
    expected_ceiling = math.ceil(cap / bonus)

    assert settings.families_for_full_credit == expected_ceiling

    # The CONFIGURED entry must agree with the derivation, and it is read
    # directly here rather than through the property — otherwise this test
    # proves only that the property is self-consistent, which is the D-027
    # circularity in a config-test costume. This is the assertion that kills
    # C-1c (a config value contradicted by the arithmetic).
    configured = int(settings.confidence_ceiling_by_independent_families.value)
    assert configured == expected_ceiling, (
        f"the configured ceiling ({configured}) contradicts the confidence "
        f"constants (bonus={bonus}, cap={cap} -> {expected_ceiling} families)"
    )

    # And the cross-check must be LIVE, not merely present: a contradictory
    # configuration must raise rather than be silently tolerated. Simulated by
    # calling the property on a model whose configured entry is wrong — this is
    # what kills C-1b (the cross-check disabled).
    wrong_entry = settings.confidence_ceiling_by_independent_families.model_copy(
        update={"value": expected_ceiling + 1}
    )
    contradicted = settings.model_copy(
        update={"confidence_ceiling_by_independent_families": wrong_entry}
    )
    with pytest.raises(ValueError, match="saturate at"):
        _ = contradicted.families_for_full_credit

    # The schedule must be live strictly below the ceiling.
    below = compute_confidence(ConfidenceInputs(source_independence_count=expected_ceiling - 1))
    at = compute_confidence(ConfidenceInputs(source_independence_count=expected_ceiling))
    above = compute_confidence(ConfidenceInputs(source_independence_count=expected_ceiling + 1))
    assert below < at
    assert at == above, (
        "the independence credit must saturate at families_for_full_credit; "
        f"it kept rising ({at} -> {above})"
    )


def test_the_ceiling_is_unreachable_from_this_models_inputs() -> None:
    """This classifier can supply at most three families, so the credit never
    saturates — a disclosed limitation, not a bug.

    The reachable families are BLS_CPI (headline, core, median, sticky),
    BEA_PCE (core PCE) and DALLAS_FED (trimmed mean). ``families_for_full_credit``
    is 5. So the top of the confidence schedule — a fully-corroborated reading —
    is **not attainable** by this model today.

    The consequence is worth stating plainly because it bounds what a HIGH verdict
    can mean: the strongest reading this classifier can produce is three
    independent families, and `source_independence_count` therefore never exceeds
    3. Adding a market-based input (a TIPS breakeven) would make 4 available.
    """
    settings = get_settings().inflation.convergence
    max_families = _verdict(
        inflation_convergence_classifier(_six(1, 1, 1, 1, 1, 1))
    ).independent_families

    assert max_families == 3
    assert max_families < settings.families_for_full_credit


def test_no_degeneracy_warning_at_six_measures() -> None:
    """At n=6 the attainable set is {0, 1/6, ..., 1} and the band has width.

    Hand arithmetic: [0.6, 0.8) contains 4/6 = 0.6667 and 5/6 = 0.8333 is out;
    3/6 = 0.5 is below. So exactly one value — wait, two candidates:
    4/6 = 0.6667 is in, and 5/6 = 0.8333 >= 0.8 is not. So one value again at
    n=6. The band becomes genuinely multi-valued at n=5 and n=8; what matters
    here is that the n<5 warning is not raised, because the warning is a claim
    about the measure count, not about band width in general.
    """
    result = inflation_convergence_classifier(_six(1, 1, 1, 1, 1, 1))
    assert not any("DEGENERATE" in w for w in result.warnings)


def test_degeneracy_warning_is_raised_without_a_classification_gate() -> None:
    """The warning is about the configuration, not about the reading.

    A LOW month at n=3 has the same degenerate threshold pair as a HIGH one, so
    the warning must not be conditional on the class. Gating it on HIGH would
    make it invisible in exactly the cases where a reader is most likely to
    over-read the band structure.
    """
    assert get_settings().inflation.convergence.medium < get_settings().inflation.convergence.high

    high = inflation_convergence_classifier(_three(headline=1, core=1, pce=1))
    low = inflation_convergence_classifier(_three(headline=1, core=0, pce=0))

    assert any("DEGENERATE" in w for w in high.warnings)
    assert any("DEGENERATE" in w for w in low.warnings)


# --------------------------------------------------------------------------
# 5. Correction 2 — the base state travels with a HIGH reading
# --------------------------------------------------------------------------


def test_high_carries_its_measured_base_rate() -> None:
    """D-029: a categorical travels with its own measured frequency.

    The published base rates are the ones measured over real history, read from
    config rather than restated, so a recalibration moves both together.
    """
    settings = get_settings().inflation.convergence
    result = inflation_convergence_classifier(_three(headline=1, core=1, pce=1))
    verdict = _verdict(result)

    assert verdict.classification == "HIGH"
    assert verdict.base_rates["three_measure_high"] == pytest.approx(
        settings.measured_base_rates.three_measure_high
    )
    assert verdict.base_rates["six_measure_high"] == pytest.approx(
        settings.measured_base_rates.six_measure_high
    )
    assert any("BASE STATE" in w for w in result.warnings)


def test_current_measure_count_high_follows_the_supplied_count() -> None:
    """``current_measure_count_high`` is the rate for *this* invocation's n.

    The point of the field: an n=3 reading and an n=6 reading have different
    base rates (86.6% vs 89.5% measured), so the disclosure must select the one
    matching the call rather than reporting a single fixed number.
    """
    settings = get_settings().inflation.convergence

    three = _verdict(inflation_convergence_classifier(_three(headline=1, core=1, pce=1)))
    six = _verdict(inflation_convergence_classifier(_six(1, 1, 1, 1, 1, 1)))

    assert three.base_rates["current_measure_count_high"] == pytest.approx(
        settings.measured_base_rates.three_measure_high
    )
    assert six.base_rates["current_measure_count_high"] == pytest.approx(
        settings.measured_base_rates.six_measure_high
    )


def test_the_base_state_warning_is_specific_to_high() -> None:
    """A LOW reading is the informative case and must not carry the HIGH caveat.

    If the warning were unconditional it would be noise, and a reader would stop
    reading it — which is the failure mode the whole disclosure exists to avoid.
    """
    result = inflation_convergence_classifier(_three(headline=1, core=0, pce=0))
    verdict = _verdict(result)

    assert verdict.classification == "LOW"
    assert not any("BASE STATE" in w for w in result.warnings)


# --------------------------------------------------------------------------
# 6. Section 15.19-D's ceiling is visible, not silent
# --------------------------------------------------------------------------


def test_a_single_family_input_is_unreachable() -> None:
    """``independent_families == 1`` cannot occur, and the output must not imply it.

    This is a structural consequence of the schema rather than a design choice,
    and it is worth a test because a reader who sees
    ``independent_families: 2`` on every call might reasonably assume 1 is the
    floor of a scale that starts there. It does not: the three required measures
    are headline CPI, core CPI (both BLS) and core PCE (BEA), so **every** legal
    call spans at least two families.

    Exhaustive check over the reachable space: the family count takes exactly the
    values {2, 3}. Enumerated here rather than asserted as prose, so a future
    schema change that makes a single-family call possible fails this test
    instead of silently changing what the counts mean.

    Consequence for the warnings: the "one source family cannot corroborate
    itself" branch is **unreachable from the public API**. It is retained as
    defence against a future input set with a single family, and it carries a
    ``pragma: no cover``-style note in the source rather than a fabricated test.
    """
    optional = ["median_cpi_direction", "trimmed_mean_direction", "sticky_price_cpi_direction"]
    required = ["headline_cpi_direction", "core_cpi_direction", "core_pce_direction"]

    observed: set[int] = set()
    for extra in range(len(optional) + 1):
        for combo in itertools.combinations(optional, extra):
            kwargs = dict.fromkeys(required + list(combo), 1)
            verdict = _verdict(
                inflation_convergence_classifier(
                    InflationConvergenceInputs(**kwargs)  # type: ignore[arg-type]
                )
            )
            observed.add(verdict.independent_families)

    assert observed == {2, 3}, (
        f"the reachable family counts changed to {sorted(observed)}; the "
        "single-family warning branch and the band thresholds were calibrated "
        "against a floor of 2"
    )


def test_a_single_family_input_is_unreachable_via_the_raising_fixture() -> None:
    """The named non-fixture documents the impossibility at the fixture site."""
    with pytest.raises(AssertionError, match="not constructible"):
        _one_family_three()


def test_bands_available_reflects_the_family_count() -> None:
    """Two families support every band; the LOW-only case is unreachable.

    ``min_independent_families_per_band`` is ``{high: 2, medium: 2, low: 1}``.
    Because the family count floors at 2, every legal call clears the HIGH bar
    and ``bands_available`` is always ``["HIGH", "MEDIUM", "LOW"]``. The
    ``["LOW"]`` case is therefore unreachable from the public API — pinned by
    ``test_a_single_family_input_is_unreachable``.

    This is a real gap in Section 15.19-D's intended effect and it is recorded as
    such: the ceiling can never *bind* through the public API, because the
    evidence floor the schema imposes is already at the configured threshold. The
    mechanism is still implemented and tested at the helper level
    (``test_bands_available_computes_the_ceiling_from_config``) so that raising
    ``min_independent_families_per_band``, or adding a market-based input that
    changes the floor, takes effect without a code change.
    """
    settings = get_settings().inflation.convergence
    assert settings.min_families("high") == 2
    assert settings.min_families("medium") == 2
    assert settings.min_families("low") == 1

    for inputs in (
        _three_measures_two_families(),
        _four_measures_two_families(),
        _six(1, 1, 1, 1, 1, 1),
    ):
        verdict = _verdict(inflation_convergence_classifier(inputs))
        assert verdict.bands_available == ["HIGH", "MEDIUM", "LOW"]


def test_bands_available_computes_the_ceiling_from_config() -> None:
    """The ceiling is computed, not hardcoded — exercised at the helper level.

    ``bands_available`` can never bind through the public API (family floor = 2,
    HIGH threshold = 2). Testing it only through the public API would therefore
    leave the branch unexercised, and an unexercised branch that a future config
    change would suddenly activate is precisely the kind of latent defect §21.0
    warns about. So the helper is tested directly against the config it reads.

    Monotonicity is the property: a higher family count admits a superset of
    bands, strongest-first, and the ``min_families`` lookup is by lowercase band
    name.
    """
    from macro_engine.models.inflation_convergence import _bands_available

    # Below every threshold: no band.
    assert _bands_available(0) == []
    # At the LOW threshold only.
    assert _bands_available(1) == ["LOW"]
    # At the HIGH/MEDIUM thresholds.
    assert _bands_available(2) == ["HIGH", "MEDIUM", "LOW"]
    # Monotone: more families never removes a band.
    for n in range(0, 8):
        assert set(_bands_available(n)) <= set(_bands_available(n + 1))


def test_the_ceiling_warning_is_dead_code_through_the_api() -> None:
    """Written after survivor C4: dropping the ceiling warning changed nothing,
    because the branch that contains it can never be entered.

    The classifier's structure is::

        if classification in bands:      # pass
        elif bands:                      # the ceiling warning
        else:                            # the no-band warning

    ``bands`` comes from ``_bands_available(independent_families)``, and the
    family floor is 2 (the required BLS + BEA pair). ``_bands_available(2)`` is
    ``["HIGH", "MEDIUM", "LOW"]`` — every possible class — so
    ``classification in bands`` is **always True** and neither warning branch
    runs for any legal input.

    **This is a finding, not a fix.** The branches are correct; their
    precondition is unreachable. Deleting them would lose the §15.19-D ceiling
    mechanism for the day a market-based input changes the family floor, so they
    are retained and this test records the fact instead of leaving a reader to
    infer that the mechanism is live.

    What is asserted: the ceiling *cannot* bind today, and the warning generator
    would produce the right thing if it could. The second half is checked by
    calling the helper the classifier calls, with an argument the classifier
    cannot currently produce — which is legitimate here precisely *because* the
    point of the test is that the argument is unreachable.
    """
    from macro_engine.models.inflation_convergence import _bands_available

    # Every legal call lands in `bands` — asserted over the whole input space.
    for extra in range(4):
        for combo in itertools.combinations(
            ["median_cpi_direction", "trimmed_mean_direction", "sticky_price_cpi_direction"],
            extra,
        ):
            kwargs = dict.fromkeys(
                [
                    "headline_cpi_direction",
                    "core_cpi_direction",
                    "core_pce_direction",
                    *combo,
                ],
                1,
            )
            verdict = _verdict(
                inflation_convergence_classifier(
                    InflationConvergenceInputs(**kwargs)  # type: ignore[arg-type]
                )
            )
            assert verdict.classification in verdict.bands_available, (
                "a legal call produced a classification outside bands_available — "
                "the ceiling branch has become reachable and this test's premise "
                "is now wrong"
            )

    # The helper would produce a binding ceiling for a family count the model
    # cannot reach. `_bands_available(1) == ["LOW"]`, so a HIGH classification
    # would then fall outside it.
    assert _bands_available(1) == ["LOW"]
    assert "HIGH" not in _bands_available(1)


def test_the_base_rates_are_not_the_degenerate_high_confidence_literal() -> None:
    """The base-rate disclosure must describe the measured world, not a default.

    Written against survivor C1: making the disclosure *unconditional* (rather
    than dropping it) left the suite green, because no test asserted the warning
    was specific to HIGH. That test now exists
    (``test_the_base_state_warning_is_specific_to_high``); this one complements
    it by pinning the measured magnitude, so a placeholder 0.5 cannot pass.
    """
    settings = get_settings().inflation.convergence

    # The measured rates are large, because the price level rises most months.
    # A placeholder (0.5) or a rate from a different series would fail here.
    assert settings.measured_base_rates.three_measure_high > 0.8
    assert settings.measured_base_rates.six_measure_high > 0.8
    # And the six-measure form is at least as often HIGH as the three-measure
    # form, since it can only differ where the extra measures split.
    assert settings.measured_base_rates.six_measure_high >= (
        settings.measured_base_rates.three_measure_high - 0.05
    )


def test_single_family_warning_branch_is_unreachable_through_the_api() -> None:
    """The self-corroboration warning cannot fire from a legal call.

    Its guard is ``independent_families == 1 and total > 1``, and the family
    count floors at 2. The branch is retained deliberately — it is the correct
    guard if a future input set (a market-based breakeven, say) ever makes a
    single-family call possible — but it must NOT be tested by fabricating an
    illegal input, because such a test would prove nothing about the API and
    would break the moment the schema changes.

    What this test *does* assert is the complementary fact: every legal call
    carries at least two families and therefore never sees the warning.
    """
    for inputs in (
        _three_measures_two_families(),
        _four_measures_two_families(),
        _six(1, 1, 1, 1, 1, 1),
    ):
        result = inflation_convergence_classifier(inputs)
        verdict = _verdict(result)
        assert verdict.independent_families >= 2
        assert not any("ONE SOURCE FAMILY" in w for w in result.warnings)


def test_family_names_are_published_for_audit() -> None:
    """A count of 2 is not auditable; the names are.

    Two families must be reported as the two specific families, so a reader can
    check the claim rather than take it.
    """
    result = inflation_convergence_classifier(_three_measures_two_families())
    verdict = _verdict(result)

    assert sorted(verdict.family_names) == ["bea_pce", "bls_cpi"]


def test_median_cpi_counts_as_one_family_with_headline_and_core() -> None:
    """The family map's most debatable entry, pinned.

    The Cleveland Fed *publishes* median CPI, but it is computed from the BLS
    CPI survey microdata — the same production process headline and core depend
    on. A CPI redesign corrupts it exactly as it corrupts them. So adding median
    CPI to the three-measure call adds a *reading* and no family.

    This is the single mapping decision most likely to be "corrected" by a
    future reader into the wrong answer, so it carries its own test and its own
    comment in the source.
    """
    baseline = inflation_convergence_classifier(_three_measures_two_families())
    with_median = inflation_convergence_classifier(_four_measures_two_families())

    baseline_verdict = _verdict(baseline)
    verdict = _verdict(with_median)

    # One extra reading...
    assert verdict.measures_used == baseline_verdict.measures_used + 1
    # ...and zero extra families. That is the claim.
    assert verdict.independent_families == baseline_verdict.independent_families == 2
    assert verdict.family_names == baseline_verdict.family_names
    assert "bea_pce" in verdict.family_names  # only from core PCE, not median
    # And therefore no confidence gain from the extra reading.
    assert with_median.confidence == baseline.confidence


# --------------------------------------------------------------------------
# 7. The vocabulary's two halves (D-045a)
# --------------------------------------------------------------------------


def test_every_declared_class_is_producible() -> None:
    """Every member of ``CONVERGENCE_CLASSES`` must be reachable from inputs.

    The reachability half of the two-halves rule. Each of the four is
    constructed from a concrete input set and its class asserted — a member
    that no input can produce is a dead branch that a reader would trust.

    Building this set is what forced the discovery that MEDIUM is *not* reachable
    at n=3 once the corrected conflict gate is in place: the only n=3 candidate
    for MEDIUM is 2-of-3, and a lone dissenter is a third of the set, so the gate
    fires first. MEDIUM needs n=6 (4 up, 1 down, 1 flat).
    """
    produced = {
        _verdict(
            inflation_convergence_classifier(_three(headline=1, core=1, pce=1))
        ).classification,
        _verdict(inflation_convergence_classifier(_six(1, 1, 1, 1, -1, 0))).classification,
        _verdict(
            inflation_convergence_classifier(_three(headline=1, core=0, pce=0))
        ).classification,
        _verdict(
            inflation_convergence_classifier(_three(headline=1, core=-1, pce=1))
        ).classification,
    }
    assert produced == set(CONVERGENCE_CLASSES), (
        f"declared but unreachable: {set(CONVERGENCE_CLASSES) - produced}"
    )


def test_the_tuple_and_the_literal_agree() -> None:
    """The other half, asserted at module import — restated as a test so a
    regression names the pair rather than failing at import time."""
    from typing import get_args

    from macro_engine.models.inflation_convergence import ConvergenceClass

    assert set(get_args(ConvergenceClass)) == set(CONVERGENCE_CLASSES)


def test_the_verdict_schema_rejects_an_unknown_class() -> None:
    """``ConvergenceClass`` is a ``Literal``, so a typo cannot round-trip.

    A bare ``str`` field would accept ``"CONVERGED"`` and let it travel onward.
    """
    with pytest.raises(ValidationError):
        InflationConvergenceVerdict.model_validate(
            {
                "classification": "CONVERGED",
                "agreeing": 3,
                "opposing": 0,
                "flat": 0,
                "measures_used": 3,
                "frac_agreeing": 1.0,
                "attainable_fracs": [0.0, 1.0],
                "independent_families": 2,
                "family_names": ["bls_cpi", "bea_pce"],
                "bands_available": ["HIGH"],
                "base_rates": {},
            }
        )


# --------------------------------------------------------------------------
# 8. Input validation
# --------------------------------------------------------------------------


def test_an_off_vocabulary_direction_is_rejected() -> None:
    """``Direction`` is ``Literal[-1, 0, 1]``. ``2`` is not a reading.

    Without the ``Literal`` an out-of-vocabulary value would flow into the
    ``> 0`` count and be tallied as agreement — the D-029 enumerated-field
    defect.
    """
    with pytest.raises(ValidationError):
        InflationConvergenceInputs(
            headline_cpi_direction=2,  # type: ignore[arg-type]
            core_cpi_direction=1,
            core_pce_direction=1,
        )


def test_an_unknown_field_is_rejected() -> None:
    """``extra="forbid"`` — ``supercore_direction`` must not be silently typo'd in.

    Section 21.1 blocks supercore and the field is deliberately absent. A caller
    that passes it should be told, not silently ignored.
    """
    with pytest.raises(ValidationError):
        InflationConvergenceInputs(
            headline_cpi_direction=1,
            core_cpi_direction=1,
            core_pce_direction=1,
            supercore_direction=1,  # type: ignore[call-arg]
        )


def test_the_three_required_measures_cannot_be_omitted() -> None:
    """The specification's Phase 1 core is required; the extra three are not."""
    with pytest.raises(ValidationError):
        InflationConvergenceInputs(headline_cpi_direction=1, core_cpi_direction=1)  # type: ignore[call-arg]


def test_measures_used_matches_the_supplied_count() -> None:
    """The denominator is countable from the inputs, and it is published.

    D-046's "a count always travels with a denominator": ``frac_agreeing`` is
    meaningless without ``measures_used``, and ``measures_used`` is meaningless
    unless it equals the number of measures actually supplied.
    """
    three = _verdict(inflation_convergence_classifier(_three(headline=1, core=1, pce=1)))
    six = _verdict(inflation_convergence_classifier(_six(1, 1, 1, 1, 1, 1)))

    assert three.measures_used == 3
    assert six.measures_used == 6


# --------------------------------------------------------------------------
# 9. The ModelResult contract (§§22.8, 22.9)
# --------------------------------------------------------------------------


def test_value_is_a_structured_verdict_not_a_bare_label() -> None:
    """§22.9. A bare ``"HIGH"`` is uninterpretable without its denominator."""
    result = inflation_convergence_classifier(_three(headline=1, core=1, pce=1))

    assert isinstance(result.value, dict)
    for key in (
        "classification",
        "measures_used",
        "independent_families",
        "frac_agreeing",
        "base_rates",
    ):
        assert key in result.value, f"the verdict dropped {key!r}"
    assert as_str(result, key="classification") == "HIGH"
    assert as_int(result, key="measures_used") == 3


def test_confidence_comes_from_compute_confidence_not_a_literal() -> None:
    """§22.8: ``compute_confidence`` is the only producer.

    The specification hardcodes ``confidence=0.5 if n < 6 else 0.7``. Recomputing
    here from the same inputs must reproduce the value, which a literal would
    also do — so the test that actually distinguishes them is the *variation*
    test below. This one pins the call.
    """
    result = inflation_convergence_classifier(_three_measures_two_families())
    verdict = _verdict(result)

    expected = compute_confidence(
        ConfidenceInputs(
            is_heuristic_not_calibrated=True,
            source_independence_count=verdict.independent_families,
        )
    )
    assert result.confidence == pytest.approx(expected)


def test_confidence_varies_with_independent_families() -> None:
    """A literal confidence would be constant across these two calls.

    Two calls, **four measures each**, spanning two families and three families
    respectively. Any implementation with a hardcoded confidence — including the
    specification's own ``0.5 if n < 6 else 0.7``, which returns 0.5 for both
    because both are n<6 — returns the same number twice and fails here.

    The signal count is held constant precisely so that the *only* varying input
    is the one the confidence is supposed to depend on.
    """
    two = inflation_convergence_classifier(_four_measures_two_families())
    three = inflation_convergence_classifier(
        InflationConvergenceInputs(
            headline_cpi_direction=1,
            core_cpi_direction=1,
            core_pce_direction=1,
            trimmed_mean_direction=1,
        )
    )

    assert _verdict(two).measures_used == _verdict(three).measures_used == 4
    assert _verdict(two).independent_families == 2
    assert _verdict(three).independent_families == 3
    assert two.confidence < three.confidence


def test_inputs_used_names_every_supplied_measure() -> None:
    """The audit trail: which measures actually went in."""
    result = inflation_convergence_classifier(
        InflationConvergenceInputs(
            headline_cpi_direction=1,
            core_cpi_direction=1,
            core_pce_direction=1,
            median_cpi_direction=1,
        )
    )
    assert set(result.inputs_used) == {
        "headline_cpi_direction",
        "core_cpi_direction",
        "core_pce_direction",
        "median_cpi_direction",
    }
    assert "trimmed_mean_direction" not in result.inputs_used


def test_the_weak_statistic_caveat_always_travels() -> None:
    """Unconditional by design: the caveat is about the method, not the reading.

    A reader who sees a HIGH verdict and no caveat will treat a sign test as a
    magnitude estimate.
    """
    for inputs in (
        _three(headline=1, core=1, pce=1),
        _three(headline=-1, core=-1, pce=-1),
        _three(headline=0, core=0, pce=0),
        _six(1, 1, 1, -1, -1, -1),
    ):
        result = inflation_convergence_classifier(inputs)
        assert any("Sign test over month-over-month" in w for w in result.warnings)


def test_the_classifier_does_not_mutate_its_inputs() -> None:
    """D-046's no-mutation rule, checked on the caller's object.

    ``_tagged_measures`` builds fresh results and ``tag_evidence_source`` returns
    a copy, so the argument must come back byte-identical. A helper that tagged
    in place would relabel a shared result everywhere it is used.
    """
    inputs = _six(1, 1, 1, -1, -1, -1)
    before = inputs.model_dump()

    inflation_convergence_classifier(inputs)

    assert inputs.model_dump() == before


def test_direction_input_does_not_change_the_family_census() -> None:
    """Invariance: the census counts *sources*, not signs.

    Supplying the same six measures with every sign flipped must leave
    ``independent_families`` and ``family_names`` unchanged — the number of
    independent sources present is a property of which measures were supplied,
    not of what they said.
    """
    up = _verdict(inflation_convergence_classifier(_six(1, 1, 1, 1, 1, 1)))
    down = _verdict(inflation_convergence_classifier(_six(-1, -1, -1, -1, -1, -1)))

    assert up.independent_families == down.independent_families
    assert up.family_names == down.family_names
    assert up.measures_used == down.measures_used


def test_interpretation_reports_both_the_fraction_and_the_family_count() -> None:
    """The two numbers a reader needs, in the line they read first.

    A "3/3 measures agree" without the family count is the precise misreading
    Section 15.19-D exists to prevent.
    """
    result = inflation_convergence_classifier(_three(headline=1, core=1, pce=1))

    assert "3/3" in result.interpretation
    assert "2 independent" in result.interpretation


def test_the_result_carries_the_us_country_label() -> None:
    """Phase 0-4 is US-only (§22.3) — the label is not a generalization."""
    result = inflation_convergence_classifier(_three(headline=1, core=1, pce=1))
    assert result.country == "us"


def test_confidence_is_bounded_after_the_heuristic_penalty() -> None:
    """Sanity: the heuristic penalty is applied, so even three families do not
    reach the unpenalised base.

    ``compute_confidence`` starts from a base and subtracts 0.20 for
    ``is_heuristic_not_calibrated``; the independence bonus is capped, so the
    result must sit strictly below the base for any input this model accepts.
    """
    result = inflation_convergence_classifier(
        InflationConvergenceInputs(
            headline_cpi_direction=1,
            core_cpi_direction=1,
            core_pce_direction=1,
            trimmed_mean_direction=1,
        )
    )

    assert 0.0 <= result.confidence <= 1.0
    assert result.confidence < compute_confidence(ConfidenceInputs())


def test_the_base_confidence_constant_is_not_special_cased() -> None:
    """The specification's ``0.5 if n < 6 else 0.7`` must appear nowhere.

    An explicit guard against the literal being reintroduced. Every legal call
    here has n<6, so a faithful implementation of the specification's line would
    return exactly 0.5 for all four — the disjointness assertion catches that.
    """
    observed = {
        inflation_convergence_classifier(_three_measures_two_families()).confidence,
        inflation_convergence_classifier(_four_measures_two_families()).confidence,
        inflation_convergence_classifier(_six_measures_three_families()).confidence,
        inflation_convergence_classifier(_six(1, 1, 1, -1, -1, -1)).confidence,
    }
    assert observed.isdisjoint({0.5, 0.7}), (
        f"a confidence of exactly the specification's hardcoded value was "
        f"produced: {observed & {0.5, 0.7}}"
    )


# --------------------------------------------------------------------------
# 12. The base-state threshold is LEAF-DRIVEN, not a source literal (D-127)
# --------------------------------------------------------------------------


def test_the_base_state_threshold_is_read_from_config_not_a_literal() -> None:
    """The `0.75` in the source was silently coupled to a leaf that moves.

    §D-127: the base-state disclosure compares ``current_measure_count_high``
    (a config leaf) against a boundary that used to be a bare literal. The
    boundary is now ``settings.base_state_warning_threshold``, so re-measuring
    the base rate cannot move it out from under the comparison without the
    validator below refusing the pairing. This test asserts the leaf is what the
    code reads — a revert to a literal would make the two disagree here.
    """
    settings = get_settings().inflation.convergence
    declared = settings.base_state_warning_threshold
    rederived = settings.base_state_warning_threshold_value.value
    assert declared == pytest.approx(rederived)

    # The higher of the two base rates must sit ABOVE the bar, or the disclosure
    # could never fire — the state the config validator forbids.
    achieved = max(
        settings.measured_base_rates.three_measure_high,
        settings.measured_base_rates.six_measure_high,
    )
    assert declared < achieved, (
        "the base-state bar is at or above every producible HIGH base rate, so "
        "the disclosure could never fire"
    )


def test_the_base_state_disclosure_fires_today_because_the_leaf_is_below_the_rate() -> None:
    """A control: the shipped pairing produces the warning, at both n=3 and n=6.

    A threshold that is *declared* but never reached is dead config. Both
    measure-counts the model can produce carry a HIGH base rate (0.866 / 0.895)
    above the 0.75 bar, so a HIGH reading warns in both configurations.
    """
    for inputs in (
        _three(headline=1, core=1, pce=1),
        _six(1, 1, 1, 1, 1, 1),
    ):
        result = inflation_convergence_classifier(inputs)
        assert _verdict(result).classification == "HIGH"
        assert any("BASE STATE" in w for w in result.warnings), (
            "the base-state disclosure did not fire for a HIGH reading"
        )


def test_a_config_whose_threshold_kills_the_disclosure_is_refused() -> None:
    """The validator is load-bearing: it stops a config edit removing the warning.

    This is the defect the audit named — a *config* edit (raising the bar, or
    re-measuring the base rate down) could silently stop the disclosure firing.
    Now the model refuses to load such a pairing rather than degrading quietly.
    """
    import copy
    from pathlib import Path

    import yaml

    from macro_engine.config import InflationConvergenceSettings

    raw = yaml.safe_load(Path("config/settings.yaml").read_text(encoding="utf-8"))
    conv = copy.deepcopy(raw["inflation"]["convergence"])

    # Sanity: the shipped block loads.
    InflationConvergenceSettings.model_validate(conv)

    # A threshold at or above the highest base rate would make the warning dead.
    dead = copy.deepcopy(conv)
    dead["base_state_warning_threshold_value"]["value"] = 0.9
    with pytest.raises(ValidationError, match=r"could.{0,20}never fire"):
        InflationConvergenceSettings.model_validate(dead)

    # A share outside [0, 1] is not a share.
    out_of_range = copy.deepcopy(conv)
    out_of_range["base_state_warning_threshold_value"]["value"] = 1.5
    with pytest.raises(ValidationError, match=r"share in \[0, 1\]"):
        InflationConvergenceSettings.model_validate(out_of_range)


# --------------------------------------------------------------------------
# 13. `majority_direction` publishes the sign `agreeing` does not carry (D-128)
# --------------------------------------------------------------------------


def test_majority_direction_reports_the_side_the_majority_is_on() -> None:
    """`agreeing` is a count of the *majority*, which may be the DOWN side.

    §D-127: a parameter/field named `agreeing` that holds the down side's count
    reads as a directional claim it does not make (the D-034/36/37 latent trap).
    `majority_direction` makes the sign recoverable from the output.

    Rising month: 3 up, 0 down → +1. Disinflation month: 0 up, 3 down → -1.
    """
    rising = _verdict(inflation_convergence_classifier(_three(headline=1, core=1, pce=1)))
    falling = _verdict(inflation_convergence_classifier(_three(headline=-1, core=-1, pce=-1)))

    assert rising.agreeing == 3 and rising.opposing == 0
    assert rising.majority_direction == 1
    assert falling.agreeing == 3 and falling.opposing == 0
    assert falling.majority_direction == -1


def test_majority_direction_is_zero_when_no_side_holds_a_majority() -> None:
    """A tie — including the all-flat month — reports 0, the honest answer."""
    flat = _verdict(inflation_convergence_classifier(_three(headline=0, core=0, pce=0)))
    assert flat.agreeing == flat.opposing
    assert flat.majority_direction == 0

    # A genuine 1-up / 1-down / 1-flat split is also a tie on the directional
    # sides and must not claim a direction.
    mixed = _verdict(inflation_convergence_classifier(_three(headline=1, core=-1, pce=0)))
    assert mixed.agreeing == mixed.opposing == 1
    assert mixed.majority_direction == 0


def test_majority_direction_is_published_in_the_verdict() -> None:
    """The field must be part of the published contract, not an internal value."""
    value = inflation_convergence_classifier(_three(headline=1, core=1, pce=1)).value
    assert isinstance(value, dict)
    assert "majority_direction" in value
    assert value["majority_direction"] == 1


def test_the_disclosure_follows_a_moved_leaf(monkeypatch: pytest.MonkeyPatch) -> None:
    """Moving the leaf must move the disclosure — the only path that sees a literal.

    §D-127, and the counterpart of ``test_rebalancing_drift``'s lesson: a test
    that re-reads the *accessor* proves the accessor is live and says nothing
    about whether the FUNCTION consults it. A function hardcoding the shipped
    ``0.75`` passes that kind of test unchanged.

    Here the leaf is moved to a value the shipped literal does not equal, and the
    classifier is called. The disclosure must follow the leaf:

    * raised to ``0.95`` (above both base rates) it must go SILENT for a HIGH
      reading — the state the config validator forbids from shipping but which
      this test reaches by construction;
    * lowered to ``0.10`` it must FIRE as before.

    A revert to the literal ``0.75`` fails this test, which is what makes it the
    kill for the C-2a defect-reintroduction mutant.
    """
    import macro_engine.models.inflation_convergence as module
    from macro_engine.config import get_settings as _real_get_settings

    settings = _real_get_settings()
    convergence = settings.inflation.convergence

    def _patched(threshold: float) -> object:
        moved_conv = convergence.model_copy(
            update={
                "base_state_warning_threshold_value": (
                    convergence.base_state_warning_threshold_value.model_copy(
                        update={"value": threshold}
                    )
                )
            }
        )
        moved_inflation = settings.inflation.model_copy(update={"convergence": moved_conv})
        return settings.model_copy(update={"inflation": moved_inflation})

    high = _three(headline=1, core=1, pce=1)

    # (a) Bar ABOVE every base rate -> the disclosure cannot fire.
    monkeypatch.setattr(module, "get_settings", lambda: _patched(0.95))
    silenced = inflation_convergence_classifier(high)
    assert _verdict(silenced).classification == "HIGH"
    assert not any("BASE STATE" in w for w in silenced.warnings), (
        "the disclosure fired even though its bar sits above the base rate — "
        "the code is not reading the leaf"
    )

    # (b) Bar BELOW every base rate -> the disclosure fires.
    monkeypatch.setattr(module, "get_settings", lambda: _patched(0.10))
    loud = inflation_convergence_classifier(high)
    assert any("BASE STATE" in w for w in loud.warnings), (
        "the disclosure did not fire with a bar below the base rate — the code "
        "is not reading the leaf"
    )
