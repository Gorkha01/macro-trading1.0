"""Tests for Module 12 — ``classify_convergence``.

Section 22.10 (Finding #10) specifies the **general** convergence classifier:
an arbitrary list of already-produced ``ModelResult``s in, one verdict out. It
is distinct from ``inflation_convergence_classifier`` (Module 5.3, D-047 — a
fixed inflation sub-measure set) and from ``four_pillar_scorecard`` (Module
12.2, D-050 — four *named* pillars). This one takes a list, because that is
what ``build_us_macro_thesis``'s Q7 actually has.

**Six specification defects are pinned here**, in three groups.

The function did not run at all
-------------------------------
1. **``count_independent_families()`` returns a ``ModelResult``; the spec
   compares it to an ``int``.** ``independent_family_count >= 3`` raises
   ``TypeError`` on every call reaching the family gate. The specification's two
   halves were written against different versions of the supplier and were never
   executed together.
2. **``directions[0]`` is still the reference**, which is the exact bug Finding
   #10's prose claimed to remove. A neutral first signal collapses ``agree_count``
   to zero and the read to ``LOW`` regardless of the other signals; and the
   verdict changes under permutation in 132 of 1800 multisets.

The arithmetic did not express the prose
-----------------------------------------
3. **The denominator counts neutrals.** Section 22.10 divides by the non-neutral
   count; Section 12 divides by the whole list. Same signals, different verdict:
   ``[+1, +1, 0, 0]`` is unanimous by one reading and a coin flip by the other.
4. **``NO_SIGNAL`` is unreachable**, though the vocabulary declares it
   first-class and Section 22.10 returns it. All-neutral fell through to ``LOW``.
5. **``LOW`` conflates three situations.** A unanimous read with a low family
   count landed in ``LOW`` alongside genuinely weak agreement, so the section's
   own "high agreement, low independence" warning could never fire.

The composition defect D-050 found, again
------------------------------------------
6. **The thresholds behind ``CONFLICTED`` are inert.** Past that gate every
   non-neutral signal points the same way, so the reachable dissent count is
   always zero and the reachable agreement fraction is always ``1.0`` — making
   ``>= 0.8`` and ``>= 0.6`` the same test. Kept as gates with tripwires and a
   written proof, rather than deleted, so the gate *order* is not frozen.

The load-bearing tests are
``test_the_specification_version_raises_on_a_modelresult_comparison`` (the
function did not run), ``test_the_verdict_is_independent_of_signal_order`` (the
``directions[0]`` bug), and
``test_no_read_reaches_the_dissent_gate_with_a_dissenter`` (the inert
thresholds).
"""

from __future__ import annotations

import itertools

import pytest
from pydantic import ValidationError

from macro_engine.config import CalibratedValue, ConvergenceSettings, get_settings
from macro_engine.models.contracts import (
    ConfidenceInputs,
    ModelResult,
    compute_confidence,
    utc_now,
)
from macro_engine.models.convergence import (
    ConvergenceInputs,
    ConvergenceVerdict,
    classify_convergence,
)
from macro_engine.models.evidence_family import EvidenceSourceFamily
from tests.helpers import as_float, as_int, as_str

F = EvidenceSourceFamily

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _cfg() -> ConvergenceSettings:
    return get_settings().convergence


def _signal(
    value: object,
    family: EvidenceSourceFamily | None = F.BLS_CPI,
    name: str = "fixture",
) -> ModelResult:
    """Build a tagged signal. ``value`` is deliberately ``object`` so the
    non-numeric cases (dict, str, bool) can be constructed without a cast."""
    return ModelResult(
        model_name=name,
        country="us",
        as_of=utc_now(),
        value=value,  # type: ignore[arg-type]
        confidence=0.5,
        interpretation="fixture signal",
        context="fixture",
        inputs_used=["fixture"],
        source_family=family,
    )


def _classify(signals: list[ModelResult]) -> ModelResult:
    return classify_convergence(ConvergenceInputs(signals=signals))


def _verdict(signals: list[ModelResult]) -> str:
    return as_str(_classify(signals), key="classification")


def _four_families() -> tuple[EvidenceSourceFamily, ...]:
    """Four genuinely distinct families — one per signal."""
    return (
        F.BLS_EMPLOYMENT_SITUATION,
        F.BLS_CPI,
        F.MARKET_BREAKEVEN,
        F.TREASURY_OFFICIAL,
    )


def _unanimous(families: tuple[EvidenceSourceFamily, ...]) -> list[ModelResult]:
    """A ``+1`` read for each supplied family."""
    return [_signal(1, fam, name=f"s{i}") for i, fam in enumerate(families)]


def _settings(
    *,
    high: int = 0,
    medium: int = 1,
    high_families: int = 3,
    medium_families: int = 2,
) -> ConvergenceSettings:
    """A settings object built from EXPLICIT leaves.

    Exists so the accessor tests can assert against a **perturbed** object —
    a test asserting the shipped value cannot distinguish a live config read
    from a hardcoded copy of that same number (D-050's accessor blind spot).
    """
    return ConvergenceSettings(
        max_dissenting_signals_high=CalibratedValue(
            value=high, calibration_status="uncalibrated_illustrative"
        ),
        max_dissenting_signals_medium=CalibratedValue(
            value=medium, calibration_status="uncalibrated_illustrative"
        ),
        min_independent_families_high=CalibratedValue(
            value=high_families, calibration_status="uncalibrated_illustrative"
        ),
        min_independent_families_medium=CalibratedValue(
            value=medium_families, calibration_status="uncalibrated_illustrative"
        ),
        measured_conflicted_share=CalibratedValue(
            value=0.6173, calibration_status="uncalibrated_illustrative"
        ),
    )


# --------------------------------------------------------------------------
# Contract: the input model
# --------------------------------------------------------------------------


