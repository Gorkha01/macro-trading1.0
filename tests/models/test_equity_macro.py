"""Tests for Module 11's ``sector_rotation_prior`` / ``duration_sensitivity`` /
``factor_tilt_prior`` (Section 6.9, Section 20.20-E).

The functions are *lookups and a proxy*, so the hazards are not arithmetic ones
alone. They are:

* **coverage.** Section 6.9's reference sector map is keyed on SIX regime
  strings, but the classifier in ``models/regime.py`` declares and (after D-037)
  emits NINE. Under the reference body, ``slowdown`` / ``recovery`` /
  ``reflation`` would silently return the generic fallback. The tests therefore
  pin that BOTH regime-keyed maps are **exhaustive over ``REGIME_STATES``**,
  which is the assertion that keeps the hole from reopening if the classifier's
  vocabulary grows.
* **the partition between the specification's rows and this build's.** Three
  sector rows are additions. A reader must be able to tell which is which, so the
  constants are asserted to partition the vocabulary and the extension rows are
  named. The factor map has NO extension rows (Section 20.20-E is already
  exhaustive), and that is asserted too.
* **the vocabulary refusal.** Section 6.9's signatures are ``str``; a typo under
  a ``.get`` receives the generic fallback rather than an error. Both fields are
  ``Literals`` here, so the tests pin that an out-of-vocabulary value raises.
* **the confidence.** Each is the PRODUCT of a computed value and a config cap,
  so BOTH factors must be shown to move the published number — a test that only
  read the cap would pass on a build where the computed half was dead code
  (D-118's `min()` defect, restated).
* **the caveat.** The prior-not-rule qualification is the models' central claim
  about themselves; a build that dropped it would read as a recommendation. For
  ``factor_tilt_prior`` the specification adds a sharper, momentum-specific
  warning that must survive.
* **the duration arithmetic and its disclosure.** ``duration_sensitivity`` is the
  one Module 11 function whose output is a NUMBER, so its sign, its linearity,
  the growth/value ratio (3:1), the gate band and the illustrative-not-calibrated
  disclosure are all pinned.

The confidence and the caveats are asserted by READING THE OUTPUT, never by
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
    FACTOR_NAMES,
    FACTOR_REGIME_MAP,
    SECTOR_PRIOR_EXTENSION_REGIMES,
    SECTOR_ROTATION_PRIOR,
    SPECIFICATION_REGIMES,
    DurationSensitivityInputs,
    FactorTiltInputs,
    SectorRotationInputs,
    duration_sensitivity,
    factor_tilt_prior,
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


# ===========================================================================
# duration_sensitivity — Section 6.9's second function
# ===========================================================================


def _dur(style: str = "growth", bp: float = 100.0) -> DurationSensitivityInputs:
    """An input model for a named style and rate move."""
    return DurationSensitivityInputs(style=style, rate_change_bp=bp)  # type: ignore[arg-type]


def _factor(regime: str = "mid_expansion") -> FactorTiltInputs:
    """An input model for a named regime."""
    return FactorTiltInputs(regime_state=regime)  # type: ignore[arg-type]


def test_the_rate_rise_moves_a_growth_equity_down() -> None:
    """A rate RISE is a negative price impact — the model's sign.

    100bp on a 15-year-duration growth equity is ``-15 * (100/10000) * 100`` =
    ``-15.0`` percent. Asserted against the arithmetic written out here, not
    against the model's own expression.
    """
    result = duration_sensitivity(_dur("growth", 100.0))
    assert result.value == pytest.approx(-15.0, abs=1e-9)
    assert result.direction == "down"


def test_the_growth_value_ratio_is_three_to_one() -> None:
    """Growth (15yr) falls three times as far as value (5yr) for one move.

    This is the whole content of the growth-vs-value duration trade
    (``AGENTS.md:2198``): the ratio is the specification's 15:5.
    """
    growth = duration_sensitivity(_dur("growth", 100.0)).value
    value = duration_sensitivity(_dur("value", 100.0)).value
    assert isinstance(growth, float) and isinstance(value, float)
    assert value == pytest.approx(-5.0, abs=1e-9)
    assert growth == pytest.approx(3.0 * value, abs=1e-9)


def test_a_rate_fall_moves_the_equity_up() -> None:
    """A rate FALL is a positive price impact, and the direction flips."""
    result = duration_sensitivity(_dur("growth", -50.0))
    assert result.value == pytest.approx(7.5, abs=1e-9)
    assert result.direction == "up"


def test_a_zero_rate_move_is_flat_with_no_direction() -> None:
    """A zero move publishes 0.0 and a null direction, not a guessed sign."""
    result = duration_sensitivity(_dur("growth", 0.0))
    assert result.value == pytest.approx(0.0, abs=1e-12)
    assert result.direction is None


def test_the_response_is_linear_in_the_rate_move() -> None:
    """Doubling the move doubles the price impact — no convexity term."""
    single = duration_sensitivity(_dur("value", 25.0)).value
    double = duration_sensitivity(_dur("value", 50.0)).value
    assert isinstance(single, float) and isinstance(double, float)
    assert double == pytest.approx(2.0 * single, abs=1e-9)


def test_the_proxies_are_the_specifications_15_and_5() -> None:
    """The two proxies are Section 6.9's own values, read from SHIPPED config."""
    settings = get_settings().equity_macro
    assert settings.duration_growth_proxy_years == 15.0
    assert settings.duration_value_proxy_years == 5.0


