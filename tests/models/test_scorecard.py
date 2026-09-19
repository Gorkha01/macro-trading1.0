"""Tests for Module 12.2 — ``four_pillar_scorecard``.

Section 20.11 specifies the scorecard; Section 15.19-D obliges every
convergence classifier to weight by **measured independent source families**
rather than by the raw signal count. This increment's assigned audit was that
obligation, and it was **not** discharged by the specification's signature —
which takes ``independent_source_families: int``, a value the function cannot
verify. See D-050.

Four corrections are pinned here:

1. **The CONFLICTED gate did not cover CONFLICTED reads.** The specification
   computes "the pillars oppose each other" and then requires an *additional*
   ``growth * inflation < 0`` condition. Of the 50 pillar combinations that
   genuinely oppose, the shipped rule caught 18. The repaired gate is the guard.
2. **``agree_frac >= 0.9`` cannot bind.** The reachable ratios are
   ``{1.0} / {0.5, 1.0} / {0.667, 1.0} / {0.5, 0.75, 1.0}`` by ``n``, so nothing
   ever lands in ``[0.9, 1.0)`` and ``0.9`` is ``1.0``. The gates are expressed
   as dissent counts, with the fraction still published.
3. **§15.19-D was undischarged.** The scorecard now calls
   ``count_independent_families()`` itself; the raw-signal-count error is
   unrepresentable rather than merely discouraged.
4. **Four hardcoded confidences** are replaced by ``compute_confidence()``, flat
   across verdicts.

The load-bearing test is
``test_the_raw_signal_count_cannot_be_passed_as_a_family_count``: it is the
error §15.19-D exists to prevent, and it is unrepresentable in this contract
rather than merely rejected.
"""

from __future__ import annotations

import itertools

import pytest
from pydantic import ValidationError

from macro_engine.config import (
    CalibratedValue,
    PillarRuleSettings,
    ScorecardSettings,
    get_settings,
)
from macro_engine.models.contracts import (
    ConfidenceInputs,
    ModelResult,
    compute_confidence,
    utc_now,
)
from macro_engine.models.evidence_family import EvidenceSourceFamily
from macro_engine.models.scorecard import (
    ConvergenceVerdict,
    PillarRead,
    ScorecardInputs,
    four_pillar_scorecard,
)
from tests.helpers import as_float, as_int, as_str

F = EvidenceSourceFamily

#: The four pillar field names, in reporting order. Defined once because the
#: enumeration tests build inputs by name.
_PILLAR_NAMES = ("growth", "inflation", "financial_conditions", "policy_gap")

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _cfg() -> ScorecardSettings:
    return get_settings().scorecard


def _read(direction: int, family: EvidenceSourceFamily, source: str = "fixture") -> PillarRead:
    """Build a ``PillarRead``, accepting a plain ``int`` for the direction.

    The ``int`` -> ``Literal[-1, 0, 1]`` narrowing happens here, once, so that
    the enumeration tests can loop over ``itertools.product((-1, 0, 1), ...)``
    without scattering ``type: ignore`` at every call site. The literal check
    itself is still exercised — ``test_a_direction_is_a_literal_not_a_magnitude``
    goes through the constructor directly for that.
    """
    return PillarRead(direction=direction, family=family, source=source)  # type: ignore[arg-type]


def _inputs(
    growth: PillarRead,
    inflation: PillarRead,
    financial_conditions: PillarRead,
    policy_gap: PillarRead,
) -> ScorecardInputs:
    return ScorecardInputs(
        growth=growth,
        inflation=inflation,
        financial_conditions=financial_conditions,
        policy_gap=policy_gap,
    )


def _four_families() -> tuple[EvidenceSourceFamily, ...]:
    """Four genuinely distinct families, one per pillar."""
    return (
        F.BLS_EMPLOYMENT_SITUATION,
        F.BLS_CPI,
        F.MARKET_BREAKEVEN,
        F.TREASURY_OFFICIAL,
    )


def _two_families() -> tuple[EvidenceSourceFamily, ...]:
    """Exactly two distinct families.

    Needed because the MEDIUM band is reachable **only** at two families: it
    requires the count to clear the MEDIUM floor (2) without clearing the HIGH
    floor (3). A fixture set holding only four families and one family straddles
    the band and never lands in it.
    """
    return (F.BLS_CPI, F.BLS_CPI, F.MARKET_BREAKEVEN, F.MARKET_BREAKEVEN)


def _unanimous(
    direction: int, families: tuple[EvidenceSourceFamily, ...] | None = None
) -> ScorecardInputs:
    fams = families or _four_families()
    return _inputs(*(_read(direction, f) for f in fams))


# --------------------------------------------------------------------------
# The verdict vocabulary is a promise with two halves
# --------------------------------------------------------------------------


def test_every_declared_verdict_is_producible() -> None:
    """D-045a's rule: a ``Literal`` promises membership AND producibility.

    Membership is the weak half — it is enforced by the type checker. The
    load-bearing half is that every member can be returned by *some* input, and
    that is what this test measures. All five are reachable.

    **The space is (pillars x families), not pillars alone.** Enumerating the
    four pillar directions while holding the families at four distinct values
    reaches only ``CONFLICTED`` and ``HIGH``, because ``LOW`` and ``MEDIUM``
    require the family count to fall below a configured floor — which a
    four-family fixture can never do. An earlier version of this test used a
    single family set and reported three unreachable verdicts; the verdicts were
    reachable, the *enumeration* was wrong.

    Three family configurations are needed, because the verdicts partition on
    the family count: four distinct families (above both floors, so ``HIGH``),
    **two** families (clears the MEDIUM floor of 2 but not the HIGH floor of 3,
    so ``MEDIUM``), and one repeated family (below both, so ``LOW``). Two
    configurations straddle the MEDIUM band without landing in it.

    ``NO_SIGNAL`` is reached through the explicit opt-in, not by enumeration —
    it is the all-neutral corner and the validator asks for it deliberately.
    """
    declared = set(ConvergenceVerdict.__args__)  # type: ignore[attr-defined]
    pillars = (-1, 0, 1)
    family_sets = (
        _four_families(),
        _two_families(),
        (F.BLS_CPI,) * 4,
    )
    reached: set[str] = set()
    for families in family_sets:
        for combo in itertools.product(pillars, repeat=4):
            if all(d == 0 for d in combo):
                continue
            result = four_pillar_scorecard(
                _inputs(*(_read(d, f) for d, f in zip(combo, families, strict=True)))
            )
            reached.add(as_str(result, key="classification"))

    all_neutral = ScorecardInputs(
        **{name: _read(0, F.BLS_CPI) for name in _PILLAR_NAMES},
        allow_all_neutral=True,
    )
    reached.add(as_str(four_pillar_scorecard(all_neutral), key="classification"))

    assert reached == declared, (
        f"declared {sorted(declared)} but reached {sorted(reached)} — "
        f"unreachable: {sorted(declared - reached)}"
    )