def test_the_signal_list_cannot_be_empty() -> None:
    """An empty list is refused at the contract, not classified.

    ``count_independent_families`` tolerates an empty list (D-046, for
    incrementally-built signal lists), but a *classifier* over nothing has no
    verdict to return. ``NO_SIGNAL`` means "signals exist and all are neutral",
    which is a different claim from "no signals were supplied".
    """
    with pytest.raises(ValidationError, match="at least 1 item"):
        ConvergenceInputs(signals=[])


def test_an_unknown_field_is_refused() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ConvergenceInputs(signals=[_signal(1)], confidence_override=0.99)  # type: ignore[call-arg]


def test_a_single_signal_is_allowed() -> None:
    """One signal is a degenerate but legal read.

    It is unanimous by construction — it cannot disagree with anything — but it
    spans exactly one family, so independence caps it at ``LOW``. That is the
    correct answer and the interesting one: "unanimous" and "well-evidenced"
    are not the same claim, and a one-signal read is the limiting case.
    """
    assert _verdict([_signal(1, F.BLS_CPI)]) == "LOW"


# --------------------------------------------------------------------------
# Defect 1 — the specification's version raises on a ModelResult comparison
# --------------------------------------------------------------------------


def test_the_specification_version_raises_on_a_modelresult_comparison() -> None:
    """Pin the defect: the specification's own arithmetic is not runnable.

    ``count_independent_families()`` returns a ``ModelResult`` (D-046's
    correction — a bare ``int`` cannot carry the untagged denominator). The
    specification's classifier assigns that result and then writes
    ``independent_family_count >= 3``, which is a ``ModelResult``-vs-``int``
    comparison.

    This test asserts the *language* behaviour the defect depends on, so it
    fails if Python ever made such a comparison total — at which point the
    specification's version would silently run with the wrong value instead of
    raising, which is worse.
    """
    from macro_engine.models.evidence import count_independent_families

    census = count_independent_families([_signal(1, F.BLS_CPI)])
    assert isinstance(census, ModelResult), (
        "count_independent_families must return a ModelResult for the "
        "specification's defect to be what D-051 says it is."
    )
    with pytest.raises(TypeError, match="'>=' not supported"):
        _ = census >= 3  # type: ignore[operator]


def test_the_family_count_is_measured_and_published() -> None:
    """The classifier measures the count rather than accepting it (Defect 1's repair)."""
    result = _classify(_unanimous(_four_families()))
    assert as_int(result, key="independent_families") == 4


def test_the_census_contract_is_guarded_against_a_non_dict_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A supplier that breaks its contract raises a NAMED error, not ``AttributeError``.

    Found by mutation M5.4, which deleted the ``isinstance(census_value, dict)``
    guard and **survived** — because in normal operation the supplier always
    returns a dict, so no ordinary test reaches the guard. The guard is a
    contract check on a module boundary, and the only way to test it is to make
    the supplier misbehave deliberately.

    The distinction matters: without the guard the failure is
    ``AttributeError: 'list' object has no attribute 'get'`` raised from inside
    the classifier's own body, which reads as a bug in *this* function. With the
    guard it is a ``TypeError`` naming the supplier and the key required, which
    reads as what it is.
    """
    import macro_engine.models.convergence as conv

    def fake_census(_: object) -> ModelResult:
        return ModelResult(
            model_name="count_independent_families",
            country="us",
            as_of=utc_now(),
            value=["not", "a", "dict"],
            confidence=0.5,
            interpretation="stub",
            context="stub",
            inputs_used=[],
        )

    monkeypatch.setattr(conv, "count_independent_families", fake_census)
    with pytest.raises(TypeError, match="non-dict value"):
        conv.classify_convergence(
            conv.ConvergenceInputs(signals=[_signal(1, F.BLS_CPI), _signal(1, F.BEA_PCE)])
        )


def test_the_census_contract_is_guarded_against_a_non_integer_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A census whose ``distinct_families`` is missing raises a NAMED error.

    Found by mutation M5.5, which deleted the ``isinstance(distinct, int)`` guard
    and survived for the same reason as M5.4: the supplier normally supplies it.
    Without the guard the value flows into ``distinct >= settings.high_family_floor``
    and raises exactly the ``TypeError: '>=' not supported between instances of
    'NoneType' and 'int'`` that Defect 1 is about — so a regression in the
    supplier would be reported as a recurrence of the specification defect it was
    written to repair.
    """
    import macro_engine.models.convergence as conv

    def fake_census(_: object) -> ModelResult:
        return ModelResult(
            model_name="count_independent_families",
            country="us",
            as_of=utc_now(),
            value={"families": [], "tagged": 2, "untagged": 0, "duplicate_results": 0},
            confidence=0.5,
            interpretation="stub",
            context="stub",
            inputs_used=[],
        )

    monkeypatch.setattr(conv, "count_independent_families", fake_census)
    with pytest.raises(TypeError, match="no integer `distinct_families`"):
        conv.classify_convergence(
            conv.ConvergenceInputs(signals=[_signal(1, F.BLS_CPI), _signal(1, F.BEA_PCE)])
        )


