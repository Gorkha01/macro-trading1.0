"""Tests for ``build_scenario_distribution`` (Module 12, §16.4 Q10, D-064).

The four defects this file exists to pin
----------------------------------------
1. **Two branches for a five-member vocabulary.** §16.4's ``else`` gives
   ``LOW``, ``CONFLICTED`` and ``NO_SIGNAL`` the same 0.30 — and ``MacroThesis``
   **hard-blocks** a live trade on ``CONFLICTED``, so the producer emitted a
   distribution for a state its own consumer refuses.
   ``test_the_vocabulary_is_a_partition_not_a_fall_through`` is the pin.
2. **``convergence: str``** — a typo silently became 0.30.
   ``test_a_bare_string_convergence_is_refused`` is the pin.
3. **``ScenarioOutcome`` declared twice, incompatibly.** O-51.
   ``test_the_thesis_layer_scenario_outcome_is_the_models_layer_one`` and
   ``test_no_two_top_level_classes_share_a_name`` are the pins.
4. **``gap.unit`` never read.** ``test_a_gap_in_unknown_units_is_refused``.

Expected values are hand-computed in each docstring rather than captured from a
run, per Section 11.1, and the probabilities are read from the fixture's own
leaves rather than re-derived from the same config the code reads (D-035).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from macro_engine.config import get_settings
from macro_engine.models.probability import PayoffUnit
from macro_engine.thesis_layer.scenarios import build_scenario_distribution
from macro_engine.thesis_layer.schemas import (
    ConvergenceClassification,
    MarketPricingGap,
    ScenarioOutcome,
)

#: A meaningful gap of **+1.00 percent**, so every basis-point payoff is the
#: payoff multiple times 100 and the arithmetic in the docstrings is readable.
_RAW_GAP = 1.0

#: The five convergence verdicts, from the enum itself rather than re-typed, so a
#: member added without this file learning about it fails the partition test.
_ALL_VERDICTS = list(ConvergenceClassification)


def _gap(**overrides: object) -> MarketPricingGap:
    params: dict[str, object] = {
        "model_implied_value": 4.0,
        "market_implied_value": 3.0,
        "raw_gap": _RAW_GAP,
        "unit": "%",
        "interpretation": "model above market",
        "is_meaningful": True,
        "dispersion": 0.5,
    }
    params.update(overrides)
    return MarketPricingGap(**params)  # type: ignore[arg-type]


def _build(
    verdict: ConvergenceClassification = ConvergenceClassification.HIGH,
    **gap_overrides: object,
) -> list[ScenarioOutcome]:
    return build_scenario_distribution(_gap(**gap_overrides), verdict)


def _by_name(distribution: list[ScenarioOutcome]) -> dict[str, ScenarioOutcome]:
    return {outcome.name: outcome for outcome in distribution}


# ---------------------------------------------------------------------------
# Defect 1 — the vocabulary is five members, the branches were two
# ---------------------------------------------------------------------------


def test_the_vocabulary_is_a_partition_not_a_fall_through() -> None:
    """Enumerate the enum. Every distributable verdict yields four branches and
    every other verdict yields NONE — the two halves of one partition, driven
    from the enum rather than from a re-typed list."""
    distributable: list[str] = []
    empty: list[str] = []
    for verdict in _ALL_VERDICTS:
        distribution = _build(verdict)
        (distributable if distribution else empty).append(verdict.value)

    assert distributable == ["HIGH", "MEDIUM", "LOW"]
    assert empty == ["CONFLICTED", "NO_SIGNAL"], (
        "CONFLICTED and NO_SIGNAL must produce NO distribution: MacroThesis "
        "hard-blocks a live trade on CONFLICTED, and NO_SIGNAL means every pillar "
        "read neutral so there is nothing to distribute over"
    )


@pytest.mark.parametrize(
    "verdict", [ConvergenceClassification.CONFLICTED, ConvergenceClassification.NO_SIGNAL]
)
def test_a_non_distributable_verdict_returns_an_empty_list(
    verdict: ConvergenceClassification,
) -> None:
    """The empty list is schema-valid — ``MacroThesis`` skips its sum check when
    the distribution is empty — so the no-trade path needs no special case."""
    assert _build(verdict) == []


def test_a_non_distributable_verdict_does_not_read_the_gap() -> None:
    """Ordering: the convergence check comes FIRST, so a CONFLICTED thesis with a
    malformed gap still returns ``[]`` rather than raising about the gap. The
    verdict decides whether a thesis exists at all; the gap is only consulted
    once one does."""
    assert build_scenario_distribution(_gap(unit="bp"), ConvergenceClassification.CONFLICTED) == []


# ---------------------------------------------------------------------------
# Defect 2 — the enumerated parameter
# ---------------------------------------------------------------------------


def test_an_exact_string_spelling_works() -> None:
    """``ConvergenceClassification`` inherits from ``str``, so a bare ``"HIGH"``
    has the same hash as the member and passes a membership test — and then dies
    on ``.value`` with ``AttributeError: 'str' object has no attribute 'value'``.
    Parsing at the boundary turns that into the right answer."""
    distribution = build_scenario_distribution(_gap(), "HIGH")  # type: ignore[arg-type]
    assert distribution[0].probability == pytest.approx(0.55)
    assert distribution[0].name == "base_case_gap_closes_as_modeled"


@pytest.mark.parametrize("typo", ["high", "High", "HIGH ", "CONVERGING", ""])
def test_a_misspelled_convergence_is_refused(typo: str) -> None:
    """§16.4's signature is ``convergence: str``, so every one of these fell into
    the ``else`` branch and silently received ``0.30`` — a full, tradeable
    distribution for a verdict the caller never named. D-029's enumerated-field
    rule: the parameter is typed, AND parsed at the boundary, so the typo is an
    error rather than a default."""
    with pytest.raises(ValueError, match="is not a valid"):
        build_scenario_distribution(_gap(), typo)  # type: ignore[arg-type]


def test_the_typo_and_the_valid_spelling_are_distinguishable() -> None:
    """The whole point: ``"HIGH"`` and ``"high"`` must not both produce a
    distribution. One works; the other raises."""
    assert build_scenario_distribution(_gap(), "HIGH")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        build_scenario_distribution(_gap(), "high")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The arithmetic, hand-computed
# ---------------------------------------------------------------------------


def test_the_high_convergence_distribution() -> None:
    """base 0.55, remaining 0.45.

    Hand calculation: 0.45 * 0.5 = 0.225; 0.45 * 0.35 = 0.1575;
    0.45 * 0.15 = 0.0675. Sum = 0.55 + 0.225 + 0.1575 + 0.0675 = 1.0.
    Payoffs on a +1.00% gap at 100 bp/%: +100, +40, -60, -150.
    """
    distribution = _by_name(_build(ConvergenceClassification.HIGH))
    assert distribution["base_case_gap_closes_as_modeled"].probability == 0.55
    assert distribution["gap_partially_closes"].probability == pytest.approx(0.225)
    assert distribution["thesis_invalidated_reversal"].probability == pytest.approx(0.1575)
    assert distribution["tail_adverse_surprise"].probability == pytest.approx(0.0675)
    assert distribution["base_case_gap_closes_as_modeled"].payoff_estimate == pytest.approx(100.0)
    assert distribution["gap_partially_closes"].payoff_estimate == pytest.approx(40.0)
    assert distribution["thesis_invalidated_reversal"].payoff_estimate == pytest.approx(-60.0)
    assert distribution["tail_adverse_surprise"].payoff_estimate == pytest.approx(-150.0)


@pytest.mark.parametrize(
    ("verdict", "base"),
    [
        (ConvergenceClassification.HIGH, 0.55),
        (ConvergenceClassification.MEDIUM, 0.45),
        (ConvergenceClassification.LOW, 0.30),
    ],
)
def test_every_distribution_sums_to_one(verdict: ConvergenceClassification, base: float) -> None:
    """The whole reason the four probabilities are derived from ``base`` and the
    shares rather than chosen: the sum is then a consequence, not a coincidence.
    The tolerance is the schema's own, not a looser local one."""
    distribution = _build(verdict)
    total = sum(outcome.probability for outcome in distribution)
    tolerance = get_settings().validation.prob_tolerance
    assert abs(total - 1.0) <= tolerance, f"{verdict.value} summed to {total!r}"
    assert distribution[0].probability == base


