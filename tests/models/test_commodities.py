"""Tests for Module 10's ``oil_balance_signal`` and ``gold_driver_attribution``.

Every fixture here is DERIVED from the config leaves rather than hardcoded, so a
leaf change moves the test with it instead of silently testing a stale number
(the ``C6b`` class, D-031). The boundary cases sit exactly ON the model's
thresholds so a mutant that flips ``>`` to ``>=`` cannot survive a fixture set
that never touches it.

The oil model is the simplest in the repository — one subtraction and a sign
flip — so the decisions a future edit is most likely to break are exactly the
ones asserted here:

* the **sign convention** (a draw tightens),
* the **rounding** to the config-declared precision,
* the **confidence PRODUCT** (not ``min()`` — the D-118/D-119 rule),
* the **refusal** when a leg is absent,
* the **result contract** (unit, direction, family, both inputs named), and
* the **disclosure** that discriminates a fetched leg from a supplied one.

The gold model (Appendix D, D-121) adds a *classification* on top of that shape,
so its tests focus on what a classifier can get wrong:

* the **layer ORDER** (Appendix D appends primary → structural → acute, and the
  dominant layer is the FIRST active one — not "the last", not "the strongest"),
* the **threshold boundary** (``abs(change) > threshold``, tested ON the value),
* the **trend vocabulary** (a typo must be REFUSED, not read as "layer inactive"),
* the **independence count** (two FRED legs are ONE provider — the disclosure
  must not inflate confidence from a leg count),
* the **CB-leg degradation** (absent is NORMAL for that layer and must NOT
  raise, unlike the other two), and
* the **``none_identified`` reading** (a real reading, not an error).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from macro_engine.config import (
    CalibratedValue,
    GoldDriverSettings,
    MetalsComplexSettings,
    OilBalanceSettings,
    get_settings,
)
from macro_engine.data_layer.commodities_client import (
    ALUMINUM_SYMBOL,
    COPPER_SYMBOL,
    IRON_ORE_SYMBOL,
    CommodityReadError,
    MetalChangeReading,
)
from macro_engine.models.commodities import (
    GoldDriverInputs,
    MetalsComplexInputs,
    OilBalanceInputs,
    gold_driver_attribution,
    metals_complex_divergence,
    oil_balance_signal,
)
from macro_engine.models.contracts import (
    ConfidenceInputs,
    EvidenceSourceFamily,
    ModelResult,
    compute_confidence,
)


def _inputs(**overrides: object) -> OilBalanceInputs:
    """An inputs object with BOTH values SUPPLIED, so no network is used.

    The supplied case is the right default for a unit test: it exercises the
    model's own arithmetic without depending on a live response. The fetch path
    has its own tests below, and the live check exercises it end to end.
    """
    base: dict[str, object] = {
        "inventory_change_weekly": -5000.0,
        "opec_spare_capacity_proxy": 1.5,
    }
    base.update(overrides)
    return OilBalanceInputs(**base)  # type: ignore[arg-type]


def _value(result: ModelResult, key: str) -> object:
    """Read one key out of the published ``value`` dict, typed for mypy.

    ``ModelResult.value`` is a wide union (Section 22.9), so every ``["key"]``
    access needs narrowing before a comparison. Keeping the narrowing in one
    place avoids scattering ``# type: ignore`` comments across the file, and an
    assertion failure here is a real contract break, not a typing annoyance.
    """
    value = result.value
    assert isinstance(value, dict), f"value is {type(value).__name__}"
    return value[key]


def _tightness(result: ModelResult) -> float:
    item = _value(result, "tightness")
    assert isinstance(item, float)
    return item


def _deviation(result: ModelResult) -> float:
    item = _value(result, "inventory_seasonal_deviation_thousand_barrels")
    assert isinstance(item, float)
    return item


def _spare(result: ModelResult) -> float:
    item = _value(result, "opec_spare_capacity_mbd")
    assert isinstance(item, float)
    return item


# --- the sign convention (Section 6.8's arithmetic) ---------------------------


def test_a_draw_tightens_the_market() -> None:
    """``tightness = -deviation``: a stock DRAW (negative deviation) is positive.

    This is the reference implementation's own convention ("draw = tightening")
    and the single most likely line to be inverted by a "clarifying" edit.
    """
    result = oil_balance_signal(_inputs(inventory_change_weekly=-5000.0))
    assert _tightness(result) == 5000.0
    assert result.direction == "tightening"


def test_a_build_loosens_the_market() -> None:
    """The mirror: a stock BUILD (positive deviation) is a negative tightness."""
    result = oil_balance_signal(_inputs(inventory_change_weekly=5000.0))
    assert _tightness(result) == -5000.0
    assert result.direction == "loosening"


def test_a_zero_deviation_is_not_called_tightening() -> None:
    """Exactly on the seasonal norm is LOOSENING by the strict ``> 0`` test.

    The boundary: the reference writes ``'tightening' if tightness > 0 else
    'loosening'``, so a zero reading is loosening. This fixture sits exactly on
    the boundary so a mutant changing ``>`` to ``>=`` is caught — a fixture set
    that never touches zero could not distinguish the two.
    """
    result = oil_balance_signal(_inputs(inventory_change_weekly=0.0))
    assert _tightness(result) == 0.0
    assert result.direction == "loosening"


# --- the rounding (config-declared, not a literal) ----------------------------


def test_the_tightness_is_rounded_to_the_configured_decimals() -> None:
    """The precision is a leaf, so the test follows it rather than pinning 2.

    A value with more than ``value_decimals`` decimals must come back rounded to
    that many places. DERIVED from the leaf so a change to it moves this test.
    """
    decimals = get_settings().oil_balance.value_decimals
    result = oil_balance_signal(_inputs(inventory_change_weekly=-1234.56789))
    assert _tightness(result) == round(1234.56789, decimals)
    # The deviation is rounded the same way.
    assert _deviation(result) == round(-1234.56789, decimals)


def test_the_rounding_uses_the_leaf_not_a_hardcoded_two(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Perturb the LEAF away from the shipped ``2`` (D-050 — the ``M3b`` remedy).

    The shipped leaf is ``2``, so ``round(tightness, 2)`` in the body is
    byte-identical to ``round(tightness, decimals)`` — a test that only feeds a
    ``2``-decimal leaf cannot tell them apart, which is how ``M3b`` survived the
    first sweep. Moving the leaf to ``4`` and asserting the body FOLLOWS it is
    what makes the accessor load-bearing: the hardcoded mutant now publishes two
    decimals where the test demands four, and dies.

    The previous shape-only form (``len(frac) <= decimals``) is subsumed: at
    ``decimals == 4`` a ``2``-decimal result still satisfies ``<= 4``, so the
    assertion had to move from an upper BOUND to an EXACT match.
    """
    monkeypatch.setattr(
        "macro_engine.config.OilBalanceSettings.value_decimals",
        property(lambda self: 4),
    )
    result = oil_balance_signal(_inputs(inventory_change_weekly=-1.987654321))
    assert _tightness(result) == round(1.987654321, 4)
    assert _tightness(result) != round(1.987654321, 2)
    assert _deviation(result) == round(-1.987654321, 4)


# --- confidence: two producers, both load-bearing -----------------------------


def test_confidence_is_the_product_of_the_computed_half_and_the_cap() -> None:
    """The published confidence equals the cap TIMES a computed factor < 1.

    Proves both halves are engaged: if the cap were the whole answer, confidence
    would equal the cap exactly; if the computed half were dead code, the value
    would be identical for fetched and supplied inputs (the next test).
    """
    cap = get_settings().oil_balance.reliability_value
    result = oil_balance_signal(_inputs())
    assert 0.0 < result.confidence < cap


def test_confidence_is_not_the_cap_alone() -> None:
    """A strict inequality — the computed half is multiplied in, so it is < cap.

    A mutant that published ``oil.reliability_value`` directly (dropping the
    computed factor) would make this equality fail.
    """
    oil = get_settings().oil_balance
    result = oil_balance_signal(_inputs())
    supplied_computed = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=True,
            is_heuristic_not_calibrated=not oil.reliability_cap_is_calibrated,
            source_independence_count=0,
            depends_on_unobservable=False,
        )
    )
    assert result.confidence == pytest.approx(supplied_computed * oil.reliability_value, rel=1e-12)


