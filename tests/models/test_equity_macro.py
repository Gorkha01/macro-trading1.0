"""Tests for Module 11's ``sector_rotation_prior`` (Section 6.9).

The function is a *lookup*, so the hazards are not arithmetic ones. They are:

* **coverage.** Section 6.9's reference map is keyed on SIX regime strings, but
  the classifier in ``models/regime.py`` declares and (after D-037) emits NINE.
  Under the reference body, ``slowdown`` / ``recovery`` / ``reflation`` would
  silently return the generic fallback. The tests therefore pin that the map is
  **exhaustive over ``REGIME_STATES``**, which is the assertion that keeps the
  hole from reopening if the classifier's vocabulary grows.
* **the partition between the specification's rows and this build's.** Three rows
  are additions. A reader must be able to tell which is which, so the constants
  are asserted to partition the vocabulary and the extension rows are named.
* **the vocabulary refusal.** Section 6.9's signature is ``str``; a typo under a
  ``.get`` receives the generic fallback rather than an error. The field is a
  ``Literal`` here, so the tests pin that an out-of-vocabulary value raises.
* **the confidence.** It is the PRODUCT of a computed value and a config cap, so
  BOTH factors must be shown to move the published number — a test that only read
  the cap would pass on a build where the computed half was dead code (D-118's
  `min()` defect, restated).
* **the caveat.** The prior-not-rule qualification is the model's central claim
  about itself; a build that dropped it would read as a recommendation.

The confidence and the caveat are asserted by READING THE OUTPUT, never by
recomposing the model's own expression (the ``C6b`` / D-050 defect: a test that
reproduces the code cannot fail when the code is wrong).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from macro_engine.config import CalibratedValue, EquityMacroSettings, get_settings
from macro_engine.models.contracts import (
    ConfidenceInputs,
    EvidenceSourceFamily,
    ModelResult,
    compute_confidence,
)
from macro_engine.models.equity_macro import (
    SECTOR_PRIOR_EXTENSION_REGIMES,
    SECTOR_ROTATION_PRIOR,
    SPECIFICATION_REGIMES,
    SectorRotationInputs,
    sector_rotation_prior,
)
from macro_engine.models.regime import REGIME_STATES, RegimeState


def _settings_with(**values: object) -> EquityMacroSettings:
    """A settings object seeded from the SHIPPED block (D-114's structural fix).

    The base is the shipped block and only the named leaves are overridden, so a
    new leaf cannot make this fixture stale (the O-127 class the ``_fx_carry``
    helpers hit four times before D-114 fixed it structurally).
    """
    base = dict(get_settings().equity_macro.model_dump())
    base.update(values)
    return EquityMacroSettings.model_validate(base)


def _inputs(regime: str = "mid_expansion") -> SectorRotationInputs:
    """An input model for a named regime."""
    return SectorRotationInputs(regime_state=regime)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Coverage — the defect Section 6.9's map has, and the assertion that closes it
# ---------------------------------------------------------------------------


def test_map_is_exhaustive_over_the_classifier_vocabulary() -> None:
    """EVERY declared regime state has a row.

    This is the increment's central assertion: it is what makes the reference
    body's six-key map (which silently falls back for three reachable states) a
    defect rather than a specification, and it is what fails loudly if the
    classifier's vocabulary grows without the map following.
    """
    missing = set(REGIME_STATES) - set(SECTOR_ROTATION_PRIOR)
    assert not missing, (
        f"regimes with no sector prior: {sorted(missing)}. Section 6.9's map "
        f"covers only six of the classifier's states; the map must be exhaustive."
    )


def test_no_map_key_is_outside_the_classifier_vocabulary() -> None:
    """The map introduces no regime the classifier cannot emit.

    The converse of the check above: a row keyed on a string the classifier never
    returns is DEAD VOCABULARY (D-037's class), so the map and the classifier
    must be the same set.
    """
    extra = set(SECTOR_ROTATION_PRIOR) - set(REGIME_STATES)
    assert not extra, f"map keys outside REGIME_STATES (dead rows): {sorted(extra)}"


def test_the_two_regime_constants_partition_the_vocabulary() -> None:
    """The specification's rows and this build's extensions are disjoint and total.

    A reader must be able to tell a Section 6.9 row from an added one, so the two
    constants together must be exactly ``REGIME_STATES`` with no overlap.
    """
    spec = set(SPECIFICATION_REGIMES)
    ext = set(SECTOR_PRIOR_EXTENSION_REGIMES)
    assert not (spec & ext), f"a regime is both specification and extension: {spec & ext}"
    assert spec | ext == set(REGIME_STATES), (
        f"the constants do not cover the vocabulary: missing {set(REGIME_STATES) - (spec | ext)}"
    )
    assert len(SPECIFICATION_REGIMES) == 6
    assert len(SECTOR_PRIOR_EXTENSION_REGIMES) == 3


def test_every_regime_returns_a_non_empty_sector_list() -> None:
    """No regime — specification or extension — yields an empty result.

    An empty list on any path would make the published container's shape depend
    on the branch, which the ``value`` contract forbids.
    """
    for regime in REGIME_STATES:
        result = sector_rotation_prior(_inputs(regime))
        assert isinstance(result.value, list)
        assert result.value, f"{regime} produced an empty sector list"


# ---------------------------------------------------------------------------
# The rows themselves — asserted against the specification's declared content
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("regime", "expected"),
    [
        ("early_expansion", ["financials", "consumer_discretionary", "industrials"]),
        ("mid_expansion", ["technology"]),
        ("late_expansion", ["energy", "materials"]),
        ("recession", ["utilities", "staples", "healthcare"]),
        ("stagflation", ["staples", "energy"]),
        ("disinflation", ["technology", "financials"]),
    ],
)
def test_specification_rows_match_section_6_9(regime: str, expected: list[str]) -> None:
    """The six specification rows are Section 6.9's own, verbatim and in order.

    Written out here rather than imported so the assertion cannot pass by reading
    the value under test.
    """
    assert sector_rotation_prior(_inputs(regime)).value == expected


@pytest.mark.parametrize("regime", ["slowdown", "recovery", "reflation"])
def test_extension_rows_are_not_the_generic_fallback(regime: str) -> None:
    """The three added regimes return a REAL prior, not ``no_prior_label``.

    This is the coverage hole restated as a test: under Section 6.9's six-key map
    each of these would return the generic label; here each returns sectors.
    """
    result = sector_rotation_prior(_inputs(regime))
    assert isinstance(result.value, list)
    assert result.value != [get_settings().equity_macro.no_prior_label]
    assert len(result.value) >= 2


def test_extension_rows_carry_a_disclosure_of_their_origin() -> None:
    """An extension row says so in its assumptions.

    The three added rows are this build's declaration, not Section 6.9's; a
    consumer must be able to see that from the result itself.
    """
    for regime in SECTOR_PRIOR_EXTENSION_REGIMES:
        result = sector_rotation_prior(_inputs(regime))
        assert any("NOT Section" in a for a in result.assumptions), (
            f"{regime}'s result does not disclose that its row is an extension"
        )


def test_specification_rows_do_not_claim_to_be_extensions() -> None:
    """The converse: a specification row does not carry the extension disclosure."""
    for regime in SPECIFICATION_REGIMES:
        result = sector_rotation_prior(_inputs(regime))
        assert not any("NOT Section" in a for a in result.assumptions)


# ---------------------------------------------------------------------------
# The vocabulary refusal — Section 6.9's bare-str defect, closed
# ---------------------------------------------------------------------------


def test_an_out_of_vocabulary_regime_is_refused_at_construction() -> None:
    """A misspelled regime RAISES; it does not receive the generic fallback.

    Section 6.9's ``.get(regime_state, [...])`` would answer ``"recesion"`` with
    the generic prior. The field is a ``Literal`` here, so the value cannot be
    constructed.
    """
    with pytest.raises(ValidationError, match="regime_state"):
        SectorRotationInputs(regime_state="recesion")  # type: ignore[arg-type]


def test_an_empty_regime_is_refused_at_construction() -> None:
    """An empty string is refused, not defaulted."""
    with pytest.raises(ValidationError):
        SectorRotationInputs(regime_state="")  # type: ignore[arg-type]


def test_the_field_literal_is_the_classifiers_own() -> None:
    """The input field is typed as the classifier's ``RegimeState``, not a copy.

    Imported, not re-typed (D-046): if ``regime.py`` gains a state, this module's
    field accepts it and the coverage test above fails until the map is extended.
    """
    from typing import get_args

    annotation = SectorRotationInputs.model_fields["regime_state"].annotation
    assert set(get_args(annotation)) == set(get_args(RegimeState))


# ---------------------------------------------------------------------------
# The fallback — reachable only via an uncovered DECLARED state, and proven so
# ---------------------------------------------------------------------------


def test_the_fallback_is_unreachable_today() -> None:
    """The generic fallback cannot fire for any declared regime, because the map
    is exhaustive.

    The fallback is KEPT as the honest response should the vocabulary grow, but
    today it is unreachable — and this test proves that by driving every declared
    state through the function and never seeing the label. (The D-118 ``R6a``
    lesson: write the branch, then MEASURE whether it can bind.)
    """
    label = get_settings().equity_macro.no_prior_label
    for regime in REGIME_STATES:
        assert sector_rotation_prior(_inputs(regime)).value != [label]


def test_the_fallback_still_publishes_the_configured_label_when_forced() -> None:
    """When the map is made incomplete, the fallback publishes the config label.

    The fallback path is dead today, so it is exercised by forcing it: the map is
    emptied for one regime and the configured ``no_prior_label`` must appear, with
    the disclosure warning. This is the behaviour a future vocabulary change would
    rely on.
    """
    import macro_engine.models.equity_macro as mod

    label = get_settings().equity_macro.no_prior_label
    patched = {k: v for k, v in SECTOR_ROTATION_PRIOR.items() if k != "mid_expansion"}
    original = mod.SECTOR_ROTATION_PRIOR
    mod.SECTOR_ROTATION_PRIOR = patched
    try:
        missing = sector_rotation_prior(_inputs("mid_expansion"))
    finally:
        mod.SECTOR_ROTATION_PRIOR = original

    assert missing.value == [label]
    assert any("no defined sector prior" in w for w in missing.warnings)
    # The confidence is LOWER without a prior: the computed half prices the miss.
    covered = sector_rotation_prior(_inputs("mid_expansion")).confidence
    assert covered > missing.confidence


# ---------------------------------------------------------------------------
# Confidence — a PRODUCT, both halves load-bearing (D-118's min() defect)
# ---------------------------------------------------------------------------


def test_confidence_is_the_product_of_computed_and_cap() -> None:
    """The published confidence equals ``compute_confidence(...) * cap``.

    Both halves are read FROM THE SAME RUN — the D-119 lesson (pairing one run's
    computed value with another run's cap is a defect in the CHECK, not the
    model).
    """
    settings = get_settings().equity_macro
    expected_computed = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=False,
            is_heuristic_not_calibrated=not settings.reliability_cap_is_calibrated,
            source_independence_count=1,
            depends_on_unobservable=False,
        )
    )
    result = sector_rotation_prior(_inputs("mid_expansion"))
    assert result.confidence == pytest.approx(
        expected_computed * settings.reliability_value, abs=1e-12
    )


def test_the_cap_is_load_bearing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Perturbing the cap moves the published confidence (D-050).

    A build that read the computed half alone, or hardcoded the cap, would fail
    here. The leaf is perturbed in place (the ``test_carry_score`` idiom), never
    compared against its own literal.
    """
    base = sector_rotation_prior(_inputs("mid_expansion")).confidence
    cap = get_settings().equity_macro.reliability_cap
    monkeypatch.setattr(cap, "value", float(cap.value) / 2.0, raising=False)

    moved = sector_rotation_prior(_inputs("mid_expansion")).confidence
    assert moved == pytest.approx(base / 2.0, abs=1e-12), (
        "halving the cap must halve the published confidence"
    )


def test_the_computed_half_is_load_bearing(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing prior lowers the confidence — the computed half is not dead code.

    Forcing the fallback path makes ``data_quality_flags_present`` true, which
    must lower the published number. If the computed half were dropped (a bare
    cap), the two values would be equal and this would fail.
    """
    import macro_engine.models.equity_macro as mod

    covered = sector_rotation_prior(_inputs("recession"))
    patched = {k: v for k, v in SECTOR_ROTATION_PRIOR.items() if k != "recession"}
    monkeypatch.setattr(mod, "SECTOR_ROTATION_PRIOR", patched)

    missing = sector_rotation_prior(_inputs("recession"))
    assert missing.value == [get_settings().equity_macro.no_prior_label]
    assert missing.confidence < covered.confidence


def test_the_calibration_status_leaf_is_load_bearing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cap's calibration STATUS moves the published confidence (D-050).

    The confidence's computed half reads ``reliability_cap_is_calibrated`` into
    ``is_heuristic_not_calibrated``, so an uncalibrated cap must price a
    heuristic penalty. The shipped cap IS ``uncalibrated_illustrative`` (so the
    penalty is ON), which means the load-bearing direction to prove is the
    RELEASE: a build whose helper reported ``calibrated`` unconditionally — the
    ``N1b`` mutation — would apply no penalty and publish a HIGHER number. This
    perturbs the leaf's own ``calibration_status`` in place (a status change,
    never a comparison against the helper's own expression: the ``C6b`` defect)
    and asserts the number RISES by exactly the configured ``heuristic_penalty``
    applied to the same run's inputs, scaled by the shipped cap the product uses.
    """
    settings = get_settings()
    shipped = sector_rotation_prior(_inputs("mid_expansion")).confidence
    assert not settings.equity_macro.reliability_cap_is_calibrated, (
        "this test proves the release direction, which only exists while the "
        "shipped cap is uncalibrated"
    )

    # A trustworthy status: the penalty must no longer apply. The leaf is the
    # same object the shipped settings read, so mutating it in place moves the
    # helper the model actually calls.
    monkeypatch.setattr(
        settings.equity_macro.reliability_cap,
        "calibration_status",
        "mechanical_rule",
        raising=False,
    )
    # Read into a local so the assertion is a plain runtime check rather than a
    # narrowing guard that would make the rest of the test unreachable to mypy.
    leaf_moved: bool = settings.equity_macro.reliability_cap_is_calibrated
    assert leaf_moved, "the calibration status leaf did not move"

    released = sector_rotation_prior(_inputs("mid_expansion")).confidence

    # The penalty is read from config, so the expected lift is measured, not
    # typed: it is the configured heuristic penalty applied to the SHIPPED cap
    # the product scales by (the cap's value is unchanged by the status edit).
    penalty_times_cap = settings.confidence.heuristic_penalty.value * (
        settings.equity_macro.reliability_value
    )
    assert released > shipped, (
        "marking the cap calibrated must RELEASE the heuristic penalty and so "
        "raise the published confidence; equality means the status is not read"
    )
    assert released - shipped == pytest.approx(penalty_times_cap, abs=1e-12)


def test_confidence_stays_within_the_unit_interval() -> None:
    """Every regime publishes a confidence in ``[0, 1]``."""
    for regime in REGIME_STATES:
        result = sector_rotation_prior(_inputs(regime))
        assert 0.0 <= result.confidence <= 1.0


# ---------------------------------------------------------------------------
# The caveat, the contract and the container
# ---------------------------------------------------------------------------


def test_the_prior_not_rule_caveat_is_published_on_every_path() -> None:
    """The base-rate qualification is in ``context`` and a warning, always.

    A caller who reads a bare sector list as a recommendation has misread the
    model; the output must make that hard on every path.
    """
    for regime in REGIME_STATES:
        result = sector_rotation_prior(_inputs(regime))
        assert "BASE-RATE PRIOR" in result.context
        assert any("BASE-RATE PRIOR" in w for w in result.warnings)


def test_the_result_is_a_model_result_with_the_expected_identity() -> None:
    """The contract: model name, country, unit, source family."""
    result = sector_rotation_prior(_inputs("mid_expansion"))
    assert isinstance(result, ModelResult)
    assert result.model_name == "sector_rotation_prior"
    assert result.country == "us"
    assert result.unit == "sector_names"
    assert result.source_family == EvidenceSourceFamily.MANUAL_ASSESSMENT
    assert result.inputs_used == ["regime_state"]


def test_the_published_value_is_a_fresh_list_not_the_map_entry() -> None:
    """Mutating the result must not corrupt the module's own map.

    A build that published the map's tuple (or shared its list) would let a
    caller edit ``SECTOR_ROTATION_PRIOR`` through the result.
    """
    result = sector_rotation_prior(_inputs("mid_expansion"))
    assert isinstance(result.value, list)
    result.value.append("__MUTANT__")
    assert sector_rotation_prior(_inputs("mid_expansion")).value == ["technology"]


def test_sector_order_is_preserved_from_the_map() -> None:
    """The published order is the map's order, most-advantaged first."""
    for regime, sectors in SECTOR_ROTATION_PRIOR.items():
        assert sector_rotation_prior(_inputs(regime)).value == list(sectors)


# ---------------------------------------------------------------------------
# The config leaves
# ---------------------------------------------------------------------------


def test_the_default_cap_is_the_specifications_value() -> None:
    """The shipped cap is Section 6.9's ``0.4``.

    Unlike ``intervention_capacity``'s 0.8/0.7, the specification's value is KEPT
    (there is no ordering argument against a base-rate frequency). Read from
    SHIPPED config so a change to it is a deliberate edit, not a silent one.
    """
    assert get_settings().equity_macro.reliability_value == 0.4


def test_a_cap_outside_the_unit_interval_is_refused() -> None:
    """The settings validator refuses a cap outside ``[0, 1]``."""
    with pytest.raises(ValueError, match="reliability_cap"):
        _settings_with(
            reliability_cap=CalibratedValue(
                value=1.5, calibration_status="uncalibrated_illustrative"
            )
        )


def test_a_negative_cap_is_refused() -> None:
    """A negative cap is refused before it can reach ``ModelResult``."""
    with pytest.raises(ValueError, match="reliability_cap"):
        _settings_with(
            reliability_cap=CalibratedValue(
                value=-0.1, calibration_status="uncalibrated_illustrative"
            )
        )


def test_an_empty_no_prior_label_is_refused() -> None:
    """An empty no-prior label is refused: it would publish a blank sector."""
    with pytest.raises(ValueError, match="no_prior_label"):
        _settings_with(
            no_prior_label_leaf=CalibratedValue(
                value="   ", calibration_status="institutional_convention"
            )
        )