def test_the_four_branch_names_are_the_config_keys() -> None:
    """A rename in the config or in the function must fail loudly. The names are
    the join between the two, so they are asserted as a set against the config's
    own keys rather than re-typed."""
    settings = get_settings().scenario_distribution
    names = {outcome.name for outcome in _build()}
    assert names == set(settings.payoff_multiples)
    assert names == set(settings.remaining_shares) | {"base_case_gap_closes_as_modeled"}


def test_the_gap_scales_every_payoff() -> None:
    """Doubling the gap doubles every payoff and changes no probability."""
    single = _by_name(_build(raw_gap=1.0))
    double = _by_name(_build(raw_gap=2.0))
    for name, outcome in single.items():
        assert double[name].payoff_estimate == pytest.approx(2.0 * outcome.payoff_estimate)
        assert double[name].probability == outcome.probability


def test_the_sign_of_the_gap_does_not_change_the_distribution() -> None:
    """The distribution is the *magnitude* of the mispricing; the trade's
    direction is a separate field on ``TradeIdea``. A negative gap therefore
    yields the same distribution, which is why ``abs`` is correct here rather
    than a defect."""
    positive = _build(raw_gap=1.0)
    negative = _build(raw_gap=-1.0)
    assert [o.payoff_estimate for o in positive] == [o.payoff_estimate for o in negative]
    assert [o.probability for o in positive] == [o.probability for o in negative]


