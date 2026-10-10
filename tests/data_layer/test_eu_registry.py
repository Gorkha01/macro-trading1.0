"""The euro-area (country "eu") registry block and the ``extra_params`` surface.

Two things are tested here and they are different kinds of claim:

1. **The euro-area entries.** Section 22.3 requires a country's data leg to be
   its OWN verified sources — not a relabel of another country's. Most of these
   tests assert that a *declared* property of an entry is the property the
   fetch path will actually use, because the failure mode when it is not is
   silent: a euro series fetched with a US unit reads as a plausible number.

2. **``extra_params``.** Adding the euro legs forced this surface into
   existence: the scalar fetcher hardcoded ``{"symbol":..., "start_date":...}``
   and could not express ``economy.indicators`` (provider ``econdb``), which
   needs ``country=EU``. The tests below pin the three properties that make it
   safe — it is merged, it cannot shadow ``symbol``, and the shadowing refusal
   is at LOAD time rather than at fetch time.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from macro_engine.config import RegistrySeries, get_registry, get_settings
from macro_engine.data_layer.snapshot_builder import fetch_field

# ---------------------------------------------------------------------------
# The euro-area entries: declared properties must be the ones used
# ---------------------------------------------------------------------------


def test_the_euro_area_entries_exist_and_are_verified() -> None:
    """Each ``eu_*`` entry is present, verified, and carries rule-5 evidence.

    Section 21.1 requires a verified series ID before use; ``_verified_requires_evidence``
    enforces the evidence at load, so this test asserts the SET rather than
    re-checking a validator that already ran. A missing entry would otherwise
    surface as a fetch that returns nothing and is treated as "no data".
    """
    registry = get_registry()
    expected = {
        "eu_hicp_index",
        "eu_ecb_deposit_rate",
        "eu_ecb_main_refi_rate",
        "eu_estr",
        "eu_unemployment_rate",
        "eu_gdp_real_level",
        "eu_short_rate_3m",
        "eu_long_rate_10y",
    }
    missing = expected - set(registry.series)
    assert not missing, f"euro-area entries missing from the registry: {sorted(missing)}"
    for key in expected:
        entry = registry.require_verified(key)
        assert entry.verified_on is not None
        assert entry.verified_value is not None


def test_the_eu_fetch_plan_names_registry_keys_that_resolve() -> None:
    """Every key in ``snapshot_fields.eu`` resolves to a real snapshot field.

    The UK leg's lesson, kept for the euro leg: ``snapshot_fields`` holds
    REGISTRY KEYS and the schema holds ATTRIBUTES. The two coincide for the
    euro block (so the divergence bug the UK hit cannot bite here), and this
    test is what would catch a future edit that broke the coincidence.
    """
    settings = get_settings()
    registry = get_registry()
    from macro_engine.data_layer.schemas import MacroDataSnapshot

    fields = set(MacroDataSnapshot.model_fields)
    plan = settings.snapshot_fields["eu"]
    assert plan, "the eu fetch plan is empty; the euro block would never be fetched"
    for key in plan:
        assert key in registry.series, f"eu plan names {key!r}, which is not a registry key"
        entry = registry.series[key]
        attr = entry.snapshot_field or key
        # `model_fields`, not `hasattr`: pydantic v2 keeps field names in the
        # model's field map rather than as class attributes, so `hasattr` on the
        # CLASS is the wrong probe and would pass for a name that is not a field.
        assert attr in fields, (
            f"eu entry {key!r} maps to schema attribute {attr!r}, which does not exist"
        )


def test_the_euro_area_has_no_declared_hicp_rate_or_gdp_growth_field() -> None:
    """The two euro RATES are derived, so no field is declared for them.

    The euro area publishes an HICP INDEX and a real GDP LEVEL currently, and
    its HICP-rate and GDP-growth series are stale (measured: the OECD HICP rate
    stops 2025-12, ``NAEXKP01EZQ657S`` stops 2023-01). A declared field that no
    fetch can populate is the "declared, consumed, unreachable" defect class —
    so the derivation is a MODELS-layer step and no snapshot field exists. This
    test pins the ABSENCE, which is the half a presence-check cannot see.
    """
    from macro_engine.data_layer.persistence import SCALAR_SERIES_FIELDS
    from macro_engine.data_layer.schemas import MacroDataSnapshot

    fields = set(MacroDataSnapshot.model_fields)
    assert "eu_hicp_yoy" not in fields
    assert "eu_gdp_growth_qoq" not in fields
    assert "eu_hicp_yoy" not in SCALAR_SERIES_FIELDS
    assert "eu_gdp_growth_qoq" not in SCALAR_SERIES_FIELDS
    # ...and the inputs the derivations consume ARE present.
    assert "eu_hicp_index" in fields
    assert "eu_gdp_real_level" in fields


def test_the_euro_long_rate_declares_a_fraction_source_scale() -> None:
    """``eu_long_rate_10y`` is served as a FRACTION and converted to percent.

    Measured 2026-10-10: ``economy.indicators``/``Y10YD`` returns 0.03748 for a
    ~3.75% yield. The x100 is derived from ``source_units: decimal`` rather
    than hand-written, so a route swap cannot silently leave a 100x error —
    both 3.748 and 0.03748 are plausible-looking rates.
    """
    entry = get_registry().series["eu_long_rate_10y"]
    assert entry.units == "percent"
    assert entry.source_units == "decimal"
    assert entry.unit_scale_to_units == pytest.approx(100.0)
    # The recorded evidence is stated in the ENGINE's unit (percent), not the
    # route's (fraction) — otherwise a reader comparing the value to
    # plausible_range would be comparing across scales.
    assert entry.verified_value == pytest.approx(3.748, abs=1e-3)
    value = entry.verified_value
    assert entry.plausible_range is not None
    low, high = entry.plausible_range
    assert value is not None
    assert low <= value <= high


def test_no_other_euro_entry_declares_a_source_scale() -> None:
    """Only the one route that needs scaling declares one.

    A ``source_units`` on an entry whose route already returns percent would
    multiply a correct value by 1.0 and be harmless — but it would also mean the
    declaration is not load-bearing, and the value in a config file that nothing
    depends on is where a wrong value survives. This test says the six FRED
    percent entries and the index/level entries declare none.
    """
    registry = get_registry()
    for key in (
        "eu_ecb_deposit_rate",
        "eu_ecb_main_refi_rate",
        "eu_estr",
        "eu_unemployment_rate",
        "eu_short_rate_3m",
        "eu_hicp_index",
        "eu_gdp_real_level",
    ):
        entry = registry.series[key]
        assert entry.source_units is None, f"{key} declares a source_units it does not need"
        assert entry.unit_scale_to_units is None


def test_the_unemployment_leg_is_on_the_econdb_route_with_a_country_param() -> None:
    """The one euro leg that needs route parameters beyond ``symbol``.

    Every FRED euro-area unemployment variant stops in <=2023 (measured), so the
    leg is reachable ONLY through ``econdb`` — whose ``economy.indicators`` route
    requires BOTH ``country`` and ``frequency``. Both are declared in the
    registry, per Section 21.1's "the registry is the only source of routing".

    ``frequency`` was a real WS1 defect: the route was declared with ``country``
    alone, and OpenBB validated the kwargs against the ``imf`` provider (whose
    parameter model has no ``frequency``) before ever reaching ``econdb`` — so
    the fetch failed naming a provider the registry had not asked for. The
    registry must therefore carry every parameter the NAMED provider requires.
    """
    entry = get_registry().series["eu_unemployment_rate"]
    assert entry.provider == "econdb"
    assert entry.endpoint == "economy.indicators"
    assert entry.symbol == "URATE"
    assert entry.extra_params == {"country": "EU", "frequency": "month"}
    assert entry.units == "percent"


# ---------------------------------------------------------------------------
# The extra_params surface
# ---------------------------------------------------------------------------


def test_extra_params_cannot_shadow_symbol_or_start_date() -> None:
    """A reserved key is refused at LOAD, not merged at fetch.

    A shadowed ``symbol`` changes which series is read while every recorded
    evidence field (description, verified_value, plausible_range) still describes
    the original — a wrong fact wearing a verification's clothes. Refusing at
    load makes the misconfiguration impossible rather than merely unreachable.
    """
    for reserved in ("symbol", "start_date"):
        with pytest.raises(ValueError, match="extra_params"):
            RegistrySeries(
                provider="econdb",
                endpoint="economy.indicators",
                symbol="URATE",
                extra_params={reserved: "SHADOW"},
                status="verified",
                verified_on="2026-10-10",  # type: ignore[arg-type]
                verified_value=6.1,
            )


def test_extra_params_is_optional_and_none_by_default() -> None:
    """Every pre-existing entry is unchanged: ``None`` means "symbol is enough"."""
    assert get_registry().series["cpi_headline"].extra_params is None


def test_fetch_field_passes_extra_params_to_the_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """The declared parameters reach the call, merged UNDER the fetcher's own.

    This is the load-bearing test for the surface: without it, ``extra_params``
    is a field nothing reads, and the euro unemployment leg would fetch with no
    ``country`` and fail at the provider — reported as a missing series rather
    than a misconfiguration.
    """
    seen: dict[str, Any] = {}

    class _Client:
        def fetch_series(
            self,
            *,
            provider: str,
            endpoint: str,
            params: dict[str, Any],
            series_label: str,
        ) -> pd.DataFrame:
            seen["provider"] = provider
            seen["endpoint"] = endpoint
            seen["params"] = dict(params)
            return pd.DataFrame(
                {
                    "date": [pd.Timestamp("2026-08-01")],
                    "value": [6.1],
                    "series_id": [series_label],
                    "source": ["econdb"],
                    "retrieved_at": [pd.Timestamp("2026-10-10")],
                }
            )

        def close(self) -> None:  # pragma: no cover - unused by fetch_field
            pass

    entry = get_registry().series["eu_unemployment_rate"]
    points = fetch_field(_Client(), "eu_unemployment_rate", entry, start="2026-01-01")  # type: ignore[arg-type]

    assert seen["provider"] == "econdb"
    assert seen["endpoint"] == "economy.indicators"
    assert seen["params"]["country"] == "EU", "the declared country param did not reach the call"
    assert seen["params"]["symbol"] == "URATE"
    assert seen["params"]["start_date"] == "2026-01-01"
    assert len(points) == 1
    assert points[0].value == pytest.approx(6.1)


def test_the_fetcher_owns_symbol_and_start_date_even_if_extra_params_tried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The merge order makes the fetcher's keys win — belt and braces.

    The config validator already refuses the shadowing combination, so this
    guard is unreachable through the registry. It is asserted anyway because the
    merge happens in a different file from the validator, and the failure it
    prevents (reading a different series than the entry verifies) is silent. A
    future edit that relaxed the validator would leave this as the last line of
    defence rather than as nothing.
    """
    seen: dict[str, Any] = {}

    class _Client:
        def fetch_series(
            self, *, provider: str, endpoint: str, params: dict[str, Any], series_label: str
        ) -> pd.DataFrame:
            seen["params"] = dict(params)
            return pd.DataFrame(
                {
                    "date": [pd.Timestamp("2026-08-01")],
                    "value": [1.0],
                    "series_id": [series_label],
                    "source": ["x"],
                    "retrieved_at": [pd.Timestamp("2026-10-10")],
                }
            )

        def close(self) -> None:  # pragma: no cover
            pass

    # Construct an entry that BYPASSES the validator's refusal, standing in for
    # a future relaxation of it.
    entry = RegistrySeries.model_construct(
        provider="econdb",
        endpoint="economy.indicators",
        symbol="URATE",
        extra_params={"symbol": "SHADOW", "start_date": "1999-01-01", "country": "EU"},
        status="verified",
    )
    fetch_field(_Client(), "eu_unemployment_rate", entry, start="2026-01-01")  # type: ignore[arg-type]

    assert seen["params"]["symbol"] == "URATE", "extra_params shadowed the real symbol"
    assert seen["params"]["start_date"] == "2026-01-01", "extra_params shadowed the real window"
    assert seen["params"]["country"] == "EU", "the non-reserved key was dropped"