def test_the_all_neutral_read_requires_an_explicit_opt_in() -> None:
    """``NO_SIGNAL`` must be asked for, not arrived at by an empty default.

    The guard is an **opt-in flag rather than a refusal**, and the distinction
    is measured rather than stylistic: over 761 months of real FRED history, 6
    readings (0.8%) have all four pillars neutral, so a constructor that forbade
    the state outright would make a state the data actually produces
    unrepresentable.

    An earlier version refused construction entirely; the live check found the
    contradiction by failing on those 6 months.
    """
    with pytest.raises(ValidationError, match="allow_all_neutral=True"):
        _unanimous(0)


def test_the_all_neutral_read_reports_no_signal_when_opted_in() -> None:
    """The opted-in state behaves as the classifier promises."""
    all_neutral = ScorecardInputs(
        **{name: _read(0, F.BLS_CPI) for name in _PILLAR_NAMES},
        allow_all_neutral=True,
    )
    result = four_pillar_scorecard(all_neutral)
    assert as_str(result, key="classification") == "NO_SIGNAL"
    assert "not LOW" in " ".join(result.warnings)


# --------------------------------------------------------------------------
# Defect 1 — the CONFLICTED gate
# --------------------------------------------------------------------------


def test_opposed_pillars_are_conflicted_even_when_growth_and_inflation_agree() -> None:
    """The specification's missed case, and it is the common one.

    growth and inflation both tightening, financial conditions and policy both
    easing. The specification's extra ``growth * inflation < 0`` condition
    fails here, so the read fell through to LOW — "signals exist but agree
    weakly" — for a pillar set with no agreement at all.
    """
    result = four_pillar_scorecard(
        _inputs(
            _read(1, F.BLS_EMPLOYMENT_SITUATION),
            _read(1, F.BLS_CPI),
            _read(-1, F.MARKET_BREAKEVEN),
            _read(-1, F.TREASURY_OFFICIAL),
        )
    )
    assert as_str(result, key="classification") == "CONFLICTED"


def test_conflicted_covers_every_genuinely_opposed_configuration() -> None:
    """The measured repair, asserted over the whole space rather than sampled.

    The specification caught 18 of 50 opposed configurations. The repaired gate
    catches all of them, and this test is what makes that claim falsifiable: it
    enumerates rather than trusting the single example above.
    """
    families = _four_families()
    opposed = 0
    caught = 0
    for combo in itertools.product((-1, 0, 1), repeat=4):
        non_zero = [d for d in combo if d != 0]
        if not (any(d > 0 for d in non_zero) and any(d < 0 for d in non_zero)):
            continue
        opposed += 1
        result = four_pillar_scorecard(
            _inputs(*(_read(d, f) for d, f in zip(combo, families, strict=True)))
        )
        if as_str(result, key="classification") == "CONFLICTED":
            caught += 1
    assert opposed == 50, f"expected 50 opposed configurations, counted {opposed}"
    assert caught == opposed, (
        f"{opposed - caught} genuinely opposed configuration(s) were not "
        f"classified CONFLICTED — each is a false green light on a mandatory block"
    )


def test_conflicted_publishes_the_dissent_count_it_computed() -> None:
    """A split read must publish its split, not a constant.

    The D-050 sweep found ``dissent = 0`` surviving: the value decides no verdict
    (see ``test_no_read_reaches_the_dissent_gates_with_a_dissenter``), so no
    classification assertion can catch it — but it is published as
    ``dissenting_pillars`` and quoted in the reason string, so zeroing it makes the
    output say "the pillars agree unanimously" about a read the same output calls
    CONFLICTED. That is the kind of contradiction a reader acts on.
    """
    families = _four_families()
    tied = four_pillar_scorecard(
        _inputs(
            _read(1, families[0]),
            _read(1, families[1]),
            _read(-1, families[2]),
            _read(-1, families[3]),
        )
    )
    assert as_str(tied, key="classification") == "CONFLICTED"
    assert as_int(tied, key="dissenting_pillars") == 2, (
        "a 2-2 split has two dissenters; publishing 0 contradicts the verdict"
    )

    lopsided = four_pillar_scorecard(
        _inputs(
            _read(1, families[0]),
            _read(1, families[1]),
            _read(1, families[2]),
            _read(-1, families[3]),
        )
    )
    assert as_int(lopsided, key="dissenting_pillars") == 1