def test_the_tail_loses_more_than_the_whole_mispricing() -> None:
    """The asymmetry the distribution exists to expose: the smallest probability
    carries the largest loss, and that loss exceeds the entire gap."""
    distribution = _by_name(_build())
    tail = distribution["tail_adverse_surprise"]
    base = distribution["base_case_gap_closes_as_modeled"]
    assert tail.probability < base.probability
    assert abs(tail.payoff_estimate) > abs(base.payoff_estimate)


# ---------------------------------------------------------------------------
# Defect 3 — the class collision (O-51)
# ---------------------------------------------------------------------------


def test_the_thesis_layer_scenario_outcome_is_the_models_layer_one() -> None:
    """THE COLLISION. Two structurally different classes carried this one name;
    ``mypy --strict`` accepted both because both are types, ``ruff`` saw a legal
    name in both modules, and a test importing one of them saw nothing wrong.
    D-057 recorded it as O-51; this asserts identity, which is the only
    assertion that can tell a re-export from a redeclaration."""
    from macro_engine.models import probability as models_probability
    from macro_engine.thesis_layer import schemas as thesis_schemas

    assert thesis_schemas.ScenarioOutcome is models_probability.ScenarioOutcome, (
        "the thesis layer must RE-EXPORT the models-layer class, not declare its "
        "own — a producer that cannot hand its output to its own consumer is not "
        "a producer (O-51)"
    )