def test_a_fetched_run_reports_higher_confidence_than_a_fully_supplied_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE TEST THAT READS THE OTHER HALF (D-118's rule).

    The computed half is HIGHER with both legs fetched than with none. Under
    ``min()`` both runs would publish the cap and this assertion would fail —
    which is precisely why the combining rule is MULTIPLICATION. If this test is
    ever "fixed" by relaxing the comparison, the model has lost the only evidence
    that fetching is worth more than typing.
    """
    oil = get_settings().oil_balance
    _stub_fetches(monkeypatch, deviation=-5000.0, spare=1.5)
    fetched = oil_balance_signal(OilBalanceInputs())
    supplied = oil_balance_signal(_inputs())
    assert fetched.confidence > supplied.confidence
    assert fetched.confidence == pytest.approx(
        compute_confidence(
            ConfidenceInputs(
                data_quality_flags_present=False,
                is_heuristic_not_calibrated=not oil.reliability_cap_is_calibrated,
                source_independence_count=2,
                depends_on_unobservable=False,
            )
        )
        * oil.reliability_value,
        rel=1e-12,
    )


def test_one_fetched_leg_leaves_the_quality_flag_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One leg fetched is still an incomplete input set, so the flag stays.

    The negative control for the two-leg case: it proves the ``< 2`` comparison
    is doing work rather than being effectively constant.
    """
    oil = get_settings().oil_balance
    _stub_fetches(monkeypatch, deviation=-5000.0, spare=None)
    result = oil_balance_signal(OilBalanceInputs(opec_spare_capacity_proxy=1.5))
    assert result.confidence == pytest.approx(
        compute_confidence(
            ConfidenceInputs(
                data_quality_flags_present=True,
                is_heuristic_not_calibrated=not oil.reliability_cap_is_calibrated,
                source_independence_count=1,
                depends_on_unobservable=False,
            )
        )
        * oil.reliability_value,
        rel=1e-12,
    )


# --- the refusal --------------------------------------------------------------


def test_an_unavailable_inventory_with_no_supplied_value_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A leg that cannot be fetched and is not supplied must REFUSE, not degrade."""
    _stub_fetches(monkeypatch, deviation=None, spare=1.5)
    with pytest.raises(ValueError, match="inventory_change_weekly"):
        oil_balance_signal(OilBalanceInputs())


def test_an_unavailable_spare_leg_with_no_supplied_value_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_fetches(monkeypatch, deviation=-5000.0, spare=None)
    with pytest.raises(ValueError, match="opec_spare_capacity_proxy"):
        oil_balance_signal(OilBalanceInputs())


def test_the_refusal_names_both_missing_legs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The message must name every missing leg, not just the first."""
    _stub_fetches(monkeypatch, deviation=None, spare=None)
    with pytest.raises(ValueError, match=r"inventory_change_weekly.*opec_spare_capacity_proxy"):
        oil_balance_signal(OilBalanceInputs())


def test_supplying_one_leg_avoids_the_refusal_for_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Supplying the fetchable-but-failed leg lets the model compute."""
    _stub_fetches(monkeypatch, deviation=None, spare=1.5)
    result = oil_balance_signal(OilBalanceInputs(inventory_change_weekly=-100.0))
    assert _tightness(result) == 100.0


def test_a_fully_supplied_run_never_reaches_the_fetchers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The negative control: supplied values must short-circuit the fetch.

    If the model fetched anyway, a caller's explicit number would be ignored —
    and this test proves the ``is None`` guards are what prevent that.
    """
    calls: list[str] = []

    def _should_not_be_called() -> tuple[float | None, str]:
        calls.append("called")
        return 0.0, "SHOULD NOT HAVE BEEN CALLED"

    monkeypatch.setattr(
        "macro_engine.models.commodities._fetch_inventory_deviation", _should_not_be_called
    )
    monkeypatch.setattr(
        "macro_engine.models.commodities._fetch_spare_capacity", _should_not_be_called
    )
    oil_balance_signal(_inputs())
    assert calls == []


# --- the input guards ---------------------------------------------------------


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_inventory_deviation_is_refused(bad: float) -> None:
    """A nan silently fails every comparison — the D-078 class."""
    with pytest.raises(ValidationError, match="inventory_change_weekly"):
        OilBalanceInputs(inventory_change_weekly=bad, opec_spare_capacity_proxy=1.0)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_spare_capacity_is_refused(bad: float) -> None:
    with pytest.raises(ValidationError, match="opec_spare_capacity_proxy"):
        OilBalanceInputs(inventory_change_weekly=-1.0, opec_spare_capacity_proxy=bad)


def test_a_negative_deviation_is_allowed() -> None:
    """A draw is a legitimate signed reading and must not be clamped."""
    obj = OilBalanceInputs(inventory_change_weekly=-9999.0)
    assert obj.inventory_change_weekly == -9999.0


def test_a_negative_spare_capacity_is_allowed_but_warned() -> None:
    """A negative spare reading is disclosed and warned, never silently flipped.

    A measurement artefact or a genuine over-supply can produce a small negative;
    the model reports what the series says so the anomaly is visible rather than
    repaired (Section 21.0 rule 2).
    """
    result = oil_balance_signal(_inputs(opec_spare_capacity_proxy=-0.3))
    assert _spare(result) == -0.3
    assert any("negative" in w for w in result.warnings)


def test_extra_input_fields_are_refused() -> None:
    with pytest.raises(ValidationError):
        OilBalanceInputs(  # type: ignore[call-arg]
            inventory_change_weekly=-1.0,
            opec_spare_capacity_proxy=1.0,
            surprise=1.0,
        )


# --- the buffer warning -------------------------------------------------------


def test_the_buffer_warning_fires_at_or_above_the_threshold() -> None:
    """DERIVED from the leaf, so a threshold change moves the test with it."""
    threshold = get_settings().oil_balance.tight_spare_threshold_value
    at = oil_balance_signal(_inputs(opec_spare_capacity_proxy=threshold))
    assert any("buffer" in w for w in at.warnings)


def test_the_buffer_warning_does_not_fire_below_the_threshold() -> None:
    """The negative control: proves the comparison is not effectively constant."""
    threshold = get_settings().oil_balance.tight_spare_threshold_value
    below = oil_balance_signal(_inputs(opec_spare_capacity_proxy=threshold - 0.5))
    assert not any("buffer" in w for w in below.warnings)


# --- source family ------------------------------------------------------------


def test_a_fully_supplied_run_is_tagged_manual_assessment() -> None:
    result = oil_balance_signal(_inputs())
    assert result.source_family == EvidenceSourceFamily.MANUAL_ASSESSMENT


def test_a_fetched_run_is_tagged_market_commodity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run that fetched at least one leg must be tagged MARKET_COMMODITY."""
    _stub_fetches(monkeypatch, deviation=-5000.0, spare=1.5)
    result = oil_balance_signal(OilBalanceInputs())
    assert result.source_family == EvidenceSourceFamily.MARKET_COMMODITY


# --- the disclosure discriminates ---------------------------------------------


def test_a_supplied_leg_is_disclosed_as_supplied() -> None:
    """A caller-typed number must never read like a fetched one (D-117)."""
    result = oil_balance_signal(_inputs())
    assert all("SUPPLIED BY THE CALLER" in p for p in result.data_provenance)
    assert not any(p.startswith("FETCHED") for p in result.data_provenance)


def test_a_fetched_leg_is_disclosed_as_fetched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_fetches(monkeypatch, deviation=-5000.0, spare=1.5)
    result = oil_balance_signal(OilBalanceInputs())
    assert all(p.startswith("FETCHED") for p in result.data_provenance)


# --- the result contract ------------------------------------------------------


def test_the_result_carries_its_contract_fields() -> None:
    result = oil_balance_signal(_inputs())
    assert result.model_name == "oil_balance_signal"
    assert result.country == "us"
    assert result.unit == "thousand_barrels_seasonal_deviation"
    assert set(result.inputs_used) == {
        "inventory_change_weekly",
        "opec_spare_capacity_proxy",
    }
    assert result.assumptions  # the deviation/vintage caveats travel


def test_both_inputs_are_named_as_used() -> None:
    """The §6.8 body named only one of its two declared inputs (D-037's shape).

    A declared-but-unnamed field lets a reader wonder whether it was consumed;
    this asserts both are named.
    """
    result = oil_balance_signal(_inputs())
    assert "inventory_change_weekly" in result.inputs_used
    assert "opec_spare_capacity_proxy" in result.inputs_used


def test_the_value_carries_all_three_readings() -> None:
    """The reading, the deviation it came from, and the spare figure travel together."""
    result = oil_balance_signal(
        _inputs(inventory_change_weekly=-1234.0, opec_spare_capacity_proxy=2.5)
    )
    assert _tightness(result) == 1234.0
    assert _deviation(result) == -1234.0
    assert _spare(result) == 2.5


def test_the_trade_signal_warning_is_always_present() -> None:
    """The scoping warning is the function's reason for existing and never drops.

    Section 6.8's whole point is that this is a TRANSMISSION input, not a trade
    signal; a result without that warning would let a consumer misread it.
    """
    result = oil_balance_signal(_inputs())
    assert any("standalone trade signal" in w for w in result.warnings)


# --- the config block: accessors and validators (G1-G4) -----------------------


def _oil_settings_with(**values: object) -> OilBalanceSettings:
    """A settings object seeded from the SHIPPED block (D-114's structural fix).

    The base is the shipped block and only the named leaves are overridden, so a
    new leaf cannot make this fixture stale.
    """
    base = dict(get_settings().oil_balance.model_dump())
    base.update(values)
    return OilBalanceSettings.model_validate(base)


def _calibrated(value: object) -> CalibratedValue:
    return CalibratedValue(value=value, calibration_status="uncalibrated_illustrative", note="test")


@pytest.mark.parametrize("sentinel", [0.17, 0.41])
def test_the_reliability_accessor_follows_a_perturbed_leaf(sentinel: float) -> None:
    """G1a: perturb the LEAF, not the literal (D-050 — the ``C6b`` remedy).

    The mutant returns ``0.4``, which is close to the shipped leaf (0.30), so a
    comparison against the shipped value would pass under it. Reading a
    PERTURBED leaf that differs from BOTH the shipped value and the mutant
    literal proves the accessor reads config.
    """
    perturbed = _oil_settings_with(reliability_cap=_calibrated(sentinel))
    assert perturbed.reliability_value == pytest.approx(sentinel)
    assert perturbed.reliability_value != 0.4


@pytest.mark.parametrize("sentinel", [3, 5])
def test_the_decimals_accessor_follows_a_perturbed_leaf(sentinel: int) -> None:
    """G2a: the decimals accessor reads the leaf, not the literal ``2``."""
    perturbed = _oil_settings_with(value_decimals_leaf=_calibrated(sentinel))
    assert perturbed.value_decimals == sentinel
    assert perturbed.value_decimals != 2


@pytest.mark.parametrize("sentinel", [1.25, 3.75])
def test_the_spare_threshold_accessor_follows_a_perturbed_leaf(sentinel: float) -> None:
    """G3a: the threshold accessor reads the leaf, not the literal ``2.0``."""
    perturbed = _oil_settings_with(tight_spare_threshold_mbd=_calibrated(sentinel))
    assert perturbed.tight_spare_threshold_value == pytest.approx(sentinel)
    assert perturbed.tight_spare_threshold_value != 2.0


@pytest.mark.parametrize("bad_decimals", [-1, -5])
def test_a_negative_decimals_leaf_is_refused(bad_decimals: int) -> None:
    """G4b: a negative ``ndigits`` makes ``round`` COARSEN the figure.

    Without this test the validator was replaced by ``if False:`` unnoticed; a
    negative leaf would silently publish a tightness rounded to tens or hundreds.
    """
    with pytest.raises(ValidationError, match="value_decimals"):
        _oil_settings_with(value_decimals_leaf=_calibrated(bad_decimals))


@pytest.mark.parametrize("bad_threshold", [-0.01, -2.0])
def test_a_negative_spare_threshold_is_refused(bad_threshold: float) -> None:
    """G4c: a negative threshold makes the buffer warning fire on EVERY reading.

    Spare capacity cannot be negative, so the threshold must be non-negative;
    otherwise the warning's vocabulary is dead (D-037's class).
    """
    with pytest.raises(ValidationError, match="tight_spare_threshold_mbd"):
        _oil_settings_with(tight_spare_threshold_mbd=_calibrated(bad_threshold))


@pytest.mark.parametrize("bad_cap", [-0.01, 1.01])
def test_a_cap_outside_the_unit_interval_is_refused(bad_cap: float) -> None:
    """G4a: the cap validator must FIRE on an out-of-range cap.

    ``ModelResult`` refuses a confidence outside [0, 1], so a leaf outside it
    would raise at the first call rather than at load.
    """
    with pytest.raises(ValidationError, match="reliability_cap"):
        _oil_settings_with(reliability_cap=_calibrated(bad_cap))


# --- helpers ------------------------------------------------------------------


def _stub_fetches(
    monkeypatch: pytest.MonkeyPatch,
    *,
    deviation: float | None,
    spare: float | None,
) -> None:
    """Patch the model's two fetch helpers to return fixed values.

    Patching the MODEL's private helpers (not the client) is what makes the
    model's own ``fetched_legs`` accounting and its source-family choice execute;
    the client has its own tests for the transport beneath these.
    """
    monkeypatch.setattr(
        "macro_engine.models.commodities._fetch_inventory_deviation",
        lambda: (deviation, "FETCHED — stub deviation"),
    )
    monkeypatch.setattr(
        "macro_engine.models.commodities._fetch_spare_capacity",
        lambda: (spare, "FETCHED — stub spare"),
    )


# =============================================================================
# ``gold_driver_attribution`` — Appendix D's three-layer framework (D-121)
# =============================================================================


def _gold_inputs(**overrides: object) -> GoldDriverInputs:
    """A gold inputs object with ALL THREE values SUPPLIED, so no network is used.

    Supplying all three is the right unit-test default for a *classifier*: it
    lets a test pin the exact layer combination it means to exercise. The fetch
    paths have their own tests below and the live check exercises them end to end.
    """
    base: dict[str, object] = {
        "real_yield_change_bp": 0.0,
        "central_bank_net_purchases_trend": "flat",
        "crisis_indicator": False,
    }
    base.update(overrides)
    return GoldDriverInputs(**base)  # type: ignore[arg-type]


def _layers(result: ModelResult) -> list[str]:
    item = _value(result, "active_layers")
    assert isinstance(item, list)
    return list(item)


def _dominant(result: ModelResult) -> str:
    item = _value(result, "dominant_layer")
    assert isinstance(item, str)
    return item


def _gold_change(result: ModelResult) -> float:
    item = _value(result, "real_yield_change_bp")
    assert isinstance(item, float)
    return item


def _stub_gold_fetches(
    monkeypatch: pytest.MonkeyPatch,
    *,
    change_bp: float | None,
    crisis: bool | None,
) -> None:
    """Patch the gold model's two fetch helpers to return fixed values.

    Patching the MODEL's private helpers (not the client) is what makes the
    model's own ``fetched_legs`` accounting and its source-family choice execute;
    the client has its own tests for the transport beneath these.
    """
    monkeypatch.setattr(
        "macro_engine.models.commodities._resolve_real_yield_change",
        lambda: (change_bp, "FETCHED — stub real-yield change"),
    )
    monkeypatch.setattr(
        "macro_engine.models.commodities._resolve_crisis_indicator",
        lambda: (crisis, "FETCHED — stub crisis indicator"),
    )


# --- the layer classification and its ORDER -----------------------------------


def test_an_inert_market_identifies_no_layer() -> None:
    """All three layers quiet is a READING, and must be ``none_identified``.

    Not an error, not an empty string, not a crash: the framework's honest
    output when nothing in it fired.
    """
    result = gold_driver_attribution(_gold_inputs())
    assert _dominant(result) == "none_identified"
    assert _layers(result) == []


def test_a_large_real_yield_move_fires_the_primary_layer() -> None:
    result = gold_driver_attribution(
        _gold_inputs(real_yield_change_bp=25.0, crisis_indicator=False)
    )
    assert _dominant(result) == "real_yield"
    assert _layers(result) == ["real_yield"]


def test_rising_cb_purchases_fire_the_structural_layer() -> None:
    result = gold_driver_attribution(_gold_inputs(central_bank_net_purchases_trend="rising"))
    assert _dominant(result) == "cb_diversification"
    assert _layers(result) == ["cb_diversification"]


def test_a_crisis_fires_the_acute_layer() -> None:
    result = gold_driver_attribution(_gold_inputs(crisis_indicator=True))
    assert _dominant(result) == "crisis_confidence"
    assert _layers(result) == ["crisis_confidence"]


def test_all_three_layers_fire_in_the_specifications_order() -> None:
    """THE ORDER TEST. Appendix D appends primary → structural → acute.

    The dominant layer is the FIRST active one, so when all three fire the
    mechanical real-yield channel is reported as dominant. A mutant that took
    ``layers[-1]`` or reordered the appends would change this list.
    """
    result = gold_driver_attribution(
        _gold_inputs(
            real_yield_change_bp=25.0,
            central_bank_net_purchases_trend="rising",
            crisis_indicator=True,
        )
    )
    assert _layers(result) == ["real_yield", "cb_diversification", "crisis_confidence"]
    assert _dominant(result) == "real_yield"


def test_the_primary_layer_wins_over_the_others_when_all_fire() -> None:
    """Stated separately from the list assertion because it is the TIE-BREAK.

    A reader is entitled to know that "dominant" means "first in the
    specification's order", not "most severe" or "most recent".
    """
    result = gold_driver_attribution(
        _gold_inputs(
            real_yield_change_bp=-40.0,
            central_bank_net_purchases_trend="rising",
            crisis_indicator=True,
        )
    )
    assert _dominant(result) == "real_yield"


def test_a_negative_real_yield_change_also_fires_the_primary_layer() -> None:
    """The layer tests ``abs(change)``, so a FALL fires it too.

    A mutant that dropped the ``abs()`` would pass the positive case and fail
    this one — which is the whole reason both directions are tested.
    """
    result = gold_driver_attribution(_gold_inputs(real_yield_change_bp=-25.0))
    assert _dominant(result) == "real_yield"


# --- the threshold boundary (ON the value) ------------------------------------


def test_a_change_exactly_on_the_threshold_does_not_fire() -> None:
    """Appendix D writes ``>``, not ``>=``, so the boundary itself is INERT.

    A fixture that sat strictly above the threshold would let a ``>`` → ``>=``
    mutant survive; this one sits exactly ON it and pins the operator.
    """
    threshold = get_settings().gold_driver.yield_change_threshold_bp
    result = gold_driver_attribution(_gold_inputs(real_yield_change_bp=threshold))
    assert _layers(result) == []


def test_a_change_just_above_the_threshold_fires() -> None:
    """The negative control for the boundary test above."""
    threshold = get_settings().gold_driver.yield_change_threshold_bp
    result = gold_driver_attribution(_gold_inputs(real_yield_change_bp=threshold + 0.1))
    assert _layers(result) == ["real_yield"]


def test_the_threshold_follows_the_leaf_not_a_hardcoded_ten(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-050 LEAF PERTURBATION: a change of 3 bp fires only if the leaf moved.

    The shipped leaf IS 10, so a test using 11 bp would pass against a
    hardcoded ``10`` as well as against the leaf (the ``M3b``/``C6b`` weak-test
    class). Perturbing the leaf to 2 makes the two distinguishable: 3 bp must
    now FIRE.
    """
    gold = _gold_settings_with(yield_change_threshold_materiality_bp=_calibrated(2.0))

    class _Settings:
        gold_driver = gold

    monkeypatch.setattr("macro_engine.models.commodities.get_settings", lambda: _Settings())
    result = gold_driver_attribution(_gold_inputs(real_yield_change_bp=3.0))
    assert _layers(result) == ["real_yield"]


def test_a_change_inside_a_perturbed_leaf_stays_inert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The negative control for the perturbation: 3 bp is inside a leaf of 5."""
    gold = _gold_settings_with(yield_change_threshold_materiality_bp=_calibrated(5.0))

    class _Settings:
        gold_driver = gold

    monkeypatch.setattr("macro_engine.models.commodities.get_settings", lambda: _Settings())
    result = gold_driver_attribution(_gold_inputs(real_yield_change_bp=3.0))
    assert _layers(result) == []


# --- inputs validation --------------------------------------------------------


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_real_yield_change_is_refused(bad: float) -> None:
    """A nan silently fails every comparison (D-078's class)."""
    with pytest.raises(ValidationError, match="real_yield_change_bp"):
        GoldDriverInputs(real_yield_change_bp=bad)


@pytest.mark.parametrize("bad", ["raise", "up", "Rising", "RISING", "", "flatish"])
def test_a_trend_outside_the_specifications_vocabulary_is_refused(bad: str) -> None:
    """A typo must be REFUSED, not read as "this layer is inactive".

    Appendix D matches the exact string ``== "rising"``, so an unrecognised value
    would silently drop the layer — a different claim from "the caller meant
    rising". ``"Rising"`` is included because the match is case-SENSITIVE.
    """
    with pytest.raises(ValidationError, match="central_bank_net_purchases_trend"):
        GoldDriverInputs(central_bank_net_purchases_trend=bad)


@pytest.mark.parametrize("good", ["rising", "flat", "falling"])
def test_every_permitted_trend_value_is_accepted(good: str) -> None:
    """The positive control for the vocabulary test — all three are legal."""
    assert (
        GoldDriverInputs(central_bank_net_purchases_trend=good).central_bank_net_purchases_trend
        == good
    )


def test_gold_extra_input_fields_are_refused() -> None:
    with pytest.raises(ValidationError):
        GoldDriverInputs(unknown_field=1)  # type: ignore[call-arg]


def test_a_flat_trend_does_not_fire_the_structural_layer() -> None:
    """``flat`` is one of the three legal values and is NOT "rising"."""
    result = gold_driver_attribution(_gold_inputs(central_bank_net_purchases_trend="flat"))
    assert _layers(result) == []


def test_a_falling_trend_does_not_fire_the_structural_layer() -> None:
    """Only ``"rising"`` fires the CB layer — Appendix D's own asymmetry.

    The layer is about DIVERSIFICATION, and only net buying is diversification;
    a fall does not fire it. Asserted so a future edit that "improves" the
    predicate to ``!= "flat"`` fails here.
    """
    result = gold_driver_attribution(_gold_inputs(central_bank_net_purchases_trend="falling"))
    assert _layers(result) == []


# --- the refusals (only two legs can refuse) ----------------------------------


def test_an_unavailable_real_yield_with_no_supplied_value_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The PRIMARY layer cannot be absent: it is the framework's main driver."""
    _stub_gold_fetches(monkeypatch, change_bp=None, crisis=False)
    with pytest.raises(ValueError, match="real_yield_change_bp"):
        gold_driver_attribution(GoldDriverInputs())


def test_an_unavailable_crisis_with_no_supplied_value_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A VIX fetch FAILURE must refuse — 'could not read' != 'calm'."""
    _stub_gold_fetches(monkeypatch, change_bp=20.0, crisis=None)
    with pytest.raises(ValueError, match="crisis_indicator"):
        gold_driver_attribution(GoldDriverInputs())


def test_an_absent_cb_trend_does_not_refuse(monkeypatch: pytest.MonkeyPatch) -> None:
    """THE ASYMMETRY TEST. The CB leg is a MEASURED BLOCK, so absent is normal.

    Unlike the other two legs, an unresolvable CB trend must NOT raise — there is
    no source, so it is absent on every default run. If a future edit made it
    fatal, the model would be unusable without a caller-supplied judgement.
    """
    _stub_gold_fetches(monkeypatch, change_bp=20.0, crisis=False)
    result = gold_driver_attribution(GoldDriverInputs())
    assert _dominant(result) == "real_yield"
    assert _value(result, "central_bank_net_purchases_trend") is None


def test_the_cb_block_is_disclosed_as_a_measured_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The disclosure must say 'no source exists', not 'the layer is flat'.

    This is the discriminating-disclosure discipline: a data-availability
    absence must never read like a finding about central-bank behaviour.
    """
    _stub_gold_fetches(monkeypatch, change_bp=20.0, crisis=False)
    result = gold_driver_attribution(GoldDriverInputs())
    joined = " ".join(result.data_provenance)
    assert "NOT RESOLVED" in joined
    assert "no free live source" in joined
    # And it must NOT claim the layer is inactive for an economic reason.
    assert "INACTIVE" in joined


def test_a_fully_supplied_gold_run_never_reaches_the_fetchers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The negative control: supplied values must short-circuit both fetches."""
    calls: list[str] = []

    def _should_not_be_called() -> tuple[float | None, str]:
        calls.append("called")
        return 0.0, "SHOULD NOT HAVE BEEN CALLED"

    monkeypatch.setattr(
        "macro_engine.models.commodities._resolve_real_yield_change", _should_not_be_called
    )
    monkeypatch.setattr(
        "macro_engine.models.commodities._resolve_crisis_indicator", _should_not_be_called
    )
    gold_driver_attribution(_gold_inputs())
    assert calls == []


def test_supplying_the_failed_leg_avoids_the_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Supplying the fetchable-but-failed leg lets the model compute."""
    _stub_gold_fetches(monkeypatch, change_bp=None, crisis=False)
    result = gold_driver_attribution(GoldDriverInputs(real_yield_change_bp=-25.0))
    assert _dominant(result) == "real_yield"


# --- confidence: the product, and the ONE-provider rule -----------------------


def test_gold_confidence_is_the_product_of_the_computed_half_and_the_cap() -> None:
    """A FULLY SUPPLIED run: flag set (no fetch), independence 0, times the cap."""
    gold = get_settings().gold_driver
    computed = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=True,
            is_heuristic_not_calibrated=not gold.reliability_cap_is_calibrated,
            source_independence_count=0,
            depends_on_unobservable=False,
        )
    )
    result = gold_driver_attribution(_gold_inputs())
    assert result.confidence == pytest.approx(computed * gold.reliability_value, rel=1e-12)


def test_gold_confidence_is_not_the_cap_alone() -> None:
    """Under ``min()`` the published confidence would equal the cap everywhere."""
    gold = get_settings().gold_driver
    result = gold_driver_attribution(_gold_inputs())
    assert result.confidence != pytest.approx(gold.reliability_value, rel=1e-9)


def test_a_fetched_gold_run_reports_higher_confidence_than_a_fully_supplied_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE TEST THAT READS THE OTHER HALF (D-118's rule).

    The computed half is HIGHER with both legs fetched than with none. Under
    ``min()`` both runs would publish the cap and this assertion would fail —
    which is precisely why the combining rule is MULTIPLICATION.
    """
    gold = get_settings().gold_driver
    _stub_gold_fetches(monkeypatch, change_bp=20.0, crisis=False)
    fetched = gold_driver_attribution(GoldDriverInputs())
    supplied = gold_driver_attribution(_gold_inputs(real_yield_change_bp=20.0))
    assert fetched.confidence > supplied.confidence
    assert fetched.confidence == pytest.approx(
        compute_confidence(
            ConfidenceInputs(
                data_quality_flags_present=False,
                is_heuristic_not_calibrated=not gold.reliability_cap_is_calibrated,
                source_independence_count=1,
                depends_on_unobservable=False,
            )
        )
        * gold.reliability_value,
        rel=1e-12,
    )


def test_both_fetched_gold_legs_count_as_one_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE INDEPENDENCE TEST. DFII10 and VIXCLS are BOTH FRED.

    Two fetches, ONE source family. A model that passed ``fetched_legs`` as the
    independence count would publish a HIGHER confidence here than the honest
    one — inflating its own evidence from a leg count. This test pins the count
    at 1 by asserting the exact product.
    """
    gold = get_settings().gold_driver
    _stub_gold_fetches(monkeypatch, change_bp=20.0, crisis=False)
    result = gold_driver_attribution(GoldDriverInputs())
    one_provider = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=False,
            is_heuristic_not_calibrated=not gold.reliability_cap_is_calibrated,
            source_independence_count=1,
            depends_on_unobservable=False,
        )
    )
    two_providers = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=False,
            is_heuristic_not_calibrated=not gold.reliability_cap_is_calibrated,
            source_independence_count=2,
            depends_on_unobservable=False,
        )
    )
    assert result.confidence == pytest.approx(one_provider * gold.reliability_value, rel=1e-12)
    assert result.confidence < two_providers * gold.reliability_value