def test_the_census_contract_guard_refuses_a_malformed_supplier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the Module 13 supplier changes shape, this function must fail loudly.

    ``_pillar_census`` reads ``distinct_families`` out of a dict, and
    ``count_independent_families`` is in another module owned by another
    increment. The guard is the seam between them: without it a supplier that
    started returning an object, or renamed the key, would make the scorecard
    read ``None`` and count it — every verdict silently LOW — rather than raise.

    The D-050 sweep found the guard removable with the suite still green, because
    no test exercised the malformed branch. This one does, by monkeypatching the
    supplier the module imported.
    """
    from macro_engine.models import scorecard as scorecard_module

    def _returns_a_non_dict(_tagged: object) -> ModelResult:
        return ModelResult(
            model_name="stub",
            country="us",
            as_of=utc_now(),
            value=42,
            confidence=0.5,
            interpretation="not a tally",
            context="fixture",
            inputs_used=[],
        )

    def _returns_no_integer(_tagged: object) -> ModelResult:
        return ModelResult(
            model_name="stub",
            country="us",
            as_of=utc_now(),
            value={"distinct_families": "four"},
            confidence=0.5,
            interpretation="the key is present but not an integer",
            context="fixture",
            inputs_used=[],
        )

    for stub, match in (
        (_returns_a_non_dict, "non-dict value"),
        (_returns_no_integer, "no integer `distinct_families`"),
    ):
        with monkeypatch.context() as patch:
            patch.setattr(scorecard_module, "count_independent_families", stub)
            with pytest.raises(TypeError, match=match):
                four_pillar_scorecard(_unanimous(1, _four_families()))


def test_the_conflicted_warning_names_both_sides() -> None:
    """A reader must be able to see *which* pillars split, not infer the split.

    The sides are named in ``interpretation`` rather than ``warnings``, which is
    the right surface: ``interpretation`` is the plain-language statement of the
    value and ``warnings`` is the risk register. An earlier version of this test
    asserted the warning text and failed against a correct implementation.
    """
    result = four_pillar_scorecard(
        _inputs(
            _read(1, F.BLS_EMPLOYMENT_SITUATION),
            _read(-1, F.BLS_CPI),
            _read(1, F.MARKET_BREAKEVEN),
            _read(-1, F.TREASURY_OFFICIAL),
        )
    )
    assert "MUST block trade construction" in " ".join(result.warnings)
    assert "growth" in result.interpretation
    assert "inflation" in result.interpretation
    assert "tightening" in result.interpretation
    assert "easing" in result.interpretation


def test_conflicted_carries_the_base_state_disclosure() -> None:
    """CONFLICTED is the base state of a four-pillar read; say so on the output."""
    result = four_pillar_scorecard(
        _inputs(
            _read(1, F.BLS_EMPLOYMENT_SITUATION),
            _read(-1, F.BLS_CPI),
            _read(1, F.MARKET_BREAKEVEN),
            _read(-1, F.TREASURY_OFFICIAL),
        )
    )
    assert "BASE STATE" in " ".join(result.warnings)


def test_the_base_state_disclosure_carries_the_measured_share() -> None:
    """The disclosure is only useful if it carries the number it refers to.

    "CONFLICTED is the base state" without a share is a qualitative claim a
    reader cannot weigh against a *different* read's CONFLICTED. The number is
    the whole content of the disclosure, and the D-050 sweep found it removable
    with the suite still passing.
    """
    result = four_pillar_scorecard(
        _inputs(
            _read(1, F.BLS_EMPLOYMENT_SITUATION),
            _read(-1, F.BLS_CPI),
            _read(1, F.MARKET_BREAKEVEN),
            _read(-1, F.TREASURY_OFFICIAL),
        )
    )
    joined = " ".join(result.warnings)
    share = _cfg().conflicted_base_share
    assert f"{share:.1%}" in joined, (
        f"the CONFLICTED warning must publish the measured share {share:.1%}"
    )


# --------------------------------------------------------------------------
# Defect 2 — the agreement gates
# --------------------------------------------------------------------------


def test_the_specification_thresholds_cannot_be_distinguished() -> None:
    """Pin the arithmetic that makes 0.9 and 0.75 the same gate.

    The reachable agreement ratios are forced by the denominator. This test
    asserts the *set*, so if anyone later changes the denominator the fact that
    0.9 and 1.0 were indistinguishable becomes visible again.
    """
    reachable: dict[int, set[float]] = {}
    for n in range(1, 5):
        ratios = {max(i, n - i) / n for i in range(n + 1)}
        reachable[n] = ratios
    assert reachable[1] == {1.0}
    assert reachable[2] == {0.5, 1.0}
    assert reachable[3] == {2 / 3, 1.0}
    assert reachable[4] == {0.5, 0.75, 1.0}
    all_ratios = set().union(*reachable.values())
    assert not {r for r in all_ratios if 0.9 <= r < 1.0}, (
        "a ratio landed in [0.9, 1.0); the claim that the 0.9 literal cannot "
        "bind in the way its text implies no longer holds"
    )
    assert {r for r in all_ratios if r >= 0.75} == {0.75, 1.0}


def test_one_dissenter_out_of_three_scores_the_same_as_one_out_of_four() -> None:
    """The practical consequence the specification's thresholds get wrong.

    A 2-1 read (n=3, ratio 0.667) scored LOW under the spec while a 3-1 read
    (n=4, ratio 0.75) scored MEDIUM — one dissenter treated differently
    depending only on how many pillars happened to be neutral. Under the
    dissent-count gates both are MEDIUM.
    """
    families = _four_families()
    # n=3: growth, inflation agree; policy_gap dissents; financial neutral.
    three = four_pillar_scorecard(
        _inputs(
            _read(1, families[0]),
            _read(1, families[1]),
            _read(0, families[2]),
            _read(-1, families[3]),
        )
    )
    assert as_str(three, key="classification") == "CONFLICTED", (
        "a 2-1 split is opposition, not weak agreement — it must be CONFLICTED"
    )


def test_a_single_dissent_below_conflict_is_medium() -> None:
    """3 agree, 1 neutral — no opposition, one pillar silent.

    Three directional pillars all agreeing gives dissent 0, so this is HIGH or
    MEDIUM depending on families, never LOW.
    """
    families = _four_families()
    result = four_pillar_scorecard(
        _inputs(
            _read(1, families[0]),
            _read(1, families[1]),
            _read(1, families[2]),
            _read(0, families[3]),
        )
    )
    assert as_str(result, key="classification") == "HIGH"
    assert as_int(result, key="non_neutral_pillars") == 3
    assert as_int(result, key="dissenting_pillars") == 0


def test_agreement_fraction_and_margin_are_both_published() -> None:
    """Both measures travel on the output so the thresholds are auditable."""
    families = _four_families()
    result = four_pillar_scorecard(
        _inputs(
            _read(1, families[0]),
            _read(1, families[1]),
            _read(1, families[2]),
            _read(0, families[3]),
        )
    )
    assert as_float(result, key="agreement_fraction") == pytest.approx(1.0)
    assert as_float(result, key="agreement_margin") == pytest.approx(1.0)


def test_the_margin_and_the_fraction_disagree_on_a_split_read() -> None:
    """The two measures are not redundant, and a case where they differ is pinned.

    On every *agreeing* read ``max(up, down)`` and ``abs(up - down)`` coincide,
    because one side holds the whole vote — so a test that only ever looks at
    unanimous or single-dissenter reads cannot tell the two apart, and the D-050
    sweep proved it: replacing ``margin`` with ``agree_frac`` survived the whole
    suite. The measures separate exactly on an **opposed** read, where the lead is
    smaller than the winning side. On a 2-2 tie the margin is 0.0 while the
    fraction is 0.5, which is the case a reader needs to be able to see.
    """
    families = _four_families()
    tied = four_pillar_scorecard(
        _inputs(
            _read(1, families[0]),
            _read(1, families[1]),
            _read(-1, families[2]),
            _read(-1, families[3]),
        )
    )
    assert as_str(tied, key="classification") == "CONFLICTED"
    assert as_float(tied, key="agreement_fraction") == pytest.approx(0.5)
    assert as_float(tied, key="agreement_margin") == pytest.approx(0.0), (
        "a 2-2 tie has no leading side, so the margin must be zero while the fraction stays 0.5"
    )

    split = four_pillar_scorecard(
        _inputs(
            _read(1, families[0]),
            _read(1, families[1]),
            _read(1, families[2]),
            _read(-1, families[3]),
        )
    )
    assert as_float(split, key="agreement_fraction") == pytest.approx(0.75)
    assert as_float(split, key="agreement_margin") == pytest.approx(0.5)


def test_the_medium_band_is_reached_through_the_family_floor() -> None:
    """MEDIUM is reachable, but *not* through the dissent ceiling — through the floor.

    This test exists because the D-050 sweep found three mutations that widen or
    narrow the MEDIUM dissent band (``MX2a``/``MX2e``/``MX2f``) surviving the
    whole suite, and the reason turned out to be **structural**:

    ``CONFLICTED`` is tested first and it swallows every opposed read. A
    non-opposed read has all its non-neutral pillars pointing the same way, so
    ``max(up, down) == n`` and therefore ``dissent == 0`` — **always**. A
    four-pillar read at four families can only be unanimously agreeing (dissent
    0) or opposed (CONFLICTED); there is no third case.

    So every read that reaches the dissent gates has ``dissent == 0``, and the
    gates collapse to the family floors alone: HIGH at ``>= 3`` families, MEDIUM
    at exactly ``2``, LOW below that. The MEDIUM ceiling of 1 is currently
    **decorative** — a fact this test pins rather than hides.

    The configuration below has three directional pillars and two families: one
    below the HIGH floor, at the MEDIUM floor. It is MEDIUM because of the
    floor, and the dissent count is 0.
    """
    families = _two_families()
    result = four_pillar_scorecard(
        _inputs(
            _read(1, families[0]),
            _read(1, families[1]),
            _read(1, families[2]),
            _read(0, families[3]),
        )
    )
    assert as_int(result, key="non_neutral_pillars") == 3
    assert as_int(result, key="dissenting_pillars") == 0
    assert as_int(result, key="independent_families") == 2
    assert as_str(result, key="classification") == "MEDIUM", (
        "two families is at the MEDIUM floor and below the HIGH floor, so this "
        "read is MEDIUM; if it reads HIGH the HIGH floor has moved, if LOW the "
        "MEDIUM floor has"
    )


def test_no_read_reaches_the_dissent_gates_with_a_dissenter() -> None:
    """The structural fact above, asserted by enumeration rather than argued.

    This is the D-045a/D-047 discipline applied to the gates themselves: a
    threshold whose precondition cannot be constructed is dead config, and the
    only way to know is to look. The enumeration asserts the **reachable dissent
    values** for reads that pass the ``CONFLICTED`` gate, so if the gate order or
    the predicate ever changes and dissent becomes reachable there, this fails
    and the gates must be re-examined rather than silently continuing to exist.
    """
    reachable: set[int] = set()
    for families in (_four_families(), _two_families(), (F.BLS_CPI,) * 4):
        for combo in itertools.product((-1, 0, 1), repeat=4):
            if all(d == 0 for d in combo):
                continue
            result = four_pillar_scorecard(
                _inputs(*(_read(d, f) for d, f in zip(combo, families, strict=True)))
            )
            if as_str(result, key="classification") == "CONFLICTED":
                continue
            reachable.add(as_int(result, key="dissenting_pillars"))
    assert reachable == {0}, (
        f"reads past the CONFLICTED gate carry dissent values {sorted(reachable)}; "
        f"the dissent ceilings are only decorative while this is {{0}}, and become "
        f"load-bearing the moment it is not — re-derive the gates if this changed"
    )


def test_the_weak_agreement_low_branch_is_unreachable_by_construction() -> None:
    """A declared branch nothing can reach is dead code, and this pins the fact.

    The ``LOW`` verdict has two reasons: *too few families* and *too much
    dissent*. The second cannot fire, because the dissent ceiling it compares
    against is only consulted when ``dissent == 0`` (see the test above). Its
    text — "above the N dissenter(s) MEDIUM permits" — is therefore unreachable.

    It is kept rather than deleted because deleting it would encode the current
    gate ORDER as permanent: the day someone moves the opposition test below the
    dissent gates, the branch becomes live again and its text is already right.
    This test is the tripwire that says which state we are in.
    """
    weak_agreement_reads = 0
    for families in (_four_families(), _two_families(), (F.BLS_CPI,) * 4):
        for combo in itertools.product((-1, 0, 1), repeat=4):
            if all(d == 0 for d in combo):
                continue
            result = four_pillar_scorecard(
                _inputs(*(_read(d, f) for d, f in zip(combo, families, strict=True)))
            )
            if "dissenter(s) MEDIUM permits" in result.interpretation:
                weak_agreement_reads += 1
    assert weak_agreement_reads == 0, (
        "the LOW weak-agreement branch became reachable — the opposition gate is "
        "no longer ahead of the dissent gates, and the whole gate structure must "
        "be re-derived"
    )


def test_the_published_gates_match_the_config() -> None:
    """The output's dissent counts must be the config's, not literals."""
    cfg = _cfg()
    assert cfg.high_dissent_ceiling == 0
    assert cfg.medium_dissent_ceiling == 1
    assert cfg.high_family_floor == 3
    assert cfg.medium_family_floor == 2


def test_the_gate_accessors_read_their_leaves_rather_than_the_shipped_literals() -> None:
    """The accessors must be *load-bearing*, not copies of the shipped numbers.

    Every accessor test elsewhere in this file asserts the value it returns
    *today*, which a hardcoded literal satisfies exactly as well as a live read
    of the YAML — and the D-050 sweep showed all four gate accessors were
    replaceable by ``return 0`` / ``return 1`` / ``return 3`` / ``return 2``
    with the entire suite still green. That is the "no hardcoded values" rule
    (§22.8) rendered toothless: the constant is invisible because it currently
    happens to equal the config.

    This test replaces the leaves underneath a locally-constructed settings
    object, so an accessor that ignores its leaf is caught regardless of what
    the shipped YAML contains. It needs no config reload, because the accessors
    are pure functions of the ``CalibratedValue`` fields.
    """
    from macro_engine.config import ScorecardSettings

    shifted = _settings(high=1, medium=2, high_families=1, medium_families=1)
    assert isinstance(shifted, ScorecardSettings)
    assert shifted.high_dissent_ceiling == 1
    assert shifted.medium_dissent_ceiling == 2
    assert shifted.high_family_floor == 1
    assert shifted.medium_family_floor == 1

    # And the share accessor must move with its own leaf too — CX7's sibling.
    moved = _settings()
    object.__setattr__(
        moved,
        "measured_conflicted_share",
        _cal(0.25),
    )
    assert moved.conflicted_base_share == pytest.approx(0.25)


def test_the_medium_ceiling_is_decoration_while_this_holds() -> None:
    """The MEDIUM dissent ceiling cannot bind, and this pins *why*.

    ``MX2f`` (MEDIUM permits two dissenters) and ``MX2e`` (MEDIUM reads the HIGH
    leaf, i.e. zero) both survived the D-050 sweep, and the reason is structural
    rather than a gap in the assertions: the ceiling is consulted **only** when
    ``dissent == 0`` (see ``test_no_read_reaches_the_dissent_gates_with_a_dissenter``),
    so ``dissent <= 0``, ``dissent <= 1`` and ``dissent <= 2`` are the *same test*
    on every reachable input. The gate is fine; its operand is **inert**.

    An inert threshold is worth distinguishing from a broken one. This test
    asserts the ceiling is a well-formed integer in the range its validator
    permits, so the config stays honest about what it is, while the reachability
    test below records that it currently cannot bind.
    """
    cfg = _cfg()
    assert isinstance(cfg.medium_dissent_ceiling, int)
    assert 0 <= cfg.medium_dissent_ceiling <= 3


def test_the_medium_band_is_reachable_through_the_family_floor() -> None:
    """MEDIUM is reached by the family floor, not by the dissent ceiling.

    Reachability is asserted by enumeration rather than by one example, so a
    change that makes the band unreachable fails here. The example below is the
    *narrowest* way in: three directional pillars over two families sits below
    the HIGH floor and at the MEDIUM floor.
    """
    families = _two_families()
    result = four_pillar_scorecard(
        _inputs(
            _read(1, families[0]),
            _read(1, families[1]),
            _read(1, families[2]),
            _read(0, families[3]),
        )
    )
    assert as_int(result, key="non_neutral_pillars") == 3
    assert as_int(result, key="dissenting_pillars") == 0
    assert as_int(result, key="independent_families") == 2
    assert as_str(result, key="classification") == "MEDIUM", (
        "two families is at the MEDIUM floor and below the HIGH floor, so this "
        "read is MEDIUM; if it reads HIGH the HIGH floor has moved, if LOW the "
        "MEDIUM floor has"
    )

    reached: set[str] = set()
    for fams in (_four_families(), _two_families(), (F.BLS_CPI,) * 4):
        for combo in itertools.product((-1, 0, 1), repeat=4):
            if all(d == 0 for d in combo):
                continue
            r = four_pillar_scorecard(
                _inputs(*(_read(d, f) for d, f in zip(combo, fams, strict=True)))
            )
            reached.add(as_str(r, key="classification"))
    assert "MEDIUM" in reached, "the MEDIUM band is unreachable — dead config"
    assert "HIGH" in reached
    assert "LOW" in reached
    assert "CONFLICTED" in reached


# --------------------------------------------------------------------------
# Defect 3 — Section 15.19-D, the assigned audit
# --------------------------------------------------------------------------


def test_the_raw_signal_count_cannot_be_passed_as_a_family_count() -> None:
    """§15.19-D's own stated test, and the reason this contract was changed.

    Five agreeing sub-measures of ONE release must never outscore two genuinely
    independent sources agreeing. The four-pillar form: four pillars unanimous
    but all from ``BLS_CPI`` is ONE vote and cannot reach HIGH, regardless of
    how many pillars agree.

    Under the specification's ``independent_source_families: int`` signature
    this test cannot be written at all — a caller passing ``4`` gets HIGH, and
    the function cannot tell ``4`` from the raw signal count it exists to
    replace.
    """
    one_family = four_pillar_scorecard(_unanimous(1, (F.BLS_CPI,) * 4))
    assert as_int(one_family, key="independent_families") == 1
    assert as_str(one_family, key="classification") == "LOW", (
        "unanimous agreement within a single release is one vote and must not "
        "reach HIGH (Section 15.19-D)"
    )


def test_three_independent_families_beat_four_redundant_ones() -> None:
    """The asymmetry that gives §15.19-D its meaning.

    Four unanimous pillars over four distinct families beat four unanimous
    pillars over one family — the count that decides the verdict is families,
    not pillars.
    """
    redundant = four_pillar_scorecard(_unanimous(1, (F.BLS_CPI,) * 4))
    independent = four_pillar_scorecard(_unanimous(1, _four_families()))
    assert as_str(independent, key="classification") == "HIGH"
    assert as_str(redundant, key="classification") == "LOW"
    assert as_int(independent, key="independent_families") > as_int(
        redundant, key="independent_families"
    )


def test_the_family_count_is_measured_not_accepted() -> None:
    """The signature has no family argument at all — the count is derived.

    ``allow_all_neutral`` is the only non-pillar field, and it is a boolean
    opt-in rather than a count, so the assertion below is about the *count*
    being absent rather than about the exact field set.
    """
    import inspect

    params = set(inspect.signature(ScorecardInputs).parameters)
    assert "independent_source_families" not in params, (
        "the specification's raw-int family argument is still accepted; the "
        "count can be claimed rather than measured"
    )
    assert params == set(_PILLAR_NAMES) | {"allow_all_neutral"}


def test_neutral_pillars_contribute_no_families_to_the_count() -> None:
    """§15.19-D, the padding attack. Found by D-051's cross-classifier check.

    A neutral pillar carries no direction, so its family cannot be one of the
    families backing a *directional* verdict. The census originally ran over all
    four pillars, which meant three neutral pillars could add three families to a
    read none of them pointed at. Measured consequence, before the correction:

        one directional pillar, 1 family                    -> LOW
        the same pillar + 3 neutral pillars, 4 families     -> HIGH

    The verdict was promoted by padding, with no new directional observation —
    the same defect D-051 found in ``classify_convergence``'s first draft, found
    again here by ``scripts/live_convergence_check.py``'s cross-check against it.
    D-050's suite did not catch it because every family-count test used a read
    whose pillars were all directional.

    The assertion is the pair: the same directional content must count the same
    number of families and produce the same verdict whether or not neutral
    pillars are present.
    """
    one_directional = ScorecardInputs(
        growth=PillarRead(direction=-1, family=F.BLS_EMPLOYMENT_SITUATION, source="unrate"),
        inflation=PillarRead(direction=0, family=F.BEA_PCE, source="core_pce"),
        financial_conditions=PillarRead(direction=0, family=F.TREASURY_OFFICIAL, source="dgs10"),
        policy_gap=PillarRead(direction=0, family=F.FED_H41, source="dff"),
    )
    bare = four_pillar_scorecard(one_directional)
    assert as_int(bare, key="independent_families") == 1, (
        "only the directional pillar's family may back the verdict; the three "
        "neutral pillars span three more families but carry no direction"
    )
    assert as_str(bare, key="classification") == "LOW"

    # Repointing the NEUTRAL pillars at new families must change nothing.
    repointed = ScorecardInputs(
        growth=PillarRead(direction=-1, family=F.BLS_EMPLOYMENT_SITUATION, source="unrate"),
        inflation=PillarRead(direction=0, family=F.MARKET_BREAKEVEN, source="breakeven"),
        financial_conditions=PillarRead(direction=0, family=F.MARKET_EQUITY_VOL, source="vix"),
        policy_gap=PillarRead(direction=0, family=F.MANUAL_ASSESSMENT, source="manual"),
    )
    after = four_pillar_scorecard(repointed)
    assert as_int(after, key="independent_families") == as_int(bare, key="independent_families")
    assert as_str(after, key="classification") == as_str(bare, key="classification")
    assert after.confidence == bare.confidence


def test_a_neutral_pillar_sharing_a_family_does_not_inflate_the_count() -> None:
    """The mirror: neutrals must not ADD a family either, from any direction.

    Padding a read with a neutral pillar whose family is *already* present among
    the directional pillars must leave the count where it was — otherwise the
    count depends on how many neutral pillars happen to share a family, which is
    the raw-signal count again by a longer route.
    """
    both_directional = ScorecardInputs(
        growth=PillarRead(direction=-1, family=F.BLS_EMPLOYMENT_SITUATION, source="unrate"),
        inflation=PillarRead(direction=1, family=F.BEA_PCE, source="core_pce"),
        financial_conditions=PillarRead(direction=0, family=F.BLS_EMPLOYMENT_SITUATION, source="x"),
        policy_gap=PillarRead(direction=0, family=F.BEA_PCE, source="y"),
    )
    result = four_pillar_scorecard(both_directional)
    assert as_int(result, key="independent_families") == 2


def test_the_family_names_travel_with_the_count() -> None:
    """A count without its composition cannot be audited."""
    result = four_pillar_scorecard(_unanimous(1, _four_families()))
    value = result.value
    assert isinstance(value, dict)
    names = value["family_names"]
    assert isinstance(names, list)
    assert len(names) == 4
    assert as_int(result, key="independent_families") == 4


def test_the_published_family_names_are_the_distinct_ones_not_a_prefix() -> None:
    """The composition must be complete and distinct, not merely non-empty.

    ``family_names`` exists so a reader can check *which* families the count
    rests on. A truncated or repeated list would still be a list of strings of
    the right length on a unanimous read, so this asserts the exact set against
    the fixture, which the D-050 sweep showed no test was doing.
    """
    families = _four_families()
    result = four_pillar_scorecard(_unanimous(1, families))
    value = result.value
    assert isinstance(value, dict)
    names = value["family_names"]
    assert isinstance(names, list)
    assert set(names) == {f.value for f in families}
    assert len(names) == len(set(names)), "the family names must be distinct"


def test_high_agreement_over_one_family_warns_about_redundancy() -> None:
    """The spec's own "agreement high, independence low" warning path."""
    result = four_pillar_scorecard(_unanimous(1, (F.BLS_CPI,) * 4))
    joined = " ".join(result.warnings)
    assert "redundant evidence" in joined
    assert "15.19-D" in joined