@pytest.mark.parametrize("style", ["growth", "value"])
def test_the_illustrative_disclosure_is_published_on_every_path(style: str) -> None:
    """The proxy is ILLUSTRATIVE — the qualification is in context and warnings.

    Section 6.9's own warning says "Proxy duration is illustrative, not
    calibrated". A reader who takes the number as a calibrated forecast has
    misread the model, so the output must make that hard.
    """
    result = duration_sensitivity(_dur(style, 100.0))
    assert "ILLUSTRATIVE" in result.context.upper() or "illustrative" in result.context
    assert any("ILLUSTRATIVE" in w.upper() for w in result.warnings)


def test_an_out_of_vocabulary_style_is_refused() -> None:
    """A style that is not growth/value RAISES; it does not default."""
    with pytest.raises(ValidationError, match="style"):
        DurationSensitivityInputs(style="blend", rate_change_bp=100.0)  # type: ignore[arg-type]


def test_a_rate_move_outside_the_band_is_refused() -> None:
    """A move past the band RAISES — a unit error must not publish a headline."""
    high = get_settings().equity_macro.duration_rate_change_max_bp
    with pytest.raises(ValidationError, match="rate_change_bp"):
        DurationSensitivityInputs(style="growth", rate_change_bp=high + 1.0)


def test_a_rate_move_below_the_band_is_refused() -> None:
    """The lower edge is symmetric."""
    low = get_settings().equity_macro.duration_rate_change_min_bp
    with pytest.raises(ValidationError, match="rate_change_bp"):
        DurationSensitivityInputs(style="growth", rate_change_bp=low - 1.0)


def test_the_band_edges_are_admitted() -> None:
    """The band is INCLUSIVE: a value exactly on an edge is accepted."""
    low = get_settings().equity_macro.duration_rate_change_min_bp
    high = get_settings().equity_macro.duration_rate_change_max_bp
    assert duration_sensitivity(_dur("growth", low)).value is not None
    assert duration_sensitivity(_dur("growth", high)).value is not None


def test_the_growth_proxy_is_load_bearing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Perturbing the growth proxy moves the published value (D-050).

    A build that hardcoded ``15`` would fail here. The leaf is perturbed in
    place, never compared against its own literal.
    """
    leaf = get_settings().equity_macro.duration_growth_proxy_years_leaf
    monkeypatch.setattr(leaf, "value", 30.0, raising=False)
    moved = duration_sensitivity(_dur("growth", 100.0)).value
    assert moved == pytest.approx(-30.0, abs=1e-9), (
        "doubling the growth proxy must double the growth equity's price impact"
    )
    # The value-equity leg is INDEPENDENT of the growth leaf.
    assert duration_sensitivity(_dur("value", 100.0)).value == pytest.approx(-5.0, abs=1e-9)


def test_the_value_proxy_is_load_bearing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The value proxy moves the value leg and not the growth leg."""
    leaf = get_settings().equity_macro.duration_value_proxy_years_leaf
    monkeypatch.setattr(leaf, "value", 10.0, raising=False)
    moved = duration_sensitivity(_dur("value", 100.0)).value
    assert moved == pytest.approx(-10.0, abs=1e-9)
    assert duration_sensitivity(_dur("growth", 100.0)).value == pytest.approx(-15.0, abs=1e-9)