def test_one_fetched_gold_leg_leaves_the_quality_flag_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One leg fetched is still an incomplete input set, so the flag stays."""
    gold = get_settings().gold_driver
    _stub_gold_fetches(monkeypatch, change_bp=20.0, crisis=None)
    result = gold_driver_attribution(GoldDriverInputs(crisis_indicator=False))
    assert result.confidence == pytest.approx(
        compute_confidence(
            ConfidenceInputs(
                data_quality_flags_present=True,
                is_heuristic_not_calibrated=not gold.reliability_cap_is_calibrated,
                source_independence_count=1,
                depends_on_unobservable=False,
            )
        )
        * gold.reliability_value,
        rel=1e-12,
    )


def test_a_fully_supplied_gold_run_has_no_independent_provider() -> None:
    """Nothing fetched -> the independence count is 0, not 1."""
    gold = get_settings().gold_driver
    result = gold_driver_attribution(_gold_inputs())
    assert result.confidence == pytest.approx(
        compute_confidence(
            ConfidenceInputs(
                data_quality_flags_present=True,
                is_heuristic_not_calibrated=not gold.reliability_cap_is_calibrated,
                source_independence_count=0,
                depends_on_unobservable=False,
            )
        )
        * gold.reliability_value,
        rel=1e-12,
    )


# --- the result contract ------------------------------------------------------


def test_the_gold_result_carries_its_contract_fields() -> None:
    result = gold_driver_attribution(_gold_inputs())
    assert result.model_name == "gold_driver_attribution"
    assert result.country == "global"
    assert result.unit == "layer_attribution"
    assert result.as_of is not None


def test_the_direction_is_the_dominant_layer() -> None:
    result = gold_driver_attribution(_gold_inputs(real_yield_change_bp=25.0))
    assert result.direction == "real_yield"


def test_all_three_inputs_are_named_as_used() -> None:
    """Appendix D declares three fields; a declared-but-unnamed field is D-037."""
    result = gold_driver_attribution(_gold_inputs())
    assert result.inputs_used == [
        "real_yield_change_bp",
        "central_bank_net_purchases_trend",
        "crisis_indicator",
    ]


def test_the_value_carries_every_reading() -> None:
    result = gold_driver_attribution(
        _gold_inputs(real_yield_change_bp=25.0, central_bank_net_purchases_trend="rising")
    )
    assert _value(result, "dominant_layer") == "real_yield"
    assert _value(result, "real_yield_change_bp") == 25.0
    assert _value(result, "central_bank_net_purchases_trend") == "rising"
    assert _value(result, "crisis_indicator") is False


def test_the_published_change_uses_the_config_decimals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rounding is a config-declared precision, not a hardcoded literal."""
    gold = _gold_settings_with(value_decimals_leaf=_calibrated(3))

    class _Settings:
        gold_driver = gold

    monkeypatch.setattr("macro_engine.models.commodities.get_settings", lambda: _Settings())
    result = gold_driver_attribution(_gold_inputs(real_yield_change_bp=25.1234567))
    assert _gold_change(result) == 25.123