def test_the_exclusion_set_survives_an_empty_census(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The disclosure holds even when the census reports no families at all.

    Written for mutation M5.7, which changed the fallback in
    ``set(census_value.get("families") or [])`` to ``or ["stub"]``. The mutant
    turned out to be **provably inert** (a member added to the *subtrahend* of a
    set difference can only remove families, and ``"stub"`` is never a family
    name), so this test does not kill it — the mutant is recorded as a disclosed
    inert survivor in ``scripts/mutation_convergence.py`` with that proof.

    The test is kept because the property it asserts is real and was untested:
    when the census reports an empty ``families`` list, every neutral signal's
    family must still appear in ``families_excluded_as_neutral``. That is the
    degenerate end of the exclusion logic, and it is the end where a future
    rewrite of the fallback is most likely to start silently dropping the
    disclosure.
    """
    import macro_engine.models.convergence as conv

    def empty_census(_: object) -> ModelResult:
        return ModelResult(
            model_name="count_independent_families",
            country="us",
            as_of=utc_now(),
            value={
                "distinct_families": 2,
                "families": [],
                "tagged": 2,
                "untagged": 0,
                "duplicate_results": 0,
            },
            confidence=0.5,
            interpretation="stub",
            context="stub",
            inputs_used=[],
        )

    monkeypatch.setattr(conv, "count_independent_families", empty_census)
    result = _classify(
        [
            _signal(1, F.BLS_CPI),
            _signal(1, F.BEA_PCE),
            _signal(0, F.TREASURY_OFFICIAL),
        ]
    )
    value = result.value
    assert isinstance(value, dict)
    assert value["independent_families"] == 2
    assert value["families_excluded_as_neutral"] == ["treasury_official"], (
        "when the census reports no families, every neutral signal's family is "
        "excluded from the independence count and must still be disclosed"
    )
    assert any("appear ONLY among neutral signals" in w for w in result.warnings)


# --------------------------------------------------------------------------
# Defect 2 — the directions[0] reference
# --------------------------------------------------------------------------


def test_a_neutral_first_signal_does_not_collapse_the_read() -> None:
    """``[0, +1, +1, +1]`` must not read ``LOW``.

    With ``directions[0] == 0`` the specification's
    ``d == directions[0] and d != 0`` is false for every element, so
    ``agree_count`` is 0, ``frac`` is 0.0 and the verdict is ``LOW``. Three
    unanimous tightening signals report *weak agreement* because the first one
    happened to be neutral.
    """
    signals = [
        _signal(0, F.BLS_EMPLOYMENT_SITUATION),
        _signal(1, F.BLS_CPI),
        _signal(1, F.MARKET_BREAKEVEN),
        _signal(1, F.TREASURY_OFFICIAL),
    ]
    assert _verdict(signals) == "HIGH"


def test_the_verdict_is_independent_of_signal_order() -> None:
    """Enumerate the permutation group: no multiset may change verdict.

    The specification's version is order-dependent in **132 of 1800**
    (multiset, family-count) cases at ``n <= 5``. This asserts zero for the
    repaired form over ``n <= 4``, which is the range the specification's own
    call site uses.
    """
    families = _four_families()
    for n in (2, 3, 4):
        for combo in itertools.product((-1, 0, 1), repeat=n):
            sigs = [_signal(v, families[i % 4]) for i, v in enumerate(combo)]
            verdicts = {
                _verdict([sigs[j] for j in perm]) for perm in itertools.permutations(range(n))
            }
            assert len(verdicts) == 1, (
                f"signals {combo} give {verdicts} under permutation — the "
                "classifier is reading the call site's list order, not the "
                "evidence"
            )


def test_a_non_numeric_value_reads_neutral_rather_than_raising() -> None:
    """A dict/str/bool signal is neutral, not an error.

    ``four_pillar_scorecard`` returns a dict, so a pipeline that chains the two
    legitimately feeds this classifier a non-numeric value. Treating it as
    directional would invent a signal; raising would break the chain. Neutral
    is the only honest option.
    """
    for value in ({"classification": "HIGH"}, "HIGH", True, None):
        assert _verdict([_signal(value, F.BLS_CPI)]) == "NO_SIGNAL"


# --------------------------------------------------------------------------
# Defect 3 — the denominator
# --------------------------------------------------------------------------


def test_the_denominator_is_the_non_neutral_count_not_the_whole_list() -> None:
    """``[+1, +1, 0, 0]`` is UNANIMOUS among what reads at all.

    The specification's Section 12 divides by ``len(directions)`` (4 here) and
    gets 0.5; Section 22.10 divides by the non-neutral count (2) and gets 1.0.
    The two sections disagree about the same input and only one can be right —
    a neutral signal is not evidence for either direction, so including it in
    the denominator dilutes agreement in proportion to the input's neutrality.
    """
    signals = [
        _signal(1, F.BLS_CPI),
        _signal(1, F.BEA_PCE),
        _signal(0, F.TREASURY_OFFICIAL),
        _signal(0, F.MARKET_BREAKEVEN),
    ]
    result = _classify(signals)
    assert as_float(result, key="agreement_fraction") == 1.0
    assert as_int(result, key="non_neutral_signals") == 2
    assert as_int(result, key="total_signals") == 4
    # Unanimous among everything that reads, but only TWO families back the
    # directional read (the other two signals are neutral and contribute
    # nothing). Agreement and independence are separate gates, and this read
    # passes the first while being capped by the second.
    assert as_int(result, key="independent_families") == 2
    assert as_str(result, key="classification") == "MEDIUM"


def test_neutral_signals_are_excluded_from_the_denominator_by_warning() -> None:
    """The exclusion is disclosed, not silent."""
    signals = [_signal(1, F.BLS_CPI), _signal(1, F.BEA_PCE), _signal(0, F.TREASURY_OFFICIAL)]
    result = _classify(signals)
    assert any("read neutral and are excluded" in w for w in result.warnings)


# --------------------------------------------------------------------------
# Defect 4 — NO_SIGNAL
# --------------------------------------------------------------------------


def test_an_all_neutral_read_returns_no_signal_not_low() -> None:
    """``NO_SIGNAL`` is declared first-class and must be producible.

    The specification's general classifier has no all-neutral branch: zero
    opposition, ``agree_count == 0``, ``frac == 0.0``, verdict ``LOW``. That
    reports "we see something, weakly" when the truth is "we measured nothing".
    """
    signals = [_signal(0, fam) for fam in _four_families()]
    assert _verdict(signals) == "NO_SIGNAL"


def test_no_signal_is_distinct_from_low() -> None:
    """The two verdicts must come from different conditions.

    ``NO_SIGNAL`` = nothing directional exists. ``LOW`` = directional signals
    exist and the evidence for them is weak or redundant. Collapsing them
    reports weak agreement where no agreement was measured.
    """
    all_neutral = [_signal(0, F.BLS_CPI), _signal(0, F.BLS_CPI)]
    weak = _unanimous((F.BLS_CPI, F.BLS_CPI))
    assert _verdict(all_neutral) == "NO_SIGNAL"
    assert _verdict(weak) == "LOW"


def test_the_no_signal_warning_explains_why_it_is_not_low() -> None:
    signals = [_signal(0, fam) for fam in _four_families()]
    result = _classify(signals)
    assert any("This is NOT LOW" in w for w in result.warnings)


# --------------------------------------------------------------------------
# Defect 5 — LOW conflation
# --------------------------------------------------------------------------


def test_a_unanimous_read_with_one_family_is_not_reported_as_weak_agreement() -> None:
    """``LOW`` must not mean "unanimous but redundant".

    The specification checks the family floors *inside* the ``frac`` branches,
    so a unanimous single-family read falls to the ``else`` and is reported
    ``LOW`` — the same verdict as a genuine weak-agreement read. The section's
    own warning ("agreement is high but source independence is low") therefore
    had no branch to fire from.
    """
    signals = _unanimous((F.BLS_CPI, F.BLS_CPI, F.BLS_CPI, F.BLS_CPI))
    result = _classify(signals)
    assert as_str(result, key="classification") == "LOW"
    assert as_float(result, key="agreement_fraction") == 1.0
    assert any("redundant evidence" in w for w in result.warnings)


def test_the_redundancy_warning_and_the_weak_agreement_warning_are_separate_branches() -> None:
    """Two different reasons for ``LOW`` must produce two different warnings."""
    redundant = _classify(_unanimous((F.BLS_CPI, F.BLS_CPI)))
    one_family_warnings = [w for w in redundant.warnings if "redundant evidence" in w]
    weak_warnings = [w for w in redundant.warnings if "above the" in w]
    assert one_family_warnings, "the redundancy branch must fire for a single-family read"
    assert not weak_warnings, "the weak-agreement branch must NOT fire for a unanimous read"


# --------------------------------------------------------------------------
# Defect 6 — the inert thresholds
# --------------------------------------------------------------------------


def test_no_read_reaches_the_dissent_gate_with_a_dissenter() -> None:
    """Enumerate the space: past ``CONFLICTED`` the dissenter count is always 0.

    ``CONFLICTED`` is tested first and consumes every opposed read, so a read
    reaching the agreement gates has all non-neutral signals pointing the same
    way — ``max(up, down) == n``, hence ``dissent == 0``. The MEDIUM ceiling of
    ``1`` therefore cannot bind: ``dissent <= 0`` and ``dissent <= 1`` are the
    same predicate, exactly as in D-050.

    This is a **tripwire**, not a demonstration of a bug. It fails the moment
    the gate order changes in a way that makes dissent non-zero, which is the
    signal to re-derive the ceilings rather than discover they were decorative.
    """
    reachable: set[int] = set()
    for n in (2, 3, 4, 5):
        for combo in itertools.product((-1, 0, 1), repeat=n):
            non_neutral = [d for d in combo if d != 0]
            if not non_neutral:
                continue
            up = sum(1 for d in non_neutral if d > 0)
            down = sum(1 for d in non_neutral if d < 0)
            if up > 0 and down > 0:
                continue  # consumed by CONFLICTED
            reachable.add(len(non_neutral) - max(up, down))
    assert reachable == {0}, (
        f"dissenter counts reachable past the CONFLICTED gate are {sorted(reachable)}; "
        "the configured MEDIUM ceiling of 1 is now live and the gates need "
        "re-deriving (D-050's composition defect has changed shape)"
    )


def test_the_medium_ceiling_is_decoration_while_the_gate_order_holds() -> None:
    """The ceiling is a well-formed count even though it cannot bind."""
    ceiling = _cfg().medium_dissent_ceiling
    assert isinstance(ceiling, int)
    assert ceiling >= 0


def test_the_agreement_fraction_is_always_one_past_the_gate() -> None:
    """Why ``>= 0.8`` and ``>= 0.6`` are the same test in the specification."""
    reachable: set[float] = set()
    for n in (1, 2, 3, 4):
        for combo in itertools.product((-1, 0, 1), repeat=n):
            non_neutral = [d for d in combo if d != 0]
            if not non_neutral:
                continue
            up = sum(1 for d in non_neutral if d > 0)
            down = sum(1 for d in non_neutral if d < 0)
            if up > 0 and down > 0:
                continue
            reachable.add(round(max(up, down) / len(non_neutral), 4))
    assert reachable == {1.0}, (
        f"reachable agreement fractions past the gate are {sorted(reachable)}; "
        "if this is no longer {1.0} the two thresholds are genuinely distinct "
        "and the config no longer needs the dissent-count form"
    )


def test_the_high_gate_reads_both_halves_of_its_predicate() -> None:
    """A gate is ``dissent <= ceiling`` **and** ``distinct >= floor``.

    Found by mutation M3.5, which deleted the dissent half of the HIGH gate
    (``elif distinct >= settings.high_family_floor:``) and **survived every
    test**. The mutant is masked by two independent facts, and both had to be
    established before an honest test could be written:

    * Past ``CONFLICTED`` the dissent count is always ``0`` (see
      ``test_no_read_reaches_the_dissent_gate_with_a_dissenter``), so removing
      ``dissent <= 0`` cannot change which verdict is produced; and
    * the removed half is evaluated **first**, so deleting it does not change
      the warning branch either — the same warning fires either way.

    The mutation is behaviourally invisible for reachable input. A first attempt
    to pin it perturbed the ceiling negative so the half would bind, and the
    **config validator refused** (``cannot be negative — a dissenter count is a
    count``). That refusal is correct, and it is itself the proof the mutation is
    inert: the only configurations that would let the half bind are unreachable
    by construction.

    So the half is pinned the only way it can be — directly, by asserting the
    shipped predicate text mentions both quantities — plus the enumeration that
    makes the claim precise. This is a structural assertion standing in for a
    behavioural one, and the docstring says so rather than pretending otherwise
    (contrast M4.1, whose inertness is *total* and is left as a disclosed
    survivor instead).
    """
    import inspect

    import macro_engine.models.convergence as conv

    source = inspect.getsource(conv.classify_convergence)
    assert "dissent <= settings.high_dissent_ceiling" in source, (
        "the HIGH gate must consult the dissent ceiling; mutation M3.5 deleted "
        "this half and survived because the composition makes it unobservable "
        "from the outside (see the docstring)"
    )
    assert "distinct >= settings.high_family_floor" in source

    # The masking facts, asserted rather than assumed.
    families = _four_families()
    unanimous = _unanimous(families)
    assert _verdict(unanimous) == "HIGH"
    assert as_int(_classify(unanimous), key="dissenting_signals") == 0

    # And the reason text proves the gate consumed both quantities at run time.
    assert "backed by 4 independent source families" in _classify(unanimous).interpretation


def test_the_redundancy_branch_is_reached_and_is_distinct_from_weak_agreement() -> None:
    """``LOW`` has two reasons and they are separate branches.

    Found by mutation M3.7, which made the redundancy branch unreachable
    (``elif distinct < settings.medium_family_floor and n > 99:``) and
    **survived**.

    Why it survived is worth recording, because it is the D-050 lesson again.
    The mutant does not change any *verdict*: a unanimous single-family read
    fails the redundancy test and then fails the weak-agreement test too, so it
    reaches the final ``else`` and still returns ``LOW``. It changes only the
    **reason**, and therefore which warning is emitted — but the existing
    ``test_the_redundancy_warning_and_the_weak_agreement_warning_are_separate_branches``
    already asserts that warning, because the *warning helper* tests the same
    ``distinct < medium_family_floor`` condition independently of the verdict
    ladder. The two code paths had drifted into redundancy, and the assertion was
    silently testing the helper rather than the branch.

    What pins the branch is the **reason text it builds**, which only the ladder
    produces. The interpretation is asserted, not the warning.
    """
    families = _four_families()
    # Unanimous, four families: reaches the HIGH gate, so the redundancy branch
    # is demonstrably not a catch-all for unanimous reads.
    unanimous_wide = _unanimous(families)
    assert _verdict(unanimous_wide) == "HIGH"

    # Unanimous, ONE family: the redundancy branch's reason.
    redundant_signals = _unanimous((F.BLS_CPI, F.BLS_CPI, F.BLS_CPI, F.BLS_CPI))
    assert _verdict(redundant_signals) == "LOW"
    redundant = _classify(redundant_signals)
    assert "span only 1 source family" in redundant.interpretation, (
        "the redundancy branch's own reason must appear in the interpretation — "
        "if this is missing the branch has been folded into the weak-agreement "
        "branch (mutation M3.7)"
    )
    assert "agreement is weak" not in redundant.interpretation

    # The weak-agreement branch is genuinely reachable too: it needs dissent to
    # pass the MEDIUM ceiling without opposition, which the composition makes
    # impossible -- so it is pinned by the tripwire below rather than by input.
    # What CAN be asserted is that the two reasons are different strings, which
    # is what makes the branch worth keeping rather than folding away.
    assert "span only" in redundant.interpretation


# --------------------------------------------------------------------------
# Verdict reachability — a Literal is a promise with two halves
# --------------------------------------------------------------------------


def test_every_declared_verdict_is_producible() -> None:
    """Every member of the ``Literal`` must be reachable (the D-045a rule)."""
    from typing import get_args

    produced = {
        _verdict(_unanimous(_four_families())),  # HIGH
        _verdict([_signal(1, F.BLS_CPI)]),  # also HIGH — see below
        _verdict(_unanimous((F.BLS_CPI, F.BLS_CPI))),  # LOW (one family)
        _verdict([_signal(1, F.BLS_CPI), _signal(-1, F.BEA_PCE)]),  # CONFLICTED
        _verdict([_signal(0, F.BLS_CPI)]),  # NO_SIGNAL
        _verdict(  # MEDIUM: two families, unanimous
            [_signal(1, F.BLS_CPI), _signal(1, F.BEA_PCE)]
        ),
    }
    declared = set(get_args(ConvergenceVerdict))
    assert produced == declared, f"produced {produced}, declared {declared}"


def test_the_verdict_space_matches_the_thesis_layer_enum() -> None:
    """The vocabulary is declared once per layer and must not fork.

    ``models/`` is the lower layer and cannot import ``thesis_layer``, so the
    ``Literal`` is necessarily declared twice. A forked vocabulary is the D-046
    defect (a second definition satisfying an ``==`` check), so the two are
    asserted to agree member-for-member.
    """
    from typing import get_args

    from macro_engine.thesis_layer.schemas import ConvergenceClassification

    assert set(get_args(ConvergenceVerdict)) == {m.value for m in ConvergenceClassification}


# --------------------------------------------------------------------------
# The verdict gates, branch by branch
# --------------------------------------------------------------------------


def test_conflicted_requires_opposition_not_just_disagreement() -> None:
    """``CONFLICTED`` means both directions are present, in any arrangement."""
    for combo in itertools.permutations((1, 1, -1, -1)):
        sigs = [_signal(v, fam) for v, fam in zip(combo, _four_families(), strict=True)]
        assert _verdict(sigs) == "CONFLICTED"


def test_a_single_opposed_signal_is_conflicted() -> None:
    """One dissenter in the *other* direction is opposition, however lopsided."""
    sigs = [
        _signal(1, F.BLS_CPI),
        _signal(1, F.BEA_PCE),
        _signal(1, F.TREASURY_OFFICIAL),
        _signal(-1, F.MARKET_BREAKEVEN),
    ]
    assert _verdict(sigs) == "CONFLICTED"


def test_conflicted_publishes_the_directions_it_read() -> None:
    """The per-signal directions are published, in input order."""
    sigs = [_signal(1, F.BLS_CPI), _signal(-1, F.BEA_PCE), _signal(0, F.TREASURY_OFFICIAL)]
    result = _classify(sigs)
    value = result.value
    assert isinstance(value, dict)
    assert value["directions"] == [1, -1, 0]


def test_medium_requires_two_families() -> None:
    """A unanimous two-family read is MEDIUM; one family is LOW."""
    assert _verdict([_signal(1, F.BLS_CPI), _signal(1, F.BEA_PCE)]) == "MEDIUM"
    assert _verdict([_signal(1, F.BLS_CPI), _signal(1, F.BLS_CPI)]) == "LOW"


def test_high_requires_three_families() -> None:
    """Three families reach HIGH; two only reach MEDIUM."""
    three = _unanimous((F.BLS_CPI, F.BEA_PCE, F.TREASURY_OFFICIAL))
    assert _verdict(three) == "HIGH"
    assert _verdict(_unanimous((F.BLS_CPI, F.BEA_PCE))) == "MEDIUM"


def test_the_margin_and_the_fraction_disagree_on_a_split_read() -> None:
    """``agreement_fraction`` and ``agreement_margin`` are different quantities.

    They coincide on every *agreeing* read (because past the ``CONFLICTED`` gate
    the fraction is always 1.0), and that is exactly why a fixture built from
    agreeing reads cannot tell them apart. On a 2-2 split the fraction is 0.5
    and the margin is 0.0: the fraction says "half the signals are on the
    winning side", the margin says "there is no winning side".
    """
    sigs = [
        _signal(1, F.BLS_CPI),
        _signal(1, F.BEA_PCE),
        _signal(-1, F.TREASURY_OFFICIAL),
        _signal(-1, F.MARKET_BREAKEVEN),
    ]
    result = _classify(sigs)
    assert as_float(result, key="agreement_fraction") == 0.5
    assert as_float(result, key="agreement_margin") == 0.0


# --------------------------------------------------------------------------
# Section 15.19-D — the confidence wiring
# --------------------------------------------------------------------------


def test_the_family_count_is_what_moves_confidence() -> None:
    """Four signals from four families out-score four from one family.

    This is §15.19-D's entire purpose: five agreeing sub-measures of one
    release are one vote, and the confidence must reflect that.
    """
    four_families = _classify(_unanimous(_four_families()))
    one_family = _classify(_unanimous((F.BLS_CPI, F.BLS_CPI, F.BLS_CPI, F.BLS_CPI)))
    assert four_families.confidence > one_family.confidence


def test_neutral_signals_cannot_promote_a_read_by_padding() -> None:
    """DEFECT 7 — found by this test, which was written to assert the opposite.

    A neutral signal carries no direction, so its family cannot be one of the
    families backing a *directional* verdict. The first draft of the module (and
    the obvious reading of §15.19-D, which says to census "its inputs") counted
    all signals, and the consequence was directly exploitable: appending three
    neutral signals from three new families promoted a two-family ``MEDIUM``
    read to ``HIGH`` and lifted confidence 0.60 → 0.75, with no new directional
    observation.

    That is redundant-evidence false confidence — §15.19-D's own failure mode —
    reached through the repair. The census now runs over the directional subset.
    """
    two_directional = [_signal(1, F.BLS_CPI), _signal(1, F.BEA_PCE)]
    padded = [
        *two_directional,
        _signal(0, F.TREASURY_OFFICIAL),
        _signal(0, F.MARKET_BREAKEVEN),
        _signal(0, F.MARKET_EQUITY_VOL),
    ]
    before, after = _classify(two_directional), _classify(padded)
    assert as_int(before, key="independent_families") == 2
    assert as_int(after, key="independent_families") == 2, (
        "neutral signals must not contribute families to a directional verdict"
    )
    assert as_str(after, key="classification") == as_str(before, key="classification")
    assert after.confidence == before.confidence


def test_the_neutral_only_families_are_published_and_warned_about() -> None:
    """The exclusion is disclosed, not silent."""
    signals = [
        _signal(1, F.BLS_CPI),
        _signal(1, F.BEA_PCE),
        _signal(0, F.TREASURY_OFFICIAL),
    ]
    result = _classify(signals)
    value = result.value
    assert isinstance(value, dict)
    excluded = value["families_excluded_as_neutral"]
    assert isinstance(excluded, list)
    assert excluded == ["treasury_official"]
    assert any("appear ONLY among neutral signals" in w for w in result.warnings)


def test_confidence_matches_compute_confidence_over_the_measured_families() -> None:
    """Confidence is ``compute_confidence()``'s output, not a literal."""
    result = _classify(_unanimous(_four_families()))
    expected = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=False,
            is_heuristic_not_calibrated=True,
            depends_on_unobservable=False,
            source_independence_count=4,
        )
    )
    assert result.confidence == expected