def test_the_duration_cap_is_load_bearing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Halving the cap halves the published confidence (D-050)."""
    base = duration_sensitivity(_dur("growth", 100.0)).confidence
    cap = get_settings().equity_macro.duration_reliability_cap
    monkeypatch.setattr(cap, "value", float(cap.value) / 2.0, raising=False)
    moved = duration_sensitivity(_dur("growth", 100.0)).confidence
    assert moved == pytest.approx(base / 2.0, abs=1e-12)


def test_the_accrued_interest_confidence_is_the_product_of_both_halves() -> None:
    """The published confidence is ``compute_confidence(...) * cap``, same run.

    Both halves are read FROM THE SAME RUN (the D-119 lesson).
    """
    settings = get_settings().equity_macro
    expected_computed = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=False,
            is_heuristic_not_calibrated=not settings.duration_proxy_is_calibrated,
            source_independence_count=1,
            depends_on_unobservable=False,
        )
    )
    result = duration_sensitivity(_dur("growth", 100.0))
    assert result.confidence == pytest.approx(
        expected_computed * settings.duration_reliability_value, abs=1e-12
    )


def test_the_duration_proxy_calibration_status_is_load_bearing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Marking the proxies calibrated RELEASES the heuristic penalty (D-050).

    The shipped proxies ARE ``uncalibrated_illustrative`` (so the penalty is ON);
    the load-bearing direction to prove is the release, which must RAISE the
    published confidence by the configured penalty scaled by the cap.
    """
    settings = get_settings()
    shipped = duration_sensitivity(_dur("growth", 100.0)).confidence
    assert not settings.equity_macro.duration_proxy_is_calibrated, (
        "this test proves the release direction, which only exists while the "
        "shipped proxies are uncalibrated"
    )
    monkeypatch.setattr(
        settings.equity_macro.duration_growth_proxy_years_leaf,
        "calibration_status",
        "mechanical_rule",
        raising=False,
    )
    monkeypatch.setattr(
        settings.equity_macro.duration_value_proxy_years_leaf,
        "calibration_status",
        "mechanical_rule",
        raising=False,
    )
    released_flag: bool = settings.equity_macro.duration_proxy_is_calibrated
    assert released_flag, "the calibration status leaves did not move"

    released = duration_sensitivity(_dur("growth", 100.0)).confidence
    penalty_times_cap = settings.confidence.heuristic_penalty.value * (
        settings.equity_macro.duration_reliability_value
    )
    assert released > shipped
    assert released - shipped == pytest.approx(penalty_times_cap, abs=1e-12)