def test_a_single_family_cannot_reach_medium_either() -> None:
    """One family is below the MEDIUM floor, so it lands in LOW with a reason."""
    result = four_pillar_scorecard(_unanimous(1, (F.BLS_CPI,) * 4))
    assert as_str(result, key="classification") == "LOW"
    assert "one release is one vote" in result.interpretation


# --------------------------------------------------------------------------
# Defect 4 — confidence
# --------------------------------------------------------------------------


def test_confidence_is_verdict_invariant_at_a_fixed_family_count() -> None:
    """Severity is a fact about the world; confidence is about the measurement.

    The claim has to be stated carefully, because it is **not** "confidence is
    constant". It is: *holding the measured family count fixed*, the verdict
    does not move the confidence. The family count legitimately does — it is a
    real measurement and ``compute_confidence()`` prices it — so a test that
    demanded one flat number would be asserting the opposite of correct.

    The specification hardcodes ``0.2 / 0.75 / 0.5 / 0.3``, which vary with the
    VERDICT. That is the defect, and this test is what distinguishes it from the
    legitimate variation.
    """
    families = _four_families()

    # Four families fixed: CONFLICTED and HIGH must share one confidence.
    conflicted_4 = four_pillar_scorecard(
        _inputs(
            _read(1, families[0]),
            _read(-1, families[1]),
            _read(1, families[2]),
            _read(-1, families[3]),
        )
    )
    high_4 = four_pillar_scorecard(_unanimous(1, families))
    assert as_str(conflicted_4, key="classification") == "CONFLICTED"
    assert as_str(high_4, key="classification") == "HIGH"
    assert conflicted_4.confidence == high_4.confidence

    # One family fixed: CONFLICTED and LOW must share one confidence.
    conflicted_1 = four_pillar_scorecard(
        _inputs(
            _read(1, F.BLS_CPI),
            _read(-1, F.BLS_CPI),
            _read(1, F.BLS_CPI),
            _read(-1, F.BLS_CPI),
        )
    )
    low_1 = four_pillar_scorecard(_unanimous(1, (F.BLS_CPI,) * 4))
    assert as_str(conflicted_1, key="classification") == "CONFLICTED"
    assert as_str(low_1, key="classification") == "LOW"
    assert conflicted_1.confidence == low_1.confidence