def test_confidence_is_flat_across_verdicts_at_equal_family_count() -> None:
    """Severity and confidence are different facts.

    A ``CONFLICTED`` read is not *less certain* than a ``LOW`` one — it is a
    differently-shaped fact about the same quality of input. Confidence moves
    only with the measured family count.
    """
    families = _four_families()
    unanimous = _classify(_unanimous(families))
    conflicted = _classify(
        [_signal(v, fam) for v, fam in zip((1, 1, -1, -1), families, strict=True)]
    )
    assert as_str(unanimous, key="classification") != as_str(conflicted, key="classification")
    assert unanimous.confidence == conflicted.confidence


def test_a_data_quality_flag_among_the_signals_lowers_confidence() -> None:
    """A flagged signal is priced into the convergence confidence."""
    clean = [_signal(1, fam) for fam in _four_families()]
    flagged = list(clean)
    flagged[0] = clean[0].model_copy(update={"data_quality_flags_present": True})
    assert _classify(flagged).confidence < _classify(clean).confidence


def test_untagged_signals_are_excluded_and_disclosed() -> None:
    """Untagged provenance is neither independence nor its absence (D-046)."""
    signals = _unanimous(_four_families())
    signals[3] = signals[3].model_copy(update={"source_family": None})
    result = _classify(signals)
    assert as_int(result, key="independent_families") == 3
    assert as_int(result, key="untagged_signals") == 1
    assert any("carry no source family" in w for w in result.warnings)