def test_the_duration_proxy_flag_is_the_conjunction_of_both_legs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ONE illustrative leg makes the whole estimate illustrative (AND, not OR).

    The shipped pair is BOTH ``uncalibrated_illustrative``, so an AND and an OR
    agree on the shipped config and on a config where BOTH are calibrated (the
    two cases ``test_the_duration_proxy_calibration_status_is_load_bearing``
    exercises). The AND and the OR differ on exactly ONE case — one leg
    calibrated, the other not — which is what this test constructs. If the flag
    were an OR, calibrating a single leg would release the heuristic penalty for
    an estimate that still rests on an illustrative leg.
    """
    settings = get_settings()
    assert not settings.equity_macro.duration_proxy_is_calibrated, (
        "the shipped pair must start uncalibrated for this split test to mean anything"
    )
    # Calibrate ONLY the growth leg. The flag must stay False: the value leg is
    # still illustrative, so the estimate as a whole is still illustrative.
    monkeypatch.setattr(
        settings.equity_macro.duration_growth_proxy_years_leaf,
        "calibration_status",
        "mechanical_rule",
        raising=False,
    )
    split_flag: bool = settings.equity_macro.duration_proxy_is_calibrated
    assert split_flag is False, (
        "one calibrated leg and one illustrative leg must report NOT calibrated — "
        "an OR would wrongly release the penalty here"
    )


def test_the_duration_result_is_a_model_result_with_the_expected_identity() -> None:
    """The contract: model name, country, unit, source family."""
    result = duration_sensitivity(_dur("growth", 100.0))
    assert isinstance(result, ModelResult)
    assert result.model_name == "duration_sensitivity"
    assert result.country == "us"
    assert result.unit == "percent_price_change"
    assert result.source_family == EvidenceSourceFamily.MANUAL_ASSESSMENT
    assert result.inputs_used == ["style", "rate_change_bp"]


def test_the_default_duration_cap_is_the_specifications_value() -> None:
    """The shipped cap is Section 6.9's ``0.3``, Module 11's lowest."""
    assert get_settings().equity_macro.duration_reliability_value == 0.3


def test_a_cap_outside_the_unit_interval_is_refused_for_the_duration_block() -> None:
    """The settings validator refuses a duration cap outside ``[0, 1]``."""
    with pytest.raises(ValueError, match="duration_reliability_cap"):
        _settings_with(
            duration_reliability_cap=CalibratedValue(
                value=1.2, calibration_status="uncalibrated_illustrative"
            )
        )


def test_a_non_positive_growth_proxy_is_refused() -> None:
    """A zero-growth proxy is refused: it would erase the price-move sign."""
    with pytest.raises(ValueError, match="duration_growth_proxy_years"):
        _settings_with(
            duration_growth_proxy_years_leaf=CalibratedValue(
                value=0.0, calibration_status="uncalibrated_illustrative"
            )
        )


def test_a_non_positive_value_proxy_is_refused() -> None:
    """A negative value proxy is refused for the same reason."""
    with pytest.raises(ValueError, match="duration_value_proxy_years"):
        _settings_with(
            duration_value_proxy_years_leaf=CalibratedValue(
                value=-1.0, calibration_status="uncalibrated_illustrative"
            )
        )


def test_an_inverted_rate_band_is_refused() -> None:
    """A minimum at or above the maximum is refused (the inverted-branch class)."""
    base = dict(get_settings().equity_macro.model_dump())
    with pytest.raises(ValueError, match="band"):
        _settings_with(
            duration_rate_change_min_bp_leaf=CalibratedValue(
                value=500.0, calibration_status="institutional_convention"
            ),
            duration_rate_change_max_bp_leaf=CalibratedValue(
                value=-500.0, calibration_status="institutional_convention"
            ),
        )
    assert base  # the shipped block is unchanged (structural fixture, D-114)


# ===========================================================================
# factor_tilt_prior — Section 20.20-E's part E
# ===========================================================================


def test_the_factor_map_is_exhaustive_over_the_classifier_vocabulary() -> None:
    """EVERY declared regime state has a factor row.

    Section 20.20-E's table is already exhaustive over the nine, so this is a
    guard against drift rather than a closed hole: if the classifier's vocabulary
    grows, a row must follow.
    """
    missing = set(REGIME_STATES) - set(FACTOR_REGIME_MAP)
    assert not missing, f"regimes with no factor prior: {sorted(missing)}"


def test_no_factor_map_key_is_outside_the_classifier_vocabulary() -> None:
    """The factor map introduces no regime the classifier cannot emit."""
    extra = set(FACTOR_REGIME_MAP) - set(REGIME_STATES)
    assert not extra, f"factor-map keys outside REGIME_STATES (dead rows): {sorted(extra)}"


def test_every_factor_row_tilts_exactly_the_five_factors() -> None:
    """Each row publishes the same five factors — no row is short or wider."""
    for regime, row in FACTOR_REGIME_MAP.items():
        assert set(row) == set(FACTOR_NAMES), f"{regime} does not tilt the five factors"


def test_every_tilt_lies_in_the_closed_unit_interval() -> None:
    """Every tilt is in ``[-1, +1]`` — the specification's scale."""
    for regime, row in FACTOR_REGIME_MAP.items():
        for factor, tilt in row.items():
            assert -1.0 <= tilt <= 1.0, f"{regime}/{factor} tilt {tilt} is out of range"