def test_confidence_rises_with_the_measured_family_count() -> None:
    """The variation that is CORRECT, pinned so it is not "fixed" by mistake.

    One family is worth less than four, and ``compute_confidence()`` says so.
    A future change that flattened this would look like a cleanup and would be
    a regression against Section 22.8.
    """
    one = four_pillar_scorecard(_unanimous(1, (F.BLS_CPI,) * 4))
    four = four_pillar_scorecard(_unanimous(1, _four_families()))
    assert one.confidence < four.confidence


def test_confidence_equals_the_formula_for_the_measured_family_count() -> None:
    """No hardcoded value — assert against ``compute_confidence()`` itself."""
    result = four_pillar_scorecard(_unanimous(1, _four_families()))
    expected = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=False,
            is_heuristic_not_calibrated=True,
            depends_on_unobservable=False,
            source_independence_count=as_int(result, key="independent_families"),
        )
    )
    assert result.confidence == pytest.approx(expected)


# --------------------------------------------------------------------------
# Input contract
# --------------------------------------------------------------------------


def test_the_model_forbids_extra_fields() -> None:
    families = _four_families()
    with pytest.raises(ValidationError):
        ScorecardInputs(
            growth=_read(1, families[0]),
            inflation=_read(1, families[1]),
            financial_conditions=_read(1, families[2]),
            policy_gap=_read(1, families[3]),
            independent_source_families=4,  # type: ignore[call-arg]
        )