def test_the_commodity_scope_warning_is_always_present() -> None:
    """The production-scope decision must travel with EVERY reading."""
    for kwargs in ({}, {"crisis_indicator": True}, {"real_yield_change_bp": 99.0}):
        result = gold_driver_attribution(_gold_inputs(**kwargs))
        joined = " ".join(result.warnings)
        assert "INFORMATIONAL ONLY" in joined
        assert "production" in joined


def test_the_no_layer_reading_is_warned_not_silent() -> None:
    """``none_identified`` must explain itself — an empty attribution is a claim."""
    result = gold_driver_attribution(_gold_inputs())
    joined = " ".join(result.warnings)
    assert "NO layer was identified" in joined


def test_the_cb_absence_warning_does_not_claim_the_layer_is_flat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The warning must blame DATA AVAILABILITY, not assert an economic fact.

    The warning only fires when the CB leg is UNRESOLVED, so this drives the
    fetch path with no supplied trend — the default run for that field.
    """
    _stub_gold_fetches(monkeypatch, change_bp=20.0, crisis=False)
    result = gold_driver_attribution(GoldDriverInputs())
    joined = " ".join(result.warnings)
    assert "NOT evaluated" in joined
    assert "NOT by evidence" in joined


def test_a_fetched_gold_run_is_tagged_market_commodity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_gold_fetches(monkeypatch, change_bp=20.0, crisis=False)
    result = gold_driver_attribution(GoldDriverInputs())
    assert result.source_family is EvidenceSourceFamily.MARKET_COMMODITY


def test_a_fully_supplied_gold_run_is_tagged_manual_assessment() -> None:
    result = gold_driver_attribution(_gold_inputs())
    assert result.source_family is EvidenceSourceFamily.MANUAL_ASSESSMENT


def test_a_supplied_gold_leg_is_disclosed_as_supplied() -> None:
    result = gold_driver_attribution(_gold_inputs())
    joined = " ".join(result.data_provenance)
    assert "SUPPLIED BY THE CALLER" in joined


def test_a_fetched_gold_leg_is_disclosed_as_fetched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_gold_fetches(monkeypatch, change_bp=20.0, crisis=False)
    result = gold_driver_attribution(GoldDriverInputs())
    joined = " ".join(result.data_provenance)
    assert "FETCHED" in joined


def test_the_gold_layer_warnings_name_their_durability_profiles() -> None:
    """Each firing layer warns about its OWN durability, per Appendix D."""
    result = gold_driver_attribution(
        _gold_inputs(
            real_yield_change_bp=25.0,
            central_bank_net_purchases_trend="rising",
            crisis_indicator=True,
        )
    )
    joined = " ".join(result.warnings)
    assert "MECHANICAL" in joined
    assert "STRUCTURAL" in joined
    assert "ACUTE" in joined


# --- the gold config leaves (G-block) -----------------------------------------


def _gold_settings_with(**values: object) -> GoldDriverSettings:
    """A GoldDriverSettings seeded from the shipped block, with overrides.

    Seeding from ``dict(get_settings().gold_driver)`` rather than restating every
    field means a new field can never make this fixture stale (the O-127
    structural fix D-114 applied to its own helpers).
    """
    base = dict(get_settings().gold_driver)
    base.update(values)
    return GoldDriverSettings(**base)


@pytest.mark.parametrize("sentinel", [0.42, 0.11])
def test_the_gold_reliability_accessor_follows_a_perturbed_leaf(sentinel: float) -> None:
    """G1a: the accessor must READ the leaf, not return a literal."""
    block = _gold_settings_with(reliability_cap=_calibrated(sentinel))
    assert block.reliability_value == pytest.approx(sentinel)


@pytest.mark.parametrize("sentinel", [1, 4])
def test_the_gold_decimals_accessor_follows_a_perturbed_leaf(sentinel: int) -> None:
    """G2a: the accessor must READ the leaf, not return a literal."""
    block = _gold_settings_with(value_decimals_leaf=_calibrated(sentinel))
    assert block.value_decimals == sentinel


@pytest.mark.parametrize("sentinel", [2.5, 18.0])
def test_the_gold_yield_threshold_accessor_follows_a_perturbed_leaf(sentinel: float) -> None:
    """G3a: the accessor must READ the leaf, not return a literal."""
    block = _gold_settings_with(yield_change_threshold_materiality_bp=_calibrated(sentinel))
    assert block.yield_change_threshold_bp == pytest.approx(sentinel)


@pytest.mark.parametrize("sentinel", [15.0, 45.0])
def test_the_gold_crisis_threshold_accessor_follows_a_perturbed_leaf(sentinel: float) -> None:
    """G3b: the accessor must READ the leaf, not return a literal."""
    block = _gold_settings_with(crisis_vix_spike_level=_calibrated(sentinel))
    assert block.crisis_vix_threshold_value == pytest.approx(sentinel)


@pytest.mark.parametrize("bad", [-0.01, 1.01])
def test_a_gold_cap_outside_the_unit_interval_is_refused(bad: float) -> None:
    """G4a: the cap validator must FIRE on an out-of-range cap."""
    with pytest.raises(ValidationError, match="reliability_cap"):
        _gold_settings_with(reliability_cap=_calibrated(bad))


@pytest.mark.parametrize("bad", [-1, -3])
def test_a_negative_gold_decimals_leaf_is_refused(bad: int) -> None:
    """G4b: a negative ``ndigits`` coarsens the published change."""
    with pytest.raises(ValidationError, match="value_decimals"):
        _gold_settings_with(value_decimals_leaf=_calibrated(bad))


@pytest.mark.parametrize("bad", [0.0, -5.0])
def test_a_non_positive_yield_threshold_is_refused(bad: float) -> None:
    """G4c: a non-positive threshold fires the primary layer on ANY change."""
    with pytest.raises(ValidationError, match="yield_change_threshold_materiality_bp"):
        _gold_settings_with(yield_change_threshold_materiality_bp=_calibrated(bad))


@pytest.mark.parametrize("bad", [0.0, -1.0])
def test_a_non_positive_vix_threshold_is_refused(bad: float) -> None:
    """G4d: a non-positive VIX threshold makes crisis_indicator permanently True."""
    with pytest.raises(ValidationError, match="crisis_vix_spike_level"):
        _gold_settings_with(crisis_vix_spike_level=_calibrated(bad))


# =============================================================================
# Module 10.3 — metals_complex_divergence (Section 20.10, D-122)
#
# ⚠️ EVERY TEST NAME BELOW IS PREFIXED ``metals_`` OR IS OTHERWISE DISTINCT.
#    D-121's O-150: a new ``test_*`` name that collides with an existing one makes
#    Python bind the LAST definition, silently deleting the earlier body while
#    pytest still reports a healthy count. The gold twins were renamed for exactly
#    this reason; these are named to never collide in the first place.
# =============================================================================


def _metals_inputs(**overrides: object) -> MetalsComplexInputs:
    """A metals inputs object with ALL THREE values SUPPLIED, so no network is used.

    Supplying all three is the right unit-test default for a *classifier*: it lets
    a test pin the exact pattern it means to exercise. The fetch paths have their
    own tests below and the live check exercises them end to end.
    """
    base: dict[str, object] = {
        "copper_change_pct": 0.0,
        "iron_ore_change_pct": 0.0,
        "aluminum_change_pct": 0.0,
    }
    base.update(overrides)
    return MetalsComplexInputs(**base)  # type: ignore[arg-type]


def _metals_verdict(result: ModelResult) -> str:
    item = _value(result, "verdict")
    assert isinstance(item, str)
    return item


def _metals_change(result: ModelResult, key: str) -> float:
    item = _value(result, key)
    assert isinstance(item, float)
    return item


def _metals_settings_with(**values: object) -> MetalsComplexSettings:
    """A MetalsComplexSettings seeded from the shipped block, with overrides.

    Seeding from ``get_settings().metals_complex.model_dump()`` rather than
    restating every field means a new field can never make this fixture stale
    (the O-127 structural fix D-114 applied to its own helpers).

    The numeric leaves are typed ``CalibratedValue``, so a bare ``5.0`` is
    REFUSED by pydantic. A **bare number is wrapped** by ``_calibrated``, while
    an already-wrapped ``CalibratedValue`` is passed THROUGH untouched — without
    that guard a caller writing ``_calibrated(0.42)`` would get
    ``CalibratedValue(CalibratedValue(0.42))`` and the validator would die on a
    ``TypeError`` instead of testing anything (the ``float()`` of a model).
    """
    base = dict(get_settings().metals_complex.model_dump())
    base.update(
        {
            name: value if isinstance(value, CalibratedValue) else _calibrated(value)
            for name, value in values.items()
        }
    )
    return MetalsComplexSettings.model_validate(base)


def _stub_metal_fetches(
    monkeypatch: pytest.MonkeyPatch,
    *,
    copper: float | None,
    iron_ore: float | None,
    aluminum: float | None,
) -> None:
    """Patch the three metal fetch wrappers to return fixed MetalChangeReadings.

    Patching the CLIENT functions (not the model helpers) is what makes the
    model's own resolution loop, its ``fetched_legs`` accounting and its
    source-family choice execute end to end; the client's transport has its own
    tests in ``test_commodities_client.py``.

    A ``None`` for any leg makes that stub RAISE, which is how a fetch failure is
    represented — the model turns it into a ``None`` change and a disclosure.
    """

    def _make(name: str, value: float | None) -> object:
        def _fetch(*, as_of: object, client: object = None) -> object:
            if value is None:
                raise CommodityReadError(f"stub {name} failure")
            return MetalChangeReading(
                symbol={
                    "copper": COPPER_SYMBOL,
                    "iron_ore": IRON_ORE_SYMBOL,
                    "aluminum": ALUMINUM_SYMBOL,
                }[name],
                observation_date="2026-07-01",
                level=100.0,
                prior_observation_date="2026-06-01",
                prior_level=100.0,
                change_pct=value,
                observation_count=139,
            )

        return _fetch

    monkeypatch.setattr(
        "macro_engine.models.commodities.fetch_copper_change", _make("copper", copper)
    )
    monkeypatch.setattr(
        "macro_engine.models.commodities.fetch_iron_ore_change", _make("iron_ore", iron_ore)
    )
    monkeypatch.setattr(
        "macro_engine.models.commodities.fetch_aluminum_change", _make("aluminum", aluminum)
    )


# --- the three verdicts -------------------------------------------------------


def test_metals_the_specifications_named_case_is_construction_specific() -> None:
    """THE SPECIFICATION'S OWN TEST (Section 21.2's ``test_metals_divergence_china_specific``).

    "iron ore worst, copper down, aluminum flat must return
    CHINA_CONSTRUCTION_SPECIFIC" — this is that case, verbatim.
    """
    result = metals_complex_divergence(
        _metals_inputs(
            copper_change_pct=-4.0,
            iron_ore_change_pct=-9.0,
            aluminum_change_pct=0.5,
        )
    )
    assert _metals_verdict(result) == "CHINA_CONSTRUCTION_SPECIFIC"


def test_metals_all_three_falling_hard_is_broad_industrial() -> None:
    result = metals_complex_divergence(
        _metals_inputs(
            copper_change_pct=-5.0,
            iron_ore_change_pct=-8.0,
            aluminum_change_pct=-4.0,
        )
    )
    assert _metals_verdict(result) == "BROAD_INDUSTRIAL_WEAKNESS"


def test_metals_an_inert_complex_is_mixed_not_an_error() -> None:
    """No pattern is a READING, not a crash and not an empty string."""
    result = metals_complex_divergence(
        _metals_inputs(
            copper_change_pct=1.0,
            iron_ore_change_pct=-1.0,
            aluminum_change_pct=0.5,
        )
    )
    assert _metals_verdict(result) == "MIXED_no_clear_pattern"


def test_metals_copper_and_iron_rising_is_mixed() -> None:
    """Construction requires BOTH to be negative; a rising pair is not it."""
    result = metals_complex_divergence(
        _metals_inputs(
            copper_change_pct=3.0,
            iron_ore_change_pct=5.0,
            aluminum_change_pct=0.1,
        )
    )
    assert _metals_verdict(result) == "MIXED_no_clear_pattern"


def test_metals_iron_ore_not_the_worst_faller_is_not_construction() -> None:
    """The construction test needs ``iron_ore < copper < 0``.

    With copper the worst faller (iron ore merely down), the ordering clause
    fails — so a mutant that dropped the ordering would change this verdict.
    """
    result = metals_complex_divergence(
        _metals_inputs(
            copper_change_pct=-9.0,
            iron_ore_change_pct=-4.0,
            aluminum_change_pct=0.5,
        )
    )
    assert _metals_verdict(result) == "MIXED_no_clear_pattern"


def test_metals_copper_exactly_zero_is_not_strictly_negative() -> None:
    """The spec requires ``copper < 0`` strictly; a flat copper is not "down"."""
    result = metals_complex_divergence(
        _metals_inputs(
            copper_change_pct=0.0,
            iron_ore_change_pct=-5.0,
            aluminum_change_pct=0.5,
        )
    )
    assert _metals_verdict(result) == "MIXED_no_clear_pattern"


# --- the boundary cases, ON the thresholds (the D-031 discipline) --------------


@pytest.mark.parametrize("aluminum", [-2.0, 2.0])
def test_metals_aluminum_exactly_on_the_band_is_not_stable(aluminum: float) -> None:
    """``abs(aluminum) < band`` is STRICT: exactly on the band is NOT stable.

    The two parametrised values are the band's two signs. A mutant that flipped
    ``<`` to ``<=`` would make this case construction-specific instead of
    broad/mixed — which is why the fixture sits exactly ON the band.
    """
    result = metals_complex_divergence(
        _metals_inputs(
            copper_change_pct=-4.0,
            iron_ore_change_pct=-9.0,
            aluminum_change_pct=aluminum,
        )
    )
    # aluminum = -2.0: |-2.0| < 2.0 is False AND -2.0 < -2.0 is False => MIXED.
    # aluminum = +2.0: |2.0| < 2.0 is False => the broad test also fails => MIXED.
    assert _metals_verdict(result) == "MIXED_no_clear_pattern"


def test_metals_aluminum_just_inside_the_band_is_stable() -> None:
    """Just inside the band (1.99) IS stable, so the construction branch fires."""
    result = metals_complex_divergence(
        _metals_inputs(
            copper_change_pct=-4.0,
            iron_ore_change_pct=-9.0,
            aluminum_change_pct=1.99,
        )
    )
    assert _metals_verdict(result) == "CHINA_CONSTRUCTION_SPECIFIC"


def test_metals_aluminum_exactly_on_the_broad_threshold_is_not_weak() -> None:
    """``change < -threshold`` is STRICT: exactly ``-2.0`` is NOT broad-weak."""
    result = metals_complex_divergence(
        _metals_inputs(
            copper_change_pct=-5.0,
            iron_ore_change_pct=-8.0,
            aluminum_change_pct=-2.0,
        )
    )
    assert _metals_verdict(result) == "MIXED_no_clear_pattern"


def test_metals_aluminum_just_below_the_broad_threshold_is_weak() -> None:
    result = metals_complex_divergence(
        _metals_inputs(
            copper_change_pct=-5.0,
            iron_ore_change_pct=-8.0,
            aluminum_change_pct=-2.01,
        )
    )
    assert _metals_verdict(result) == "BROAD_INDUSTRIAL_WEAKNESS"


def test_metals_one_metal_above_the_broad_threshold_is_not_broad() -> None:
    """``all(...)`` is required: copper at exactly -2.0 breaks the quantifier."""
    result = metals_complex_divergence(
        _metals_inputs(
            copper_change_pct=-2.0,
            iron_ore_change_pct=-8.0,
            aluminum_change_pct=-5.0,
        )
    )
    assert _metals_verdict(result) == "MIXED_no_clear_pattern"


def test_metals_the_two_branches_are_mutually_exclusive() -> None:
    """THE DEAD-BRANCH PROOF (D-118 ``R6a``'s lesson, measured).

    The construction test needs ``|aluminum| < band`` (aluminum quiet) while the
    broad test needs ``aluminum < -threshold`` (aluminum falling hard). With
    positive bands these are contradictory, so NO input set satisfies both and
    the specification's ``if/elif`` order never actually decides a verdict. An
    earlier draft carried an "ambiguous pattern" disclosure for a tie; it was
    unreachable and was removed. This asserts the exclusivity on a grid that
    straddles both bands, so a future band change that broke it would fail here.
    """
    band = get_settings().metals_complex.aluminum_band_pct
    for copper in (-9.0, -5.0, -1.0, 0.0, 3.0):
        for iron_ore in (-12.0, -6.0, -0.5, 2.0):
            for aluminum in (-band - 0.5, -band, 0.0, band, band + 0.5):
                result = metals_complex_divergence(
                    _metals_inputs(
                        copper_change_pct=copper,
                        iron_ore_change_pct=iron_ore,
                        aluminum_change_pct=aluminum,
                    )
                )
                verdict = _metals_verdict(result)
                # The construction branch (aluminum strictly inside the band) and
                # the broad branch (aluminum strictly below -band) cannot co-occur.
                in_band = abs(aluminum) < band
                below_broad = aluminum < -band
                assert not (in_band and below_broad), (
                    f"bands overlap at aluminum={aluminum}: in_band={in_band}, "
                    f"below_broad={below_broad}"
                )
                assert verdict in {
                    "CHINA_CONSTRUCTION_SPECIFIC",
                    "BROAD_INDUSTRIAL_WEAKNESS",
                    "MIXED_no_clear_pattern",
                }


# --- the thresholds come from the LEAVES, not literals (D-050) -----------------


def test_metals_the_aluminum_band_follows_a_perturbed_leaf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Move the band and the verdict must move with it.

    With the shipped band of 2.0, aluminum at 3.0 is NOT stable (mixed). With a
    perturbed band of 5.0, the SAME aluminum IS stable, so the verdict flips to
    construction-specific — proving the model reads the leaf rather than a
    hardcoded 2.0 (the D-050 leaf-perturbation rule, never a value comparison).
    """
    _stub_perturbed_metals_settings(monkeypatch, aluminum_stability_band_pct_leaf=5.0)
    result = metals_complex_divergence(
        _metals_inputs(
            copper_change_pct=-4.0,
            iron_ore_change_pct=-9.0,
            aluminum_change_pct=3.0,
        )
    )
    assert _metals_verdict(result) == "CHINA_CONSTRUCTION_SPECIFIC"


def test_metals_the_broad_threshold_follows_a_perturbed_leaf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Widen the broad threshold to 3.0 and a -2.5 complex is NO LONGER broad.

    With the shipped 2.0, copper -2.5 / iron ore -2.5 / aluminum -2.5 is broad
    (all below -2.0). With a threshold of 3.0 none clears it, so the verdict is
    mixed — proving the model reads the leaf rather than a hardcoded 2.0.
    """
    _stub_perturbed_metals_settings(monkeypatch, broad_weakness_threshold_pct_leaf=3.0)
    result = metals_complex_divergence(
        _metals_inputs(
            copper_change_pct=-2.5,
            iron_ore_change_pct=-2.5,
            aluminum_change_pct=-2.5,
        )
    )
    assert _metals_verdict(result) == "MIXED_no_clear_pattern"


def _stub_perturbed_metals_settings(monkeypatch: pytest.MonkeyPatch, **values: object) -> None:
    """Make ``get_settings()`` return a metals block with the given leaves moved.

    The model calls ``get_settings().metals_complex``, so patching the SETTINGS
    accessor is what makes the leaf-perturbation tests exercise the model's own
    read of config rather than a stub of the model.
    """
    block = _metals_settings_with(**values)
    real = get_settings()

    class _Shim:
        metals_complex = block

    monkeypatch.setattr("macro_engine.models.commodities.get_settings", lambda: _Shim())
    # Keep a reference so linters do not flag the unused read; and assert the
    # shim is not simply the real block (a no-op patch would make the test lie).
    assert real.metals_complex is not block


# --- the refusal when a leg cannot be resolved --------------------------------


def test_metals_an_unresolved_leg_with_no_supplied_value_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing leg is a DIFFERENT pattern, so the model REFUSES rather than guesses."""
    _stub_metal_fetches(monkeypatch, copper=None, iron_ore=-6.0, aluminum=0.5)
    with pytest.raises(ValueError, match="copper_change_pct"):
        metals_complex_divergence(MetalsComplexInputs())


def test_metals_supplying_the_failed_leg_avoids_the_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Supplying the leg the fetch could not provide is the documented escape.

    Only copper is SUPPLIED; iron ore and aluminum are left ``None`` so the two
    stubbed fetches (``-9.0`` / ``0.5``) actually run — which is the point. The
    helper's ``0.0`` defaults would otherwise mask the stubs and the pattern
    under test would never be constructed.
    """
    _stub_metal_fetches(monkeypatch, copper=None, iron_ore=-9.0, aluminum=0.5)
    result = metals_complex_divergence(
        _metals_inputs(
            copper_change_pct=-4.0,
            iron_ore_change_pct=None,
            aluminum_change_pct=None,
        )
    )
    assert _metals_verdict(result) == "CHINA_CONSTRUCTION_SPECIFIC"


def test_metals_two_missing_legs_are_both_named_in_the_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_metal_fetches(monkeypatch, copper=None, iron_ore=None, aluminum=0.5)
    with pytest.raises(ValueError) as excinfo:
        metals_complex_divergence(MetalsComplexInputs())
    message = str(excinfo.value)
    assert "copper_change_pct" in message
    assert "iron_ore_change_pct" in message


def test_metals_a_fully_supplied_run_never_reaches_the_fetchers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Supply all three and NO fetch is called — proven by making every fetch explode."""

    def _boom(*, as_of: object, client: object = None) -> object:
        raise AssertionError("the fetchers must not be reached when all legs are supplied")

    monkeypatch.setattr("macro_engine.models.commodities.fetch_copper_change", _boom)
    monkeypatch.setattr("macro_engine.models.commodities.fetch_iron_ore_change", _boom)
    monkeypatch.setattr("macro_engine.models.commodities.fetch_aluminum_change", _boom)
    result = metals_complex_divergence(_metals_inputs())
    assert _metals_verdict(result) == "MIXED_no_clear_pattern"


# --- confidence: the PRODUCT, and the independence count -----------------------


def test_metals_confidence_is_the_product_of_the_computed_half_and_the_cap() -> None:
    """The D-118/D-119/D-120/D-121 rule: MULTIPLY, do not ``min()``.

    The computed half prices this run's inputs; the cap states what the METHOD is
    worth. ``min()`` would publish the cap on every path and make the computed
    half dead code — exactly the defect D-118 removed. A fully-supplied run has
    the quality flag SET and one NO source family, so the computed half is below
    the cap and the product is strictly BELOW the cap alone.
    """
    result = metals_complex_divergence(_metals_inputs())
    cap = get_settings().metals_complex.reliability_value
    computed = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=True,
            is_heuristic_not_calibrated=(
                not get_settings().metals_complex.reliability_cap_is_calibrated
            ),
            source_independence_count=0,
            depends_on_unobservable=False,
        )
    )
    assert result.confidence == pytest.approx(computed * cap)
    assert result.confidence < cap