def test_the_distribution_is_consumable_by_the_kelly_contract() -> None:
    """The producer's output must be the class the consumer declares. This is
    what the collision made impossible: ``KellyInputs`` raised
    ``Input should be a valid dictionary or instance of ScenarioOutcome`` — a
    message naming a class BOTH objects claimed to be.

    Asserted on the error TYPES rather than the message: the message embeds the
    input repr, which contains the word "scenarios" whatever went wrong.

    **Updated by D-064, and the update is itself a finding.** This test was
    written against a ``KellyInputs`` whose ``payoff_unit`` carried a
    **default**, so it asserted ``literal_error`` — the type refusing the bp
    declaration — while ``limits`` was deliberately omitted. D-064 made
    ``payoff_unit`` **required**, so an omitted ``limits`` now surfaces first
    (as ``missing``) and the old assertion fails.

    That failure is worth keeping in the record: the test **could not pass
    unless the field was optional**, which is a second, independent
    demonstration that the default was load-bearing rather than decorative. It
    is now asserted in the direction that matters — the two entries that must
    be **refused** are refused, and the CLASS objection is absent — with
    ``limits`` supplied so the *unit* is the thing under test.
    """
    from macro_engine.portfolio.risk_budget import KellyInputs, RiskLimits

    distribution = _build()
    limits = RiskLimits.from_settings()

    with pytest.raises(ValidationError) as excinfo:
        # The unit is the one the arithmetic refuses. Everything else is valid,
        # so the ONLY objection can be the unit.
        KellyInputs(
            scenarios=distribution,
            payoff_unit="bp_pnl_proxy",
            limits=limits,
        )
    kinds = {error["type"] for error in excinfo.value.errors()}
    assert "model_type" not in kinds, (
        "the scenarios must no longer be the wrong CLASS — that was O-51. "
        f"Remaining objections: {kinds}"
    )
    assert "value_error" in kinds, (
        "the only remaining objection should be the UNIT (O-50 by design), and "
        f"it is a named validator rather than the type; got {kinds}"
    )

    # And the omission path, which is the half D-064 added: a caller who
    # supplies NO unit gets no unit. Before D-064 this same call SUCCEEDED and
    # returned `fraction_of_capital` for a `bp_pnl_proxy` distribution.
    with pytest.raises(ValidationError) as missing:
        KellyInputs(  # type: ignore[call-arg]
            scenarios=distribution,
            limits=limits,
        )
    assert {e["type"] for e in missing.value.errors()} == {"missing"}, (
        "the unit must be DECLARED, not assumed on the caller's behalf — the "
        "default is what let a bp distribution be sized as a fraction of capital"
    )


def test_no_two_top_level_classes_share_a_name() -> None:
    """O-51's own recorded remedy: *"a test that enumerates top-level class names
    across the package and asserts uniqueness, which is mechanical and would have
    caught this one."*

    The allow-list is **exactly** the known-open collision, and its size is
    asserted — so a NEW collision fails here, and closing the listed one without
    updating this test also fails here.
    """
    root = Path(__file__).resolve().parents[2] / "src" / "macro_engine"
    declarations: dict[str, list[str]] = {}
    for path in sorted(root.rglob("*.py")):
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.ClassDef):
                declarations.setdefault(node.name, []).append(
                    str(path.relative_to(root)).replace("\\", "/")
                )

    duplicated = {name: where for name, where in declarations.items() if len(where) > 1}

    #: **Empty**, and that is a stronger statement than a populated set: every
    #: collision is closed. D-064 closed both — ``ScenarioOutcome`` (O-51) and
    #: ``MarketPricingGap`` (O-71) — because in each case a producer in the models
    #: layer could not feed a consumer that expected the other declaration. An
    #: entry here is a defect, not an exemption; the earlier draft of this test
    #: listed ``MarketPricingGap`` as "known open" and that turned out to be
    #: wrong for exactly the reason the collision was: the function under test
    #: takes a gap, and the canonical producer returned the other class.
    known_open: set[str] = set()

    assert set(duplicated) == known_open, (
        f"top-level class names are no longer unique: {duplicated}. O-51's remedy "
        f"is this test; a new collision must be fixed or recorded, not absorbed."
    )


# ---------------------------------------------------------------------------
# Defect 4 — the gap's unit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("unit", ["bp", "basis_points", "", "fraction"])
def test_a_gap_in_unknown_units_is_refused(unit: str) -> None:
    """§16.4 multiplies by 100 unconditionally, so an already-basis-point gap is
    scaled by 100 silently — D-054's 100x class. A unit this function cannot
    convert is a unit it must not guess."""
    with pytest.raises(ValueError, match="cannot convert"):
        _build(unit=unit)


def test_the_percent_unit_is_accepted_and_converted() -> None:
    """1% = 100bp, so a +1.00% gap pays 100 bp in the base case."""
    distribution = _by_name(_build(unit="%", raw_gap=1.0))
    assert distribution["base_case_gap_closes_as_modeled"].payoff_estimate == pytest.approx(100.0)