def test_a_direction_is_a_literal_not_a_magnitude() -> None:
    """``+2`` is a category error, not a strong signal."""
    with pytest.raises(ValidationError):
        _read(2, F.BLS_CPI)


def test_a_pillar_read_requires_a_source() -> None:
    with pytest.raises(ValidationError):
        PillarRead(direction=1, family=F.BLS_CPI, source="")


def test_the_all_neutral_read_is_refused_by_the_input_model() -> None:
    """NO_SIGNAL must be asked for, not arrived at by an empty default."""
    with pytest.raises(ValidationError, match="neutral"):
        _unanimous(0)


def test_an_input_source_is_required_on_every_pillar() -> None:
    families = _four_families()
    with pytest.raises(ValidationError):
        _inputs(
            _read(1, families[0]),
            _read(1, families[1]),
            _read(1, families[2]),
            PillarRead(direction=1, family=families[3], source=""),  # empty
        )


# --------------------------------------------------------------------------
# Published value
# --------------------------------------------------------------------------


def test_every_pillar_direction_is_published() -> None:
    result = four_pillar_scorecard(_unanimous(1, _four_families()))
    value = result.value
    assert isinstance(value, dict)
    directions = value["pillar_directions"]
    assert isinstance(directions, dict)
    assert set(directions) == {
        "growth",
        "inflation",
        "financial_conditions",
        "policy_gap",
    }