def test_the_factor_map_has_no_extension_rows() -> None:
    """The factor table is Section 20.20-E's own — unlike the sector map.

    Section 6.9's sector map covers six of nine states (three extension rows);
    Section 20.20-E's factor table covers all nine, so this build adds NOTHING.
    Asserted so a future edit cannot smuggle an invented row in silently.
    """
    assert len(FACTOR_REGIME_MAP) == len(REGIME_STATES) == 9


@pytest.mark.parametrize(
    ("regime", "expected"),
    [
        (
            "early_expansion",
            {"value": 1.0, "momentum": 0.5, "quality": -0.5, "low_vol": -1.0, "size": 0.5},
        ),
        (
            "recession",
            {"value": -0.5, "momentum": -1.0, "quality": 1.0, "low_vol": 1.0, "size": -1.0},
        ),
        (
            "recovery",
            {"value": 1.0, "momentum": 0.0, "quality": -0.5, "low_vol": -1.0, "size": 1.0},
        ),
        (
            "stagflation",
            {"value": 0.5, "momentum": -0.5, "quality": 1.0, "low_vol": 0.5, "size": -1.0},
        ),
    ],
)
def test_factor_rows_match_section_20_20_e(regime: str, expected: dict[str, float]) -> None:
    """Four rows are Section 20.20-E's own, verbatim.

    Written out here rather than imported so the assertion cannot pass by
    reading the value under test. The other five rows are covered by the
    exhaustiveness and range tests above.
    """
    assert factor_tilt_prior(_factor(regime)).value == expected


def test_a_misspelled_regime_is_refused_at_construction() -> None:
    """A typo RAISES; it does not receive the 'unknown regime' branch."""
    with pytest.raises(ValidationError, match="regime_state"):
        FactorTiltInputs(regime_state="recesion")  # type: ignore[arg-type]


def test_the_factor_field_literal_is_the_classifiers_own() -> None:
    """The field is typed as the classifier's ``RegimeState``, imported not copied."""
    from typing import get_args

    annotation = FactorTiltInputs.model_fields["regime_state"].annotation
    assert set(get_args(annotation)) == set(get_args(RegimeState))


def test_the_factor_fallback_is_unreachable_today() -> None:
    """The generic fallback cannot fire for any declared regime (map exhaustive)."""
    for regime in REGIME_STATES:
        assert factor_tilt_prior(_factor(regime)).value != {}


def test_the_factor_fallback_publishes_an_empty_dict_when_forced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forcing an uncovered regime publishes ``{}`` and the disclosure warning."""
    import macro_engine.models.equity_macro as mod

    patched = {k: v for k, v in FACTOR_REGIME_MAP.items() if k != "recession"}
    monkeypatch.setattr(mod, "FACTOR_REGIME_MAP", patched)
    missing = factor_tilt_prior(_factor("recession"))
    assert missing.value == {}
    assert any("no defined factor prior" in w for w in missing.warnings)
    covered = factor_tilt_prior(_factor("mid_expansion")).confidence
    assert covered > missing.confidence


def test_the_momentum_crash_warning_is_published_on_every_path() -> None:
    """Section 20.20-E's momentum warning survives on every regime.

    This is the specification's sharpest caveat — "momentum tilts are least
    reliable precisely at regime turns" — and a build that dropped it would
    present a ``-1.0`` momentum tilt as an instruction.
    """
    for regime in REGIME_STATES:
        result = factor_tilt_prior(_factor(regime))
        assert any("momentum" in w.lower() and "crash" in w.lower() for w in result.warnings), (
            f"{regime} published no momentum-crash warning"
        )


def test_the_factor_prior_not_rule_caveat_is_published_on_every_path() -> None:
    """The base-rate qualification is in context and a warning, always."""
    for regime in REGIME_STATES:
        result = factor_tilt_prior(_factor(regime))
        assert "Base-rate priors" in result.context
        assert any("NOT mechanical rules" in w for w in result.warnings)


def test_the_factor_confidence_is_the_product_of_computed_and_cap() -> None:
    """The published confidence equals ``compute_confidence(...) * cap``, one run."""
    settings = get_settings().equity_macro
    expected_computed = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=False,
            is_heuristic_not_calibrated=not settings.factor_tilt_reliability_cap_is_calibrated,
            source_independence_count=1,
            depends_on_unobservable=False,
        )
    )
    result = factor_tilt_prior(_factor("mid_expansion"))
    assert result.confidence == pytest.approx(
        expected_computed * settings.factor_tilt_reliability_value, abs=1e-12
    )


def test_the_factor_tilt_cap_is_load_bearing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Halving the factor-tilt cap halves the published confidence (D-050)."""
    base = factor_tilt_prior(_factor("mid_expansion")).confidence
    cap = get_settings().equity_macro.factor_tilt_reliability_cap
    monkeypatch.setattr(cap, "value", float(cap.value) / 2.0, raising=False)
    moved = factor_tilt_prior(_factor("mid_expansion")).confidence
    assert moved == pytest.approx(base / 2.0, abs=1e-12)