def test_the_conversion_factor_is_read_from_config() -> None:
    """Perturbed to a value no literal could produce, so a hardcoded 100 cannot
    pass (D-050)."""
    leaf = get_settings().scenario_distribution.percent_to_bp
    original = leaf.value
    object.__setattr__(leaf, "value", 250.0)
    try:
        distribution = _by_name(_build(raw_gap=1.0))
        assert distribution["base_case_gap_closes_as_modeled"].payoff_estimate == pytest.approx(
            250.0
        )
    finally:
        object.__setattr__(leaf, "value", original)


# ---------------------------------------------------------------------------
# The two caller-error guards
# ---------------------------------------------------------------------------


def test_a_gap_inside_the_noise_floor_is_refused() -> None:
    """§16.2's Q6 routes ``not is_meaningful`` to ``no_trade_thesis`` BEFORE Q10.
    A distribution over a sub-noise-floor gap is the false-confidence failure
    Module 12.2 exists to prevent, so reaching here is a skipped step, not a
    distribution."""
    with pytest.raises(ValueError, match="skipped Q6"):
        _build(is_meaningful=False)


def test_a_zero_gap_is_refused() -> None:
    """``is_meaningful`` is a caller-set field, not a derived one, so
    ``is_meaningful=True`` with ``raw_gap=0.0`` is constructible — and would
    produce four outcomes that differ only in their probabilities."""
    with pytest.raises(ValueError, match="degenerate"):
        _build(raw_gap=0.0)


def test_the_two_guards_are_distinguishable() -> None:
    """Both raise ``ValueError``; the messages must say which one fired, or a
    caller cannot act on either."""
    with pytest.raises(ValueError) as meaningless:
        _build(is_meaningful=False)
    with pytest.raises(ValueError) as degenerate:
        _build(raw_gap=0.0)
    assert "skipped Q6" in str(meaningless.value)
    assert "degenerate" in str(degenerate.value)


# ---------------------------------------------------------------------------
# The unit disclosure (O-50's producer half)
# ---------------------------------------------------------------------------


def test_every_outcome_declares_the_proxy_unit() -> None:
    """The distribution is a **proxy**, and says so. ``apply_fractional_kelly``
    accepts only ``fraction_of_capital``, so a ``bp_pnl_proxy`` set is not
    Kelly-sizable — a fact about the distribution, not an error in it."""
    assert {outcome.unit for outcome in _build()} == {"bp_pnl_proxy"}


def test_the_payoff_unit_vocabulary_is_declared_and_agrees_with_the_mirror() -> None:
    """A ``Literal`` is not runtime-enforced, so a value assertion cannot see a
    member removed from the type (D-054)."""
    assert set(get_args(PayoffUnit)) == {"bp_pnl_proxy", "fraction_of_capital"}


def test_the_payoff_unit_default_is_the_proxy() -> None:
    """``ScenarioOutcome.unit`` defaults to ``bp_pnl_proxy``, which is what the
    thesis layer's duplicate used to declare and what §16.4's sample assumes."""
    assert ScenarioOutcome(name="x", probability=0.5, payoff_estimate=1.0).unit == "bp_pnl_proxy"


# ---------------------------------------------------------------------------
# The config constraint O-41's shape
# ---------------------------------------------------------------------------


def test_the_remaining_shares_must_sum_to_one() -> None:
    """The one constraint three leaves share. Without it the four published
    probabilities sum to ``base + (1 - base) * S`` and ``S != 1`` is invisible in
    every leaf while making the distribution invalid."""
    from macro_engine.config import ScenarioDistributionSettings

    settings = get_settings().scenario_distribution
    leaf = settings.remaining_share_tail
    original = leaf.value
    object.__setattr__(leaf, "value", 0.5)
    try:
        with pytest.raises(ValidationError, match="sum to"):
            ScenarioDistributionSettings.model_validate(settings.model_dump())
    finally:
        object.__setattr__(leaf, "value", original)


def test_every_base_probability_is_read_from_config() -> None:
    """Perturbed per verdict, so a hardcoded 0.55/0.45/0.30 cannot pass."""
    settings = get_settings().scenario_distribution
    leaves = {
        ConvergenceClassification.HIGH: settings.base_probability_high,
        ConvergenceClassification.MEDIUM: settings.base_probability_medium,
        ConvergenceClassification.LOW: settings.base_probability_low,
    }
    for verdict, leaf in leaves.items():
        original = leaf.value
        object.__setattr__(leaf, "value", 0.111)
        try:
            assert _build(verdict)[0].probability == pytest.approx(0.111)
        finally:
            object.__setattr__(leaf, "value", original)