def test_untagged_signals_counts_the_whole_list_not_only_the_census() -> None:
    """D-077 REGRESSION — the untagged count must be a MEASUREMENT, not a constant.

    Found by asking what the number *could* be rather than what it *is*. The
    census that produces ``untagged`` runs over the DIRECTIONAL signals only
    (deliberately — §15.19-D, a neutral signal's family cannot back a directional
    verdict). But ``with_source_family`` REFUSES ``None`` for a non-neutral
    signal, so a signal that got its direction can never be untagged. The
    intersection of those two rules is the empty set: the census reports
    ``untagged=0`` for every input, always.

    ``classify_convergence`` copied that structural zero into the published
    ``untagged_signals`` field via ``isinstance(untagged, int) else 0`` — the
    ``else 0`` being the fabrication, since a missing key and a measured zero are
    different facts. The published field was therefore a constant dressed as a
    measurement, and its warning could never fire: on the fixture below it would
    print "0 of 1 signal(s) carry no source family" — asserting hygiene it had
    not checked, and doing so in the one warning whose entire purpose is to
    disclose that a verdict rests on unknown provenance.

    The count is now taken over the whole signal list, which is the population
    the warning's own text ("of {total} signal(s)") already claimed.
    """
    # A neutral signal that is genuinely untagged — the only shape of untagged
    # signal that can exist, and precisely the one the census cannot see.
    signals = [_signal(1, F.BLS_CPI), _signal(0, None), _signal(0, F.BEA_PCE)]
    result = _classify(signals)

    assert as_int(result, key="untagged_signals") == 1, (
        "the untagged count must include the neutral signal the census excludes"
    )
    matching = [w for w in result.warnings if "carry no source family" in w]
    assert len(matching) == 1, f"expected exactly one disclosure, got {matching}"
    assert "1 of 3 signal(s)" in matching[0], (
        f"the disclosure must state the true untagged share; got: {matching[0]}"
    )
    assert "0 of 3 signal(s)" not in matching[0]

    # And the census is still the DIRECTIONAL one: the neutral signals' families
    # must not be counted as backing the directional verdict.
    assert as_int(result, key="independent_families") == 1
    assert as_int(result, key="non_neutral_signals") == 1