def test_metals_confidence_is_not_the_cap_alone() -> None:
    """A ``min()`` mutant would return the cap; the product must be strictly less."""
    result = metals_complex_divergence(_metals_inputs())
    cap = get_settings().metals_complex.reliability_value
    assert result.confidence != pytest.approx(cap)


def test_metals_a_fetched_run_reports_higher_confidence_than_a_supplied_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fetching all three clears the quality flag, so the computed half rises."""
    supplied = metals_complex_divergence(_metals_inputs())
    _stub_metal_fetches(monkeypatch, copper=-4.0, iron_ore=-9.0, aluminum=0.5)
    fetched = metals_complex_divergence(MetalsComplexInputs())
    assert fetched.confidence > supplied.confidence


def test_metals_all_three_fetched_legs_count_as_one_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE INDEPENDENCE TEST. Three FRED legs are ONE provider, so the count is 1.

    A model that reported ``fetched_legs`` as the independence count would let the
    source-independence bonus scale with THREE fetches from one family and
    overstate the evidence threefold. This asserts the count the model actually
    passed to ``compute_confidence`` matches the one-provider reading.
    """
    captured: dict[str, object] = {}
    import macro_engine.models.commodities as commodities_module

    real = commodities_module.compute_confidence

    def _spy(inputs: ConfidenceInputs) -> float:
        captured["inputs"] = inputs
        return real(inputs)

    monkeypatch.setattr(commodities_module, "compute_confidence", _spy)
    _stub_metal_fetches(monkeypatch, copper=-4.0, iron_ore=-9.0, aluminum=0.5)
    metals_complex_divergence(MetalsComplexInputs())
    inputs = captured["inputs"]
    assert isinstance(inputs, ConfidenceInputs)
    assert inputs.source_independence_count == 1
    assert inputs.data_quality_flags_present is False