def test_every_payoff_multiple_is_read_from_config() -> None:
    """The tail multiple is the one a hardcoded literal would hide, because it is
    the only negative with a magnitude above 1."""
    leaf = get_settings().scenario_distribution.payoff_multiple_tail
    original = leaf.value
    object.__setattr__(leaf, "value", -7.0)
    try:
        distribution = _by_name(_build(raw_gap=1.0))
        assert distribution["tail_adverse_surprise"].payoff_estimate == pytest.approx(-700.0)
    finally:
        object.__setattr__(leaf, "value", original)


# ---------------------------------------------------------------------------
# Defect 5 — the distribution is DIRECTION-BLIND (D-064, found by the live check)
# ---------------------------------------------------------------------------


def test_the_distribution_is_direction_blind() -> None:
    """The sign of the gap never reaches the distribution — measured, not assumed.

    ``build_scenario_distribution`` takes ``abs(gap.raw_gap)`` and never reads
    ``gap.direction``, so a **+1%** gap and a **-1%** gap produce byte-identical
    payoffs. The distribution is a *magnitude* distribution carrying no sign.

    This was found by D-064's **live check**, not by a unit test, and only
    because the live canonical gap happened to be **negative** (-1.00%: the model
    below the market, a tightening bias) while every fixture in this file uses
    ``_RAW_GAP = +1.0``. A fixture suite written entirely on one sign cannot see
    a sign-independence defect — the same shape as D-063's finding #4, where the
    model §20.15 names is direction-blind, and D-062's golden case that was exact
    by construction.

    What it means for a consumer: a branch named
    ``thesis_invalidated_reversal`` paying -60bp reads as a loss for a LONG
    position, but the same number is the loss for a SHORT only once the sign of
    the trade is known — and the trade is **not an input here**. The sign lives
    in ``gap.direction`` and in whichever instrument the thesis selects; this
    function publishes neither.

    This is recorded as a **disclosure, not a repair**: Section 16.4's sample
    states no direction either, and inventing one would mean choosing a signed
    convention for a function whose unit is a proxy. The test pins the property
    so the omission is a documented boundary rather than an unnoticed one.
    """
    positive = _by_name(_build(raw_gap=1.0))
    negative = _by_name(_build(raw_gap=-1.0))

    for name in positive:
        assert positive[name].payoff_estimate == pytest.approx(negative[name].payoff_estimate), (
            f"{name}: the payoff changed with the sign of the gap. If this is "
            f"intended, the direction-blindness note in the module docstring and "
            f"in OPEN_ISSUES is stale and must be updated with it"
        )

    # The probabilities are sign-independent too, which is the stronger claim:
    # the whole distribution is a function of |raw_gap| and the verdict.
    for name in positive:
        assert positive[name].probability == pytest.approx(negative[name].probability)

    # And the sign IS available — just not here. Asserting the gap exposes it on
    # its own object is what makes this a boundary rather than a loss of
    # information.
    assert _gap(raw_gap=-1.0).direction == "model_below_market"
    assert _gap(raw_gap=1.0).direction == "model_above_market"


# ---------------------------------------------------------------------------
# Section 25 of the economic-integrity directive: scenario probabilities must
# be REAL or the distribution is unavailable for sizing.
# ---------------------------------------------------------------------------