def test_an_all_untagged_list_is_measured_as_untagged() -> None:
    """The floor case of D-077: a list the census sees as empty of families.

    ``count_independent_families([])`` returns ``untagged=0`` — correct for its
    own (empty) input, but it makes the structural zero unmistakable: every
    signal in ``signals`` is untagged, so any honest measurement must say 3.
    """
    signals = [_signal(1, None), _signal(1, None), _signal(-1, None)]
    result = _classify(signals)

    assert as_int(result, key="untagged_signals") == 3
    assert as_int(result, key="independent_families") == 0
    assert any("3 of 3 signal(s) carry no source family" in w for w in result.warnings)


# --------------------------------------------------------------------------
# Warning paths
# --------------------------------------------------------------------------


def test_every_warning_path_is_triggered_by_some_test() -> None:
    """Enumerate the warning branches and prove each is reached.

    A warning branch with no test is deletable (D-045), and this project's
    convention is to assert the pairing rather than trust coverage.
    """
    seen: set[str] = set()

    seen.update(_classify(_unanimous(_four_families())).warnings)  # HIGH, clean
    seen.update(_classify([_signal(1, F.BLS_CPI), _signal(-1, F.BEA_PCE)]).warnings)  # CONFLICTED
    seen.update(_classify([_signal(0, F.BLS_CPI)]).warnings)  # NO_SIGNAL
    seen.update(_classify(_unanimous((F.BLS_CPI, F.BLS_CPI))).warnings)  # redundancy
    seen.update(_classify(_unanimous((F.BLS_CPI, F.BEA_PCE))).warnings)  # MEDIUM band
    seen.update(
        _classify([_signal(1, F.BLS_CPI), _signal(1, None)]).warnings  # untagged
    )
    seen.update(
        _classify([_signal(1, F.BLS_CPI), _signal(1, F.BLS_CPI), _signal(0, F.BEA_PCE)]).warnings
    )  # neutral exclusion

    expected = {
        "Thresholds are illustrative",
        "CONFLICTED — the signals point opposite ways",
        "NO_SIGNAL — all",
        "redundant evidence",
        "enough for MEDIUM, below the",
        "carry no source family",
        "read neutral and are excluded",
    }
    joined = "\n".join(seen)
    for marker in expected:
        assert marker in joined, f"warning branch never fired: {marker!r}"