def test_metals_a_fully_supplied_run_has_no_independent_provider() -> None:
    captured: dict[str, object] = {}
    import macro_engine.models.commodities as commodities_module

    real = commodities_module.compute_confidence

    def _spy(inputs: ConfidenceInputs) -> float:
        captured["inputs"] = inputs
        return real(inputs)

    import pytest as _pytest

    with _pytest.MonkeyPatch.context() as mp:
        mp.setattr(commodities_module, "compute_confidence", _spy)
        metals_complex_divergence(_metals_inputs())
    inputs = captured["inputs"]
    assert isinstance(inputs, ConfidenceInputs)
    assert inputs.source_independence_count == 0
    assert inputs.data_quality_flags_present is True


# --- the result contract -------------------------------------------------------


def test_metals_the_result_carries_its_contract_fields() -> None:
    result = metals_complex_divergence(_metals_inputs())
    assert result.model_name == "metals_complex_divergence"
    assert result.country == "global"
    assert result.unit == "driver_classification"
    assert result.inputs_used == [
        "copper_change_pct",
        "iron_ore_change_pct",
        "aluminum_change_pct",
    ]


def test_metals_the_direction_is_derived_from_the_signs_not_the_verdict() -> None:
    """``direction`` follows the metal SIGNS, never the verdict label (D-131).

    This test REPLACES one that asserted ``mixed.direction == "expansionary"``
    for the all-positive ``(1, 1, 1)`` fixture — the verdict label happened to
    coincide with an expansionary sign there, which hid the defect. The old rule
    (``"expansionary" if MIXED else "restrictive"``) published ``"expansionary"``
    for an ALL-FALLING complex whose pattern was merely ``MIXED``: measured with
    ``copper=-1.0, iron_ore=-0.5, aluminum=-1.0`` (every metal down) before the
    fix. A label derived from the verdict is BLINDER than the state set (5ew).

    The guard drives both a falling-MIXED case and a rising-MIXED case, so a
    regression to the label-derived rule fails here.
    """
    # MIXED *and* all-falling: must read restrictive, NOT expansionary.
    falling_mixed = metals_complex_divergence(
        _metals_inputs(copper_change_pct=-1.0, iron_ore_change_pct=-0.5, aluminum_change_pct=-1.0)
    )
    assert falling_mixed.value["verdict"] == "MIXED_no_clear_pattern"
    assert falling_mixed.direction == "restrictive"

    # MIXED *and* all-rising: expansionary, the case the old test happened to hit.
    rising_mixed = metals_complex_divergence(
        _metals_inputs(copper_change_pct=1.0, iron_ore_change_pct=1.0, aluminum_change_pct=1.0)
    )
    assert rising_mixed.value["verdict"] == "MIXED_no_clear_pattern"
    assert rising_mixed.direction == "expansionary"

    # MIXED with a genuine mix of signs: NEUTRAL, which is the honest reading.
    mixed_signs = metals_complex_divergence(
        _metals_inputs(copper_change_pct=0.5, iron_ore_change_pct=-0.5, aluminum_change_pct=0.0)
    )
    assert mixed_signs.value["verdict"] == "MIXED_no_clear_pattern"
    assert mixed_signs.direction == "neutral"

    # The two FIRING verdicts are NOT automatically restrictive — the direction
    # follows the signs, exactly as for MIXED. BROAD_INDUSTRIAL_WEAKNESS here has
    # every metal falling, so it reads restrictive.
    broad = metals_complex_divergence(
        _metals_inputs(copper_change_pct=-5.0, iron_ore_change_pct=-6.0, aluminum_change_pct=-4.0)
    )
    assert broad.value["verdict"] == "BROAD_INDUSTRIAL_WEAKNESS"
    assert broad.direction == "restrictive"

    # CHINA_CONSTRUCTION_SPECIFIC: iron ore collapses while aluminum RISES, so the
    # signs genuinely DISAGREE and the honest reading is NEUTRAL — not restrictive.
    # A verdict-derived direction would have published "restrictive" here purely
    # from the label, which is the defect this test replaces.
    construction = metals_complex_divergence(
        _metals_inputs(copper_change_pct=-4.0, iron_ore_change_pct=-9.0, aluminum_change_pct=0.5)
    )
    assert construction.value["verdict"] == "CHINA_CONSTRUCTION_SPECIFIC"
    assert construction.direction == "neutral"