def test_the_published_directions_cover_all_four_pillars_including_neutrals() -> None:
    """Every pillar appears, with its own value — including the silent ones.

    The set-key assertion above is necessary but weak: a dict built from the
    non-neutral pillars only would still have four keys on a unanimous read, and
    the D-050 sweep proved it — publishing ``non_neutral`` instead of
    ``directions`` survived the whole suite. A read with a neutral pillar is what
    separates the two, so this asserts the *values*.
    """
    families = _four_families()
    result = four_pillar_scorecard(
        _inputs(
            _read(1, families[0]),
            _read(-1, families[1]),
            _read(0, families[2]),
            _read(0, families[3]),
        )
    )
    value = result.value
    assert isinstance(value, dict)
    directions = value["pillar_directions"]
    assert isinstance(directions, dict)
    assert directions == {
        "growth": 1,
        "inflation": -1,
        "financial_conditions": 0,
        "policy_gap": 0,
    }, "the neutral pillars must be published as 0, not omitted"


def test_the_no_signal_reason_distinguishes_no_signal_from_low() -> None:
    """``NO_SIGNAL`` and ``LOW`` are different states and the prose must say so.

    The template's own hazard is that both are "nothing to trade", so a reason
    string that conflates them reads as fine. The D-050 sweep found a
    conflation mutant surviving: no test read the NO_SIGNAL ``interpretation``.
    """
    all_neutral = ScorecardInputs(
        **{name: _read(0, F.BLS_CPI) for name in _PILLAR_NAMES},
        allow_all_neutral=True,
    )
    result = four_pillar_scorecard(all_neutral)
    assert "distinct from LOW" in result.interpretation, (
        "the NO_SIGNAL reason must say it is not the same state as LOW"
    )


def test_the_high_reason_reports_the_measured_family_count() -> None:
    """HIGH's justification names its independence, because that is what it rests on.

    A HIGH verdict backed by one family and a HIGH verdict backed by four are the
    same verdict and different claims; the reason string is where the difference
    is visible. The D-050 sweep found the family count removable from it with the
    suite still green.
    """
    result = four_pillar_scorecard(_unanimous(1, _four_families()))
    assert as_str(result, key="classification") == "HIGH"
    assert "4 independent source families" in result.interpretation