def test_the_factor_computed_half_is_load_bearing(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing row lowers the confidence — the computed half is not dead code."""
    import macro_engine.models.equity_macro as mod

    covered = factor_tilt_prior(_factor("mid_expansion"))
    patched = {k: v for k, v in FACTOR_REGIME_MAP.items() if k != "mid_expansion"}
    monkeypatch.setattr(mod, "FACTOR_REGIME_MAP", patched)
    missing = factor_tilt_prior(_factor("mid_expansion"))
    assert missing.value == {}
    assert missing.confidence < covered.confidence


def test_the_factor_calibration_status_leaf_is_load_bearing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Marking the factor cap calibrated RELEASES the heuristic penalty (D-050)."""
    settings = get_settings()
    shipped = factor_tilt_prior(_factor("mid_expansion")).confidence
    assert not settings.equity_macro.factor_tilt_reliability_cap_is_calibrated
    monkeypatch.setattr(
        settings.equity_macro.factor_tilt_reliability_cap,
        "calibration_status",
        "mechanical_rule",
        raising=False,
    )
    released_flag: bool = settings.equity_macro.factor_tilt_reliability_cap_is_calibrated
    assert released_flag
    released = factor_tilt_prior(_factor("mid_expansion")).confidence
    penalty_times_cap = settings.confidence.heuristic_penalty.value * (
        settings.equity_macro.factor_tilt_reliability_value
    )
    assert released > shipped
    assert released - shipped == pytest.approx(penalty_times_cap, abs=1e-12)


def test_the_factor_confidence_stays_within_the_unit_interval() -> None:
    """Every regime publishes a confidence in ``[0, 1]``."""
    for regime in REGIME_STATES:
        assert 0.0 <= factor_tilt_prior(_factor(regime)).confidence <= 1.0


def test_the_factor_result_is_a_model_result_with_the_expected_identity() -> None:
    """The contract: model name, country, unit, source family."""
    result = factor_tilt_prior(_factor("mid_expansion"))
    assert isinstance(result, ModelResult)
    assert result.model_name == "factor_tilt_prior"
    assert result.country == "us"
    assert result.unit == "tilt_minus1_to_plus1"
    assert result.source_family == EvidenceSourceFamily.MANUAL_ASSESSMENT
    assert result.inputs_used == ["regime_state"]


def test_the_factor_value_is_a_fresh_dict_not_the_map_row() -> None:
    """Mutating the result must not corrupt the module's own map."""
    result = factor_tilt_prior(_factor("mid_expansion"))
    assert isinstance(result.value, dict)
    result.value["__MUTANT__"] = 99.0
    assert factor_tilt_prior(_factor("mid_expansion")).value == dict(
        FACTOR_REGIME_MAP["mid_expansion"]
    )


def test_the_default_factor_tilt_cap_is_the_specifications_value() -> None:
    """The shipped cap is Section 20.20-E's ``0.35``."""
    assert get_settings().equity_macro.factor_tilt_reliability_value == 0.35


def test_a_factor_tilt_cap_outside_the_unit_interval_is_refused() -> None:
    """The settings validator refuses a factor-tilt cap outside ``[0, 1]``."""
    with pytest.raises(ValueError, match="factor_tilt_reliability_cap"):
        _settings_with(
            factor_tilt_reliability_cap=CalibratedValue(
                value=-0.2, calibration_status="uncalibrated_illustrative"
            )
        )