def test_metals_the_value_carries_every_reading() -> None:
    result = metals_complex_divergence(
        _metals_inputs(
            copper_change_pct=-4.0,
            iron_ore_change_pct=-9.0,
            aluminum_change_pct=0.5,
        )
    )
    assert _metals_change(result, "copper_change_pct") == pytest.approx(-4.0)
    assert _metals_change(result, "iron_ore_change_pct") == pytest.approx(-9.0)
    assert _metals_change(result, "aluminum_change_pct") == pytest.approx(0.5)


def test_metals_the_published_change_uses_the_config_decimals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The published change is rounded to the CONFIG leaf, not a hardcoded literal.

    The rounding must be observable, so the leaf is PERTURBED to a precision that
    differs from the shipped ``1`` and the assertion is an EXACT comparison
    against ``round(raw, decimals)`` — NOT ``pytest.approx(raw)``, which the raw
    input itself satisfies no matter whether the round happened. With ``decimals
    = 3`` and a raw of seven decimals, an unrounded ``-4.123456`` would fail this
    assertion (it is ``-4.123`` that must come back), which is what kills MM7a.
    """
    _stub_perturbed_metals_settings(monkeypatch, value_decimals_leaf=_calibrated(3))
    result = metals_complex_divergence(
        _metals_inputs(
            copper_change_pct=-4.1234567,
            iron_ore_change_pct=-9.9876543,
            aluminum_change_pct=0.5555555,
        )
    )
    assert _metals_change(result, "copper_change_pct") == -4.123
    assert _metals_change(result, "iron_ore_change_pct") == -9.988
    assert _metals_change(result, "aluminum_change_pct") == 0.556
    # The rounding must not be a no-op: the raw inputs have more decimals.
    assert _metals_change(result, "copper_change_pct") != -4.1234567


# --- the disclosures and warnings ---------------------------------------------


def test_metals_the_commodity_scope_warning_is_always_present() -> None:
    result = metals_complex_divergence(_metals_inputs())
    assert any("INFORMATIONAL ONLY" in w for w in result.warnings)
    assert any("China demand" in w for w in result.warnings)


def test_metals_the_construction_verdict_names_aluminum_as_the_discriminator() -> None:
    result = metals_complex_divergence(
        _metals_inputs(
            copper_change_pct=-4.0,
            iron_ore_change_pct=-9.0,
            aluminum_change_pct=0.5,
        )
    )
    assert any("discriminating" in w.lower() and "aluminum" in w.lower() for w in result.warnings)


def test_metals_the_broad_verdict_warns_against_localising_to_china() -> None:
    result = metals_complex_divergence(
        _metals_inputs(
            copper_change_pct=-5.0,
            iron_ore_change_pct=-6.0,
            aluminum_change_pct=-4.0,
        )
    )
    assert any("NOT construction-specific" in w for w in result.warnings)


def test_metals_the_mixed_reading_is_warned_not_silent() -> None:
    result = metals_complex_divergence(_metals_inputs())
    assert any("NO clear pattern" in w for w in result.warnings)


def test_metals_a_supplied_leg_is_disclosed_as_supplied() -> None:
    result = metals_complex_divergence(_metals_inputs())
    joined = " ".join(result.data_provenance)
    assert "SUPPLIED BY THE CALLER" in joined
    assert "FETCHED" not in joined


def test_metals_a_fetched_leg_is_disclosed_as_fetched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_metal_fetches(monkeypatch, copper=-4.0, iron_ore=-9.0, aluminum=0.5)
    result = metals_complex_divergence(MetalsComplexInputs())
    joined = " ".join(result.data_provenance)
    assert "FETCHED — FRED" in joined
    assert "SUPPLIED BY THE CALLER" not in joined


def test_metals_a_fetched_run_is_tagged_market_commodity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_metal_fetches(monkeypatch, copper=-4.0, iron_ore=-9.0, aluminum=0.5)
    result = metals_complex_divergence(MetalsComplexInputs())
    assert result.source_family is EvidenceSourceFamily.MARKET_COMMODITY


def test_metals_a_fully_supplied_run_is_tagged_manual_assessment() -> None:
    result = metals_complex_divergence(_metals_inputs())
    assert result.source_family is EvidenceSourceFamily.MANUAL_ASSESSMENT


def test_metals_a_partly_supplied_run_warns_that_some_legs_are_caller_supplied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_metal_fetches(monkeypatch, copper=None, iron_ore=-9.0, aluminum=0.5)
    result = metals_complex_divergence(_metals_inputs(copper_change_pct=-4.0))
    assert any("SUPPLIED BY THE CALLER" in w for w in result.warnings)


# --- the input validator -------------------------------------------------------


def test_metals_extra_input_fields_are_refused() -> None:
    with pytest.raises(ValidationError):
        MetalsComplexInputs(**{**_metals_dict(), "surprise": 1})  # type: ignore[arg-type]


def _metals_dict() -> dict[str, object]:
    return {
        "copper_change_pct": 0.0,
        "iron_ore_change_pct": 0.0,
        "aluminum_change_pct": 0.0,
    }


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_metals_a_non_finite_change_is_refused(bad: float) -> None:
    """A nan silently fails every comparison and would read as MIXED (D-078's class)."""
    with pytest.raises(ValidationError):
        MetalsComplexInputs(
            copper_change_pct=bad,
            iron_ore_change_pct=0.0,
            aluminum_change_pct=0.0,
        )


def test_metals_a_non_finite_change_on_a_later_leg_is_refused() -> None:
    with pytest.raises(ValidationError):
        MetalsComplexInputs(
            copper_change_pct=0.0,
            iron_ore_change_pct=float("nan"),
            aluminum_change_pct=0.0,
        )


def test_metals_the_country_defaults_to_global() -> None:
    assert MetalsComplexInputs().country == "global"


# --- the settings block --------------------------------------------------------


@pytest.mark.parametrize("sentinel", [0.42, 0.11])
def test_metals_the_reliability_accessor_follows_a_perturbed_leaf(sentinel: float) -> None:
    """GM1: the accessor must READ the leaf, not return a literal."""
    block = _metals_settings_with(reliability_cap=_calibrated(sentinel))
    assert block.reliability_value == pytest.approx(sentinel)


@pytest.mark.parametrize("sentinel", [1, 4])
def test_metals_the_decimals_accessor_follows_a_perturbed_leaf(sentinel: int) -> None:
    """GM2: the accessor must READ the leaf, not return a literal."""
    block = _metals_settings_with(value_decimals_leaf=_calibrated(sentinel))
    assert block.value_decimals == sentinel


@pytest.mark.parametrize("sentinel", [1.5, 7.5])
def test_metals_the_aluminum_band_accessor_follows_a_perturbed_leaf(sentinel: float) -> None:
    """GM3: the accessor must READ the leaf, not return a literal."""
    block = _metals_settings_with(aluminum_stability_band_pct_leaf=_calibrated(sentinel))
    assert block.aluminum_band_pct == pytest.approx(sentinel)


@pytest.mark.parametrize("sentinel", [1.5, 7.5])
def test_metals_the_broad_threshold_accessor_follows_a_perturbed_leaf(sentinel: float) -> None:
    """GM4: the accessor must READ the leaf, not return a literal."""
    block = _metals_settings_with(broad_weakness_threshold_pct_leaf=_calibrated(sentinel))
    assert block.broad_weakness_threshold_pct == pytest.approx(sentinel)


@pytest.mark.parametrize("bad", [-0.01, 1.01])
def test_metals_a_cap_outside_the_unit_interval_is_refused(bad: float) -> None:
    """GM5: the cap validator must FIRE on an out-of-range cap."""
    with pytest.raises(ValidationError, match="reliability_cap"):
        _metals_settings_with(reliability_cap=_calibrated(bad))


@pytest.mark.parametrize("bad", [-1, -3])
def test_metals_a_negative_decimals_leaf_is_refused(bad: int) -> None:
    """GM6: a negative ``ndigits`` coarsens the published change."""
    with pytest.raises(ValidationError, match="value_decimals"):
        _metals_settings_with(value_decimals_leaf=_calibrated(bad))


@pytest.mark.parametrize("bad", [0.0, -5.0])
def test_metals_a_non_positive_aluminum_band_is_refused(bad: float) -> None:
    """GM7: a non-positive band makes the construction verdict unreachable."""
    with pytest.raises(ValidationError, match="aluminum_stability_band_pct"):
        _metals_settings_with(aluminum_stability_band_pct_leaf=_calibrated(bad))


@pytest.mark.parametrize("bad", [0.0, -5.0])
def test_metals_a_non_positive_broad_threshold_is_refused(bad: float) -> None:
    """GM8: a non-positive threshold makes the broad verdict fire on a RISING complex."""
    with pytest.raises(ValidationError, match="broad_weakness_threshold_pct"):
        _metals_settings_with(broad_weakness_threshold_pct_leaf=_calibrated(bad))


def test_metals_the_cap_sits_below_the_gold_cap() -> None:
    """The ordering IS the claim: a one-family sign test is weaker than gold's
    change-in-a-yield with an independent second leg."""
    assert (
        get_settings().metals_complex.reliability_value
        <= get_settings().gold_driver.reliability_value
    )
