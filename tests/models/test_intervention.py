"""Hand-computed verification suite for Module 9 — intervention capacity.

Covers the direction->constraint asymmetry (the function's entire content), the
two-producer confidence rule (computed x config cap, MULTIPLICATIVE not min()),
the direction-INDEPENDENT burn alert, the AMPLE/THIN/UNSCALED disclosure scale,
and the refusal paths. Every expected number is derived from the config leaves.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from macro_engine.config import get_settings
from macro_engine.models import intervention as iv_mod
from macro_engine.models.intervention import (
    InterventionCapacityInputs,
    intervention_capacity,
)


def _mk(
    country: str = "jpn",
    direction: str = "strengthen_own_currency",
    reserves_bn: float | None = 1083.42,
    to_gdp: float | None = None,
    burn: float | None = None,
) -> InterventionCapacityInputs:
    return InterventionCapacityInputs(
        country=country,
        direction=direction,  # type: ignore[arg-type]
        fx_reserves_usd_bn=reserves_bn,
        reserves_to_gdp_pct=to_gdp,
        reserves_change_12m_pct=burn,
    )


def _fake_reading(mn: float = 1083420.49, change: float | None = -11.98) -> SimpleNamespace:
    return SimpleNamespace(
        reserves_usd_mn=mn,
        change_12m_pct=change,
        symbol="TRESEGJPM052N",
        observation_date="2026-08-01",
    )


# ---------------------------------------------------------------------------
# Config bridging (LAW 1) — no capacity literal / threshold in code
# ---------------------------------------------------------------------------
def test_config_bridging_intervention_leaves() -> None:
    s = get_settings().intervention
    assert s.reliability_value == pytest.approx(0.12)
    assert s.burn_alert_value == pytest.approx(10.0)
    assert s.reserves_to_gdp_ample_threshold == pytest.approx(20.0)
    assert s.reserve_constrained_label == "RESERVE_CONSTRAINED_breakable"
    assert s.mechanically_unconstrained_label == "MECHANICALLY_UNCONSTRAINED_COST_BOUNDED"


def test_cap_is_the_lowest_in_the_fx_family() -> None:
    # The module/docstring claim: below uip (0.15) and ppp (0.20).
    s = get_settings()
    # NOTE: the two comparison caps live in the ``fx_carry`` block, NOT in
    # top-level ``uip``/``ppp`` blocks — there are none. Accessors are
    # ``uip_reliability_value`` / ``ppp_reliability_value``.
    assert s.intervention.reliability_value == pytest.approx(0.12)
    assert (
        s.intervention.reliability_value < s.fx_carry.uip_reliability_value == pytest.approx(0.15)
    )
    assert (
        s.intervention.reliability_value < s.fx_carry.ppp_reliability_value == pytest.approx(0.20)
    )


# ---------------------------------------------------------------------------
# The asymmetry — the whole content of the function
# ---------------------------------------------------------------------------
def test_strengthening_is_reserve_constrained() -> None:
    res = intervention_capacity(_mk(direction="strengthen_own_currency"))
    assert res.value_dict()["capacity"] == "RESERVE_CONSTRAINED_breakable"
    assert "EXHAUSTION" in res.context


def test_weakening_is_mechanically_unconstrained_cost_bounded() -> None:
    res = intervention_capacity(_mk(direction="weaken_own_currency"))
    assert res.value_dict()["capacity"] == "MECHANICALLY_UNCONSTRAINED_COST_BOUNDED"
    assert "COST-DRIVEN ABANDONMENT" in res.context


def test_the_word_unlimited_is_not_the_published_label() -> None:
    # Section 22.11 renames the spec's "UNLIMITED_AMMUNITION_but_costly".
    res = intervention_capacity(_mk(direction="weaken_own_currency"))
    assert res.value_dict()["capacity"] != "UNLIMITED_AMMUNITION_but_costly"
    assert "UNLIMITED_AMMUNITION_but_costly" not in res.interpretation


def test_direction_literal_rejects_unrecognised_value() -> None:
    # The spec's bare `else` would have sent a typo down the opposite verdict.
    with pytest.raises(ValueError):
        InterventionCapacityInputs(country="jpn", direction="strengthen", fx_reserves_usd_bn=100.0)  # type: ignore[arg-type]


def test_country_is_published_not_hardcoded() -> None:
    res = intervention_capacity(_mk(country="chn"))
    assert res.country == "chn"


# ---------------------------------------------------------------------------
# Confidence — computed x cap, MULTIPLICATIVE (min() would make it dead code)
# ---------------------------------------------------------------------------
def test_confidence_supplied_path() -> None:
    # not fetched -> data_quality flag present (-0.25) + heuristic (-0.20), no
    # independence bonus: 0.70 - 0.25 - 0.20 = 0.25 ; x cap 0.12 = 0.030
    res = intervention_capacity(_mk(direction="weaken_own_currency"))
    assert res.confidence == pytest.approx(0.25 * 0.12, abs=1e-4)
    assert res.source_family is not None and res.source_family.value == "manual_assessment"


def test_confidence_fetched_path_is_higher_than_supplied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(iv_mod, "fetch_reserves", lambda c: _fake_reading())
    # fetched -> no data-quality flag, heuristic only (-0.20), +0.05 independence:
    # 0.70 - 0.20 + 0.05 = 0.55 ; x cap 0.12 = 0.066
    res = intervention_capacity(_mk(reserves_bn=None, direction="weaken_own_currency"))
    assert res.confidence == pytest.approx(0.55 * 0.12, abs=1e-4)
    # The multiplicative rule is what makes the fetched path beat the supplied one.
    supplied = intervention_capacity(_mk(direction="weaken_own_currency"))
    assert res.confidence > supplied.confidence


def test_confidence_family_is_imf_when_fetched(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(iv_mod, "fetch_reserves", lambda c: _fake_reading())
    res = intervention_capacity(_mk(reserves_bn=None, direction="weaken_own_currency"))
    assert res.source_family is not None and res.source_family.value == "imf"


# ---------------------------------------------------------------------------
# The burn alert is DIRECTION-INDEPENDENT (the fix the test drove)
# ---------------------------------------------------------------------------
def test_burn_alert_fires_on_strengthening() -> None:
    res = intervention_capacity(_mk(direction="strengthen_own_currency", burn=-11.98))
    assert any("Reserves are BURNING" in w for w in res.warnings)


def test_burn_alert_also_fires_on_weakening() -> None:
    # A reserve burn is a fact about the world, not about the direction.
    res = intervention_capacity(_mk(direction="weaken_own_currency", burn=-11.98))
    assert any("Reserves are BURNING" in w for w in res.warnings)


def test_burn_alert_boundary_is_inclusive_at_minus_10() -> None:
    # `burn_pct <= -burn_alert_value` -> exactly -10.0 fires.
    at = intervention_capacity(_mk(direction="weaken_own_currency", burn=-10.0))
    assert any("Reserves are BURNING" in w for w in at.warnings)
    just_inside = intervention_capacity(_mk(direction="weaken_own_currency", burn=-9.99))
    assert not any("Reserves are BURNING" in w for w in just_inside.warnings)


def test_a_rising_reserve_stock_does_not_alert() -> None:
    res = intervention_capacity(_mk(direction="weaken_own_currency", burn=+12.0))
    assert not any("Reserves are BURNING" in w for w in res.warnings)


def test_missing_burn_is_disclosed_as_unknown() -> None:
    res = intervention_capacity(_mk(direction="weaken_own_currency", burn=None))
    assert any("DEPLETION RATE" in w and "UNKNOWN" in w for w in res.warnings)


# ---------------------------------------------------------------------------
# AMPLE / THIN / UNSCALED — a disclosure, never a gate on the label
# ---------------------------------------------------------------------------
def test_scale_ample_at_threshold_and_thin_below() -> None:
    at = intervention_capacity(_mk(direction="weaken_own_currency", to_gdp=20.0))
    assert at.value_dict()["reserves_scale"] == "AMPLE"
    below = intervention_capacity(_mk(direction="weaken_own_currency", to_gdp=19.99))
    assert below.value_dict()["reserves_scale"] == "THIN"


def test_scale_unscaled_when_absent() -> None:
    res = intervention_capacity(_mk(direction="weaken_own_currency", to_gdp=None))
    assert res.value_dict()["reserves_scale"] == "UNSCALED"


def test_scale_does_not_change_the_capacity_label() -> None:
    thin = intervention_capacity(_mk(direction="strengthen_own_currency", to_gdp=1.0))
    ample = intervention_capacity(_mk(direction="strengthen_own_currency", to_gdp=90.0))
    assert (
        thin.value_dict()["capacity"]
        == ample.value_dict()["capacity"]
        == "RESERVE_CONSTRAINED_breakable"
    )


# ---------------------------------------------------------------------------
# Refusals — a null must not travel as a value
# ---------------------------------------------------------------------------
def test_strengthening_without_reserves_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(iv_mod, "fetch_reserves", lambda c: None)
    with pytest.raises(ValueError, match="cannot be supported and is not made"):
        intervention_capacity(_mk(reserves_bn=None, direction="strengthen_own_currency"))


def test_weakening_without_reserves_proceeds_and_discloses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(iv_mod, "fetch_reserves", lambda c: None)
    res = intervention_capacity(_mk(reserves_bn=None, direction="weaken_own_currency"))
    assert res.value_dict()["reserves_usd_bn"] is None
    assert any("NOT AVAILABLE" in p for p in res.data_provenance)


def test_fetch_error_is_surfaced_not_raised_prematurely(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_c: object) -> None:
        raise iv_mod.ReservesReadError("registry miss")  # type: ignore[attr-defined]

    monkeypatch.setattr(iv_mod, "fetch_reserves", boom)
    res = intervention_capacity(_mk(reserves_bn=None, direction="weaken_own_currency"))
    assert any("reserve fetch failed" in p for p in res.data_provenance)


def test_non_positive_reserves_refused() -> None:
    with pytest.raises(ValueError, match="strictly positive"):
        InterventionCapacityInputs(
            country="jpn", direction="weaken_own_currency", fx_reserves_usd_bn=0.0
        )
    with pytest.raises(ValueError, match="strictly positive"):
        InterventionCapacityInputs(
            country="jpn", direction="weaken_own_currency", fx_reserves_usd_bn=-5.0
        )


def test_non_finite_reserves_refused_by_finite_inputs() -> None:
    with pytest.raises(ValueError):
        InterventionCapacityInputs(
            country="jpn", direction="weaken_own_currency", fx_reserves_usd_bn=float("nan")
        )


# ---------------------------------------------------------------------------
# The fetch path: millions -> billions conversion (the 1000x trap)
# ---------------------------------------------------------------------------
def test_fetched_millions_are_converted_to_billions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(iv_mod, "fetch_reserves", lambda c: _fake_reading(mn=1083420.49))
    res = intervention_capacity(_mk(reserves_bn=None, direction="weaken_own_currency"))
    # 1,083,420.49 millions / 1000 = 1,083.42049 billions
    assert res.value_dict()["reserves_usd_bn"] == pytest.approx(1083.42049, abs=1e-4)
    assert any("FETCHED" in p for p in res.data_provenance)
    assert any("millions" in p for p in res.data_provenance)


def test_fetched_burn_is_used_when_caller_supplies_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(iv_mod, "fetch_reserves", lambda c: _fake_reading(change=-11.98))
    res = intervention_capacity(
        _mk(reserves_bn=None, burn=None, direction="strengthen_own_currency")
    )
    assert res.value_dict()["reserves_change_12m_pct"] == pytest.approx(-11.98)


def test_supplied_reserves_are_disclosed_as_supplied() -> None:
    res = intervention_capacity(_mk(direction="weaken_own_currency"))
    assert any("SUPPLIED BY THE CALLER" in p for p in res.data_provenance)


# ---------------------------------------------------------------------------
# Contract fields
# ---------------------------------------------------------------------------
def test_unit_is_declared_and_value_carries_documented_keys() -> None:
    res = intervention_capacity(_mk(direction="weaken_own_currency", to_gdp=25.0, burn=-15.0))
    assert res.unit == "usd_billions"
    assert set(res.value_dict().keys()) == {
        "capacity",
        "reserves_usd_bn",
        "reserves_change_12m_pct",
        "reserves_to_gdp_pct",
        "reserves_scale",
        "direction",
    }
