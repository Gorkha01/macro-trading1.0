"""Tests for Module 10's ``oil_balance_signal`` (Section 6.8).

Every fixture here is DERIVED from the config leaves rather than hardcoded, so a
leaf change moves the test with it instead of silently testing a stale number
(the ``C6b`` class, D-031). The boundary cases sit exactly ON the tightness
threshold so a mutant that flips ``>`` to ``>=`` cannot survive a fixture set
that never touches it.

The model is the simplest in the repository — one subtraction and a sign flip —
so the decisions a future edit is most likely to break are exactly the ones
asserted here:

* the **sign convention** (a draw tightens),
* the **rounding** to the config-declared precision,
* the **confidence PRODUCT** (not ``min()`` — the D-118/D-119 rule),
* the **refusal** when a leg is absent,
* the **result contract** (unit, direction, family, both inputs named), and
* the **disclosure** that discriminates a fetched leg from a supplied one.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from macro_engine.config import CalibratedValue, OilBalanceSettings, get_settings
from macro_engine.models.commodities import OilBalanceInputs, oil_balance_signal
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