def test_the_baseline_illustrative_warning_is_always_present() -> None:
    """Every output discloses that the thresholds are not calibrated."""
    assert any(
        "illustrative starting heuristics" in w
        for w in _classify(_unanimous(_four_families())).warnings
    )


# --------------------------------------------------------------------------
# Config accessors — tested against a PERTURBED object (D-050's blind spot)
# --------------------------------------------------------------------------


def test_the_accessors_read_their_leaves_not_the_shipped_literals() -> None:
    """Assert against SHIFTED leaves, so a hardcoded copy is detectable.

    A test asserting ``settings.medium_family_floor == 2`` passes whether the
    accessor reads the YAML or returns the constant ``2``. Four of the
    scorecard's accessors were replaceable by their own shipped literals with
    the whole suite green (D-050); this asserts the perturbed values instead.
    """
    moved = _settings(high=0, medium=1, high_families=5, medium_families=4)
    assert moved.high_family_floor == 5
    assert moved.medium_family_floor == 4
    assert moved.high_dissent_ceiling == 0
    assert moved.medium_dissent_ceiling == 1
    shifted = _settings(high=0, medium=1, high_families=1, medium_families=1)
    assert shifted.high_family_floor == 1
    assert shifted.medium_family_floor == 1


def test_shipped_family_floors_are_lower_than_the_high_floor() -> None:
    """The shipped ordering is the one the gates assume."""
    cfg = _cfg()
    assert cfg.high_family_floor > cfg.medium_family_floor