class TestScenarioDistributionStatus:
    """§25 — ``SCENARIO_DISTRIBUTION_UNAVAILABLE`` and the sizing prohibition.

    The directive: *"Scenario probabilities must be real; if they cannot be
    justified, return ``SCENARIO_DISTRIBUTION_UNAVAILABLE`` and MUST NOT
    calculate Kelly position sizing."*

    These tests pin three things: that the status vocabulary exists and is read
    from config (not hardcoded), that today's config classifies every
    distribution as UNAVAILABLE, and that a calibrated config would lift it —
    which is the falsifiable half, because a gate that can never open is a gate
    nobody can trust.
    """

    def test_the_configured_probabilities_are_not_calibrated_today(self) -> None:
        """§16.4's literals are ``uncalibrated_illustrative``, so this is False.

        If this ever fails, the scenarios became real and Section 25's
        prohibition should be revisited deliberately rather than silently
        lifted — which is exactly why the fact is asserted rather than assumed.
        """
        from macro_engine.thesis_layer.scenarios import scenario_probabilities_are_calibrated

        assert scenario_probabilities_are_calibrated() is False

    def test_a_distribution_from_illustrative_probabilities_is_unavailable(self) -> None:
        from macro_engine.models.probability import scenario_distribution_status

        status = scenario_distribution_status(_build(), probabilities_are_calibrated=False)

        assert status == "SCENARIO_DISTRIBUTION_UNAVAILABLE"

    def test_a_calibrated_distribution_would_be_marked_calibrated(self) -> None:
        """The falsifiable half: the gate opens when the config is calibrated.

        Without this the UNAVAILABLE verdict could be produced by a hardcoded
        ``return "SCENARIO_DISTRIBUTION_UNAVAILABLE"`` and the test would still
        pass — so this is what makes the first test meaningful.
        """
        from macro_engine.models.probability import scenario_distribution_status

        status = scenario_distribution_status(_build(), probabilities_are_calibrated=True)

        assert status == "calibrated"

    def test_an_empty_distribution_is_empty_no_trade_whatever_the_calibration(self) -> None:
        """A verdict that cannot carry a thesis has nothing to calibrate.

        ``empty`` wins over the calibration fact, because "no distribution" and
        "an unsizable distribution" are different facts and a reader needs both.
        """
        from macro_engine.models.probability import scenario_distribution_status

        for calibrated in (True, False):
            assert (
                scenario_distribution_status([], probabilities_are_calibrated=calibrated)
                == "empty_no_trade"
            )

    def test_the_status_vocabulary_is_exactly_three_members(self) -> None:
        """A closed vocabulary, typed — so a typo cannot masquerade as a state."""
        from macro_engine.models.probability import ScenarioDistributionStatus

        assert set(get_args(ScenarioDistributionStatus)) == {
            "calibrated",
            "SCENARIO_DISTRIBUTION_UNAVAILABLE",
            "empty_no_trade",
        }

    def test_the_calibration_fact_comes_from_config_not_a_literal(self) -> None:
        """D-035: the status must be read from the leaves, not restated.

        Proven by mutating a leaf's ``calibration_status`` in the loaded settings
        and observing the predicate flip, then restoring it. A hardcoded
        ``return False`` would fail this.
        """
        from macro_engine.thesis_layer.scenarios import scenario_probabilities_are_calibrated

        settings = get_settings()
        leaf = settings.scenario_distribution.base_probability_high
        original = leaf.calibration_status
        try:
            leaf.calibration_status = "fitted_assumption"
            assert scenario_probabilities_are_calibrated() is False, (
                "one promoted leaf out of six left the distribution uncalibrated "
                "— the predicate must require ALL leaves to be trustworthy"
            )
            settings.scenario_distribution.base_probability_medium.calibration_status = (
                "fitted_assumption"
            )
            settings.scenario_distribution.base_probability_low.calibration_status = (
                "fitted_assumption"
            )
            settings.scenario_distribution.remaining_share_partial_close.calibration_status = (
                "fitted_assumption"
            )
            settings.scenario_distribution.remaining_share_reversal.calibration_status = (
                "fitted_assumption"
            )
            settings.scenario_distribution.remaining_share_tail.calibration_status = (
                "fitted_assumption"
            )
            assert scenario_probabilities_are_calibrated() is True, (
                "with every probability leaf promoted the predicate must flip — a "
                "hardcoded False would leave this red"
            )
        finally:
            leaf.calibration_status = original
            for name in (
                "base_probability_medium",
                "base_probability_low",
                "remaining_share_partial_close",
                "remaining_share_reversal",
                "remaining_share_tail",
            ):
                getattr(
                    settings.scenario_distribution, name
                ).calibration_status = "uncalibrated_illustrative"
        assert scenario_probabilities_are_calibrated() is False, "restore failed"