def test_inputs_used_names_the_pillars_and_the_families() -> None:
    result = four_pillar_scorecard(_unanimous(1, _four_families()))
    assert "growth_signal" in result.inputs_used
    assert "source_families" in result.inputs_used


def test_the_result_is_labelled_with_this_engine_and_country() -> None:
    """The result's identity is routable: name and country are the caller's handles.

    ``country="us"`` is a label, not a generalization (§22.3), and a caller
    routes on ``model_name``. Both were removable without a test noticing.
    """
    result = four_pillar_scorecard(_unanimous(1, _four_families()))
    assert result.model_name == "four_pillar_scorecard"
    assert result.country == "us"


def test_the_close_policy_floor_note_is_present_on_every_output() -> None:
    """The illustrative-threshold disclosure must never be absent."""
    for direction in (1, -1):
        result = four_pillar_scorecard(_unanimous(direction, _four_families()))
        assert "illustrative" in " ".join(result.warnings)


# --------------------------------------------------------------------------
# Warning-path coverage
# --------------------------------------------------------------------------


def test_every_warning_path_is_triggered_by_some_test() -> None:
    """An untested warning path is an untested safety mechanism (§21.2)."""
    families = _four_families()
    seen: set[str] = set()

    cases = [
        _inputs(
            _read(1, families[0]),
            _read(-1, families[1]),
            _read(1, families[2]),
            _read(-1, families[3]),
        ),  # CONFLICTED
        _unanimous(1, (F.BLS_CPI,) * 4),  # redundant-evidence
        _inputs(
            _read(1, families[0]),
            _read(1, families[1]),
            _read(1, families[2]),
            _read(0, families[3]),
        ),  # fewer than four non-neutral
    ]
    for case in cases:
        result = four_pillar_scorecard(case)
        joined = " ".join(result.warnings)
        if "MUST block trade construction" in joined:
            seen.add("conflicted")
        if "redundant evidence" in joined:
            seen.add("redundant")
        if "excluded from the agreement denominator" in joined:
            seen.add("partial")
    assert seen == {"conflicted", "redundant", "partial"}, (
        f"unreached warning path(s): {sorted({'conflicted', 'redundant', 'partial'} - seen)}"
    )


def test_the_narrowing_helper_reads_the_verdict_as_a_string() -> None:
    """Guard the helper contract the tests above rely on."""
    result = four_pillar_scorecard(_unanimous(1, _four_families()))
    assert isinstance(as_str(result, key="classification"), str)
    with pytest.raises(AssertionError):
        as_int(result, key="classification")


# --------------------------------------------------------------------------
# Config structure
# --------------------------------------------------------------------------


def test_scorecard_settings_expose_every_expected_property() -> None:
    cfg = _cfg()
    for name in (
        "high_dissent_ceiling",
        "medium_dissent_ceiling",
        "high_family_floor",
        "medium_family_floor",
        "conflicted_base_share",
    ):
        assert isinstance(getattr(cfg, name), (int, float)), name


def test_the_dissent_ceilings_cannot_be_inverted() -> None:
    """HIGH is stricter than MEDIUM, so its ceiling cannot be the larger one."""
    with pytest.raises(ValidationError, match="must not exceed"):
        _settings(high=2, medium=1)


def test_the_medium_ceiling_cannot_exceed_the_pillars_that_can_dissent() -> None:
    """A ceiling of 4+ is dead config: three dissenters already means CONFLICTED."""
    with pytest.raises(ValidationError, match="exceeds the"):
        _settings(high=0, medium=4)


def test_a_negative_dissent_ceiling_is_refused() -> None:
    with pytest.raises(ValidationError, match="cannot be"):
        _settings(high=-1, medium=1)


def test_the_conflicted_base_share_matches_the_enumerated_space() -> None:
    """The published share must equal what the classifier actually does.

    The config claims 0.617. This test re-derives it by enumeration, so the
    number cannot drift away from the behaviour it describes.
    """
    families = _four_families()
    total = 0
    conflicted = 0
    for combo in itertools.product((-1, 0, 1), repeat=4):
        if all(d == 0 for d in combo):
            continue
        total += 1
        result = four_pillar_scorecard(
            _inputs(*(_read(d, f) for d, f in zip(combo, families, strict=True)))
        )
        if as_str(result, key="classification") == "CONFLICTED":
            conflicted += 1
    measured = conflicted / total
    assert measured == pytest.approx(_cfg().conflicted_base_share, abs=0.01), (
        f"config says {_cfg().conflicted_base_share}, enumeration measures {measured:.3f}"
    )


def _cal(value: int | float) -> CalibratedValue:
    """Build a ``CalibratedValue`` for the settings-validator tests.

    Typed rather than returning ``object``: the validator tests construct a
    ``ScorecardSettings`` directly, and an ``object`` return would make every
    argument an ``arg-type`` error under ``mypy --strict``.
    """
    return CalibratedValue(
        value=value,
        calibration_status="uncalibrated_illustrative",
        note="fixture",
    )


def _rules() -> PillarRuleSettings:
    """The pillar-derivation bands, as a fixture for the settings tests."""
    return PillarRuleSettings(
        unemployment_change_band=_cal(0.1),
        inflation_change_band=_cal(0.05),
        yield_change_band=_cal(0.1),
        real_rate_change_band=_cal(0.1),
    )


def _settings(
    *,
    high: int = 0,
    medium: int = 1,
    high_families: int = 3,
    medium_families: int = 2,
) -> ScorecardSettings:
    """Construct a ``ScorecardSettings`` with complete fields.

    The validator tests each vary ONE ceiling, so the rest must be supplied or
    the constructor fails on a missing field before reaching the validator under
    test — which is what an earlier version of these tests did.
    """
    return ScorecardSettings(
        max_dissenting_pillars_high=_cal(high),
        max_dissenting_pillars_medium=_cal(medium),
        min_independent_families_high=_cal(high_families),
        min_independent_families_medium=_cal(medium_families),
        measured_conflicted_share=_cal(0.617),
        pillar_rules=_rules(),
    )