def test_the_config_refuses_inverted_dissent_ceilings() -> None:
    with pytest.raises(ValidationError, match="must not exceed"):
        _settings(high=2, medium=1)


def test_the_config_refuses_a_negative_dissent_ceiling() -> None:
    with pytest.raises(ValidationError, match="cannot be negative"):
        _settings(high=-1, medium=0)


def test_the_config_refuses_a_medium_ceiling_above_one() -> None:
    """Above one dissenter, the ceiling could only promote CONFLICTED reads."""
    with pytest.raises(ValidationError, match="exceeds one"):
        _settings(high=0, medium=2)


def test_the_config_refuses_inverted_family_floors() -> None:
    """A HIGH floor below the MEDIUM floor is refused.

    The dissent ceilings are set legally here (high=0, medium=1) so the family
    validator is the one that fires — with inverted ceilings the earlier check
    would raise first and the family rule would go untested.
    """
    with pytest.raises(ValidationError, match="must not be below"):
        _settings(high=0, medium=1, high_families=1, medium_families=2)


def test_the_config_refuses_a_zero_family_floor() -> None:
    with pytest.raises(ValidationError, match="must be at least 1"):
        _settings(high=0, medium=1, high_families=3, medium_families=0)


def test_the_published_conflicted_share_is_the_base_state_disclosure() -> None:
    """The share travels on the config so an output can contrast with it."""
    share = _cfg().conflicted_base_share
    assert 0.0 < share < 1.0
    # The scorecard measured 0.617 over four named pillars; the classifier
    # measures 0.6173 over four signals. They are the same predicate, so the
    # two independent measurements must agree closely.
    assert abs(share - 0.617) < 0.005


# --------------------------------------------------------------------------
# The result's own contract
# --------------------------------------------------------------------------


def test_the_result_is_labelled_with_this_engine_and_country() -> None:
    result = _classify(_unanimous(_four_families()))
    assert result.model_name == "classify_convergence"
    assert result.country == "us"


def test_the_result_carries_an_interpretation_and_context() -> None:
    result = _classify(_unanimous(_four_families()))
    assert result.interpretation.startswith("Convergence: ")
    assert "15.19-D" in result.context


def test_every_decision_quantity_is_published() -> None:
    """Every quantity a gate reads must be visible in the output."""
    result = _classify(_unanimous(_four_families()))
    assert isinstance(result.value, dict)
    for key in (
        "classification",
        "agreement_fraction",
        "agreement_margin",
        "dissenting_signals",
        "non_neutral_signals",
        "total_signals",
        "independent_families",
        "untagged_signals",
        "families_excluded_as_neutral",
        "directions",
    ):
        assert key in result.value, f"missing published key: {key}"


def test_every_published_quantity_has_the_right_value_not_just_the_right_key() -> None:
    """A key-presence assertion cannot see a key wired to the wrong quantity.

    Found by mutation M7.4, which replaced ``"dissenting_signals": dissent`` with
    ``"dissenting_signals": n``: the mutant survived every existing test, because
    ``test_every_decision_quantity_is_published`` asserts only that the key
    *exists*. A published key that carries the wrong number is worse than a
    missing one — the missing one is an obvious error, the wrong one is an audit
    trail that lies.

    The read is a deliberately mixed case so no two published quantities are
    equal: four directional signals, three families, one neutral, one untagged.
    With all-distinct values, wiring any key to any other key fails here.
    """
    signals = [
        _signal(1, F.BLS_CPI),
        _signal(1, F.BEA_PCE),
        _signal(1, F.TREASURY_OFFICIAL),
        _signal(0, F.MARKET_BREAKEVEN),
        _signal(1, None),
    ]
    result = _classify(signals)
    value = result.value
    assert isinstance(value, dict)
    # n=4 directional, total=5, distinct=3, untagged=1, dissent=0, excluded=1.
    assert value["classification"] == "HIGH"
    assert value["non_neutral_signals"] == 4
    assert value["total_signals"] == 5
    assert value["independent_families"] == 3
    assert value["untagged_signals"] == 1
    assert value["dissenting_signals"] == 0
    assert value["agreement_fraction"] == 1.0
    assert value["agreement_margin"] == 1.0
    assert value["families_excluded_as_neutral"] == ["market_breakeven"]
    assert value["directions"] == [1, 1, 1, 0, 1]
    # The three counts that a careless edit most easily conflates are distinct.
    counts = {value["non_neutral_signals"], value["total_signals"], value["independent_families"]}
    assert len(counts) == 3


def test_the_dissent_count_is_not_the_directional_count() -> None:
    """The specific confusion M7.4 introduced, asserted directly.

    In this read there are four directional signals and zero dissenters, so
    wiring the two together changes the published number while leaving the
    verdict — which is exactly how it survived a suite that checks verdicts.
    """
    result = _classify(_unanimous(_four_families()))
    value = result.value
    assert isinstance(value, dict)
    assert value["non_neutral_signals"] == 4
    assert value["dissenting_signals"] == 0
    assert value["dissenting_signals"] != value["non_neutral_signals"]


def test_the_inputs_used_are_named_not_indexed() -> None:
    """``inputs_used`` carries the contributing model names, positionally.

    The signal list is arbitrary, so provenance must name the inputs rather than
    refer to them by index. Asserted against the **fixture's** names (``s0``…),
    not against a re-spelled form: a test that hardcodes the mutated literal
    guards the mutation instead of the contract, and inverts the sweep that is
    supposed to detect it.
    """
    signals = _unanimous(_four_families())
    assert [s.model_name for s in signals] == ["s0", "s1", "s2", "s3"]

    result = _classify(signals)
    assert result.inputs_used == ["s0", "s1", "s2", "s3"]
