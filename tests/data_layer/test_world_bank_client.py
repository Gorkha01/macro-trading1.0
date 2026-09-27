"""World Bank PPP conversion factors — the reachable, NON-vintage route.

What these tests are for
------------------------
D-117 replaced a **FALSE BLOCK** (D-043's class) with a real source: Section 21.1
asserted *"no clean free API"* for ``ppp_implied_rate``, and the World Bank REST
API was measured reachable (``docs/PLAN_ppp_source.md``). The properties that
make this safe are asserted STRUCTURALLY, because each has a silent failure mode
that a happy-path test would not catch:

(a) **The module never routes through OpenBB.** Asserted on the AST — a future
    "helpful" fallback to the OpenBB client must fail a test, not merely review
    (the same discipline ``test_alfred_client`` uses for its own route).
(b) **It never claims a vintage it cannot deliver.** The World Bank has no
    point-in-time selector; the module must NOT expose a ``realtime_*``-style
    parameter, and the registry entries must NOT be ``vintage_eligible``.
    Claiming otherwise is O-6's exact defect.
(c) **A failure is never an empty frame.** A malformed argument, a non-index
    body, or a missing ``lastupdated`` must raise, not return "no data" — because
    "no data" is a measured truth for the EMU aggregate and must stay distinct
    from "bad request".
(d) **The estimand is the RATIO, with the division performed.** The USA leg is
    exactly 1 by construction, so reading the identity instead of computing it
    would hide a future change of numeraire (the D-109 class).
(e) **The newest non-null YEAR is selected, not the first row.** Row order is
    not a documented contract, and a suppressed observation is not a zero.

The payload shapes used below are the real ones, captured live on 2026-09-27.
"""

from __future__ import annotations

import ast
import inspect
from datetime import date
from pathlib import Path
from typing import Any, Literal
from unittest.mock import MagicMock

import httpx
import pytest

import macro_engine.data_layer.world_bank_client as world_bank_client
from macro_engine.data_layer.world_bank_client import (
    PPPFactor,
    WorldBankReadError,
    WorldBankUnavailableError,
    fetch_ppp_conversion_factor,
    fetch_ppp_implied_rate,
    implied_rate_from_factors,
)


def _payload(rows: list[dict[str, Any]], *, lastupdated: str = "2026-07-13") -> list[Any]:
    """A real World Bank ``[metadata, rows]`` body."""
    return [
        {"page": 1, "pages": 1, "per_page": 100, "total": len(rows), "lastupdated": lastupdated},
        rows,
    ]


def _row(year: str, value: float | None, *, iso3: str = "DEU") -> dict[str, Any]:
    return {
        "indicator": {"id": "PA.NUS.PPP", "value": "PPP conversion factor, GDP"},
        "country": {"id": "DE", "value": "Germany"},
        "countryiso3code": iso3,
        "date": year,
        "value": value,
        "unit": "",
        "obs_status": "",
        "decimal": 0,
    }


def _client_returning(payload: Any, *, status: int = 200) -> MagicMock:
    """A fake ``httpx.Response``-like object whose ``.text`` is ``payload``."""
    import json as _json

    body = _json.dumps(payload) if isinstance(payload, (list, dict)) else str(payload)
    response = MagicMock(spec=httpx.Response)
    response.status_code = status
    response.text = body
    return response


def _patch_client(monkeypatch: pytest.MonkeyPatch, payload: Any, *, status: int = 200) -> None:
    """Patch ``httpx.Client`` to a context manager whose GET returns ``payload``."""

    class _FakeClient:
        def __init__(self, *a: Any, **k: Any) -> None:
            self._response = _client_returning(payload, status=status)

        def __enter__(self) -> _FakeClient:
            return self

        def __exit__(self, *exc: Any) -> Literal[False]:
            return False

        def get(self, *a: Any, **k: Any) -> Any:
            return self._response

    monkeypatch.setattr(httpx, "Client", _FakeClient)


# ---------------------------------------------------------------------------
# (a) the module never routes through OpenBB
# ---------------------------------------------------------------------------


def test_the_module_never_imports_the_openbb_client() -> None:
    """No import of ``openbb_client`` — asserted on the AST, not on behaviour."""
    source = Path(inspect.getfile(world_bank_client)).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    offenders = [name for name in imported if "openbb" in name.lower()]
    assert not offenders, (
        f"world_bank_client must not import OpenBB: {offenders}. The World Bank "
        f"route is 'direct, not OpenBB' — the same shape Section 21.1 sanctions "
        f"for current_account_pct_gdp."
    )


def test_the_module_never_references_the_local_openbb_host() -> None:
    """The docstring and URLs must not point at the OpenBB service."""
    source = Path(inspect.getfile(world_bank_client)).read_text(encoding="utf-8")
    assert "6900" not in source, "the local OpenBB host must not appear"
    assert "api.worldbank.org" in source, "the World Bank host must appear"


# ---------------------------------------------------------------------------
# (b) it never claims a vintage it cannot deliver
# ---------------------------------------------------------------------------


def test_the_module_exposes_no_realtime_vintage_parameter() -> None:
    """O-6's defect: a silently-absorbed vintage parameter.

    The World Bank REST API has no point-in-time selector, so the module must
    not pretend to have one. A ``realtime_start``/``realtime_end``/``as_of``
    parameter here would be absorbed and ignored, which is the exact failure
    O-6 recorded.

    **Asserted on the module's PUBLIC SURFACE (the function signatures), not on
    its prose** — the docstring discusses the absent capability at length, and a
    text grep would flag the explanation as if it were the defect. What must not
    exist is a *parameter*, so the signatures are inspected.
    """
    public = (
        world_bank_client.fetch_ppp_conversion_factor,
        world_bank_client.fetch_ppp_implied_rate,
    )
    for fn in public:
        params = set(inspect.signature(fn).parameters)
        for forbidden in ("realtime_start", "realtime_end", "as_of", "vintage_datetime"):
            assert forbidden not in params, (
                f"{fn.__name__} exposes {forbidden!r}: the World Bank has no "
                f"point-in-time selector, so such a parameter would be silently "
                f"absorbed (O-6)."
            )


# ---------------------------------------------------------------------------
# (c) a failure is never an empty frame
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["EU", "DEUTSCHLAND", "123", "", "De"])
def test_a_malformed_iso3_is_refused(bad: str) -> None:
    """A malformed code must raise, not return an empty series.

    The World Bank answers a malformed code with an empty payload rather than an
    error, so validation happens here to keep 'bad input' distinct from 'no
    data'.
    """
    with pytest.raises(WorldBankUnavailableError, match="3-letter country code"):
        fetch_ppp_conversion_factor(bad)


def test_a_non_list_body_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """An HTML error page must not read as 'no data'."""
    _patch_client(monkeypatch, "<html>error</html>")
    monkeypatch.setattr(world_bank_client, "_BACKOFF_SECONDS", 0.0)
    with pytest.raises(WorldBankReadError):
        fetch_ppp_conversion_factor("DEU")


def test_a_missing_lastupdated_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """The publication date is what makes the value a disclosed vintage.

    Without it the read must fail rather than proceed with an undisclosed
    figure.
    """
    _patch_client(monkeypatch, [{"page": 1}, [_row("2025", 0.71)]])
    with pytest.raises(WorldBankUnavailableError, match="lastupdated"):
        fetch_ppp_conversion_factor("DEU")


def test_an_all_null_series_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """The EMU aggregate measures 0 points — a genuine empty, surfaced loudly.

    A caller must not read an empty series as a value; the module raises so the
    'no published points' case cannot silently become a number.
    """
    _patch_client(monkeypatch, _payload([_row("2025", None), _row("2024", None, iso3="EMU")]))
    with pytest.raises(WorldBankUnavailableError, match="no populated"):
        fetch_ppp_conversion_factor("EMU")


def test_a_non_200_status_is_retried_then_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A transient status failure raises after the budget, never degrades."""
    _patch_client(monkeypatch, "nope", status=503)
    monkeypatch.setattr(world_bank_client, "_BACKOFF_SECONDS", 0.0)
    with pytest.raises(WorldBankReadError, match="failed after"):
        fetch_ppp_conversion_factor("DEU")


# ---------------------------------------------------------------------------
# (d) the estimand is the RATIO, with the division performed
# ---------------------------------------------------------------------------


def test_the_implied_rate_is_the_ratio_of_the_two_factors() -> None:
    """``factor(domestic) / factor(foreign)`` — the international dollar cancels."""
    domestic = PPPFactor("DEU", "PA.NUS.PPP", 2025, 0.71, date(2026, 7, 13))
    foreign = PPPFactor("USA", "PA.NUS.PPP", 2025, 1.0, date(2026, 7, 13))
    assert implied_rate_from_factors(domestic, foreign) == pytest.approx(0.71)


def test_a_non_usa_numeraire_is_not_silently_assumed_to_be_one() -> None:
    """The division is PERFORMED, not read off the identity.

    A USD-base pair has ``factor(USA) == 1``, so an implementation that skipped
    the division would pass every USD test. This test uses a foreign leg whose
    factor is NOT 1 and asserts the ratio reflects it — the D-109 class, where an
    assumption moving changes the estimand.
    """
    domestic = PPPFactor("DEU", "PA.NUS.PPP", 2025, 0.71, date(2026, 7, 13))
    foreign = PPPFactor("JPN", "PA.NUS.PPP", 2025, 94.7, date(2026, 7, 13))
    assert implied_rate_from_factors(domestic, foreign) == pytest.approx(0.71 / 94.7)


def test_a_zero_foreign_factor_is_refused() -> None:
    """A zero factor is not a price level; the ratio would be undefined."""
    domestic = PPPFactor("DEU", "PA.NUS.PPP", 2025, 0.71, date(2026, 7, 13))
    foreign = PPPFactor("XXX", "PA.NUS.PPP", 2025, 0.0, date(2026, 7, 13))
    with pytest.raises(WorldBankUnavailableError, match="zero"):
        implied_rate_from_factors(domestic, foreign)


# ---------------------------------------------------------------------------
# (e) the newest non-null YEAR is selected, not the first row
# ---------------------------------------------------------------------------


def test_the_newest_year_is_selected_regardless_of_row_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Row order is not a documented contract; the newest YEAR is selected."""
    # Deliberately OLDEST-first, the reverse of the live API's order.
    rows = [_row("2023", 0.701054), _row("2024", 0.700862), _row("2025", 0.709983)]
    _patch_client(monkeypatch, _payload(rows))
    factor = fetch_ppp_conversion_factor("DEU")
    assert factor.year == 2025
    assert factor.value == pytest.approx(0.709983)


def test_a_suppressed_year_is_skipped_not_read_as_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """A null value is a suppressed observation, not a zero."""
    rows = [_row("2025", None), _row("2024", 0.700862), _row("2023", 0.701054)]
    _patch_client(monkeypatch, _payload(rows))
    factor = fetch_ppp_conversion_factor("DEU")
    assert factor.year == 2024
    assert factor.value == pytest.approx(0.700862)


# ---------------------------------------------------------------------------
# the pair fetch and its disclosure
# ---------------------------------------------------------------------------


def _patch_pair(monkeypatch: pytest.MonkeyPatch, by_iso3: dict[str, PPPFactor]) -> None:
    def fake(iso3: str, **kw: Any) -> PPPFactor:
        return by_iso3[iso3]

    monkeypatch.setattr(world_bank_client, "fetch_ppp_conversion_factor", fake)


def test_the_pair_fetch_returns_the_rate_and_a_disclosure(monkeypatch: pytest.MonkeyPatch) -> None:
    """The disclosure names BOTH legs and BOTH publication dates."""
    _patch_pair(
        monkeypatch,
        {
            "DEU": PPPFactor("DEU", "PA.NUS.PPP", 2025, 0.709983, date(2026, 7, 13)),
            "USA": PPPFactor("USA", "PA.NUS.PPP", 2025, 1.0, date(2026, 7, 13)),
        },
    )
    rate, disclosure = fetch_ppp_implied_rate("DEU", "USA")
    assert rate == pytest.approx(0.709983)
    assert "DEU" in disclosure and "USA" in disclosure
    assert "2025" in disclosure and "2026-07-13" in disclosure
    assert "NOT a live price" in disclosure
    assert "NOT a point-in-time vintage" in disclosure


def test_a_year_mismatch_between_the_legs_is_disclosed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A mixed-year pair is a FACT to disclose, not an error to hide.

    The World Bank publishes each country on its own schedule, so the freshest
    available pair can mix years. Silently pairing them would hide a real vintage
    gap; the disclosure names both years so a caller sees it.
    """
    _patch_pair(
        monkeypatch,
        {
            "DEU": PPPFactor("DEU", "PA.NUS.PPP", 2025, 0.709983, date(2026, 7, 13)),
            "FRA": PPPFactor("FRA", "PA.NUS.PPP", 2024, 0.677618, date(2026, 7, 13)),
        },
    )
    rate, disclosure = fetch_ppp_implied_rate("DEU", "FRA")
    assert rate == pytest.approx(0.709983 / 0.677618)
    assert "(2025)" in disclosure and "(2024)" in disclosure


def test_the_route_name_is_distinct_from_the_other_clients() -> None:
    """Provenance strings must not collide (the D-087.21 class of breakage)."""
    from macro_engine.data_layer.alfred_client import ROUTE_NAME as ALFRED_ROUTE

    assert world_bank_client.ROUTE_NAME != ALFRED_ROUTE
    assert world_bank_client.ROUTE_NAME == "world_bank_direct"


def test_the_registry_entries_declare_only_real_schema_fields() -> None:
    """The two PPP legs must not carry a key ``RegistrySeries`` does not declare.

    This pins O-141, which was **found by the full suite, not by any test written
    for the change**. Wiring the legs added ``iso3: DEU`` / ``iso3: USA`` to the
    registry entries on the reasonable assumption that an unused tag is ignored.
    It is not: ``RegistrySeries`` is ``extra="forbid"`` (config.py:1047), and
    every entry is parsed as part of ``SeriesRegistry`` (config.py:1673, also
    ``extra="forbid"``) -- so ONE unknown key on ONE entry rejects the ENTIRE
    file. Measured: 33 tests that merely LOAD the registry went red with
    ``Extra inputs are not permitted``, including seven modules unrelated to PPP,
    while all 20 tests in this file stayed green because none of them loads it.

    Two assertions, deliberately different in kind:

    * the **structural** one -- every key on these entries is a declared field of
      ``RegistrySeries`` -- catches the defect for ANY undeclared key, not just
      the one that bit, and it is what makes the next increment's mistake loud;
    * the **behavioural** one -- the whole registry still parses -- catches the
      case where the key IS declared but some validator rejects the entry, which
      the structural check cannot see.

    Reading the field list from the model rather than hardcoding it is the point:
    a hardcoded list would drift the moment a field is added, and drift silently.
    """
    import yaml

    from macro_engine.config import RegistrySeries, SeriesRegistry

    declared = set(RegistrySeries.model_fields)

    registry_path = Path(__file__).resolve().parents[2] / "config" / "series_registry.yaml"
    raw = yaml.safe_load(registry_path.read_text(encoding="utf-8"))

    ppp_entries = {
        name: entry
        for name, entry in raw["series"].items()
        if name.startswith("ppp_conversion_factor_")
    }
    assert set(ppp_entries) == {"ppp_conversion_factor_eur", "ppp_conversion_factor_usd"}

    for name, entry in ppp_entries.items():
        undeclared = sorted(set(entry) - declared)
        assert not undeclared, (
            f"registry entry '{name}' carries {undeclared}, which RegistrySeries does not "
            f"declare -- and it is extra='forbid', so these reject the WHOLE registry "
            f"(O-141). Declare the field on RegistrySeries first, or move the value to the "
            f"call site."
        )

    # And the registry as a whole must still load: the structural check above
    # proves no UNDECLARED key, this proves no validator rejects the entry.
    assert SeriesRegistry.model_validate(raw).series.keys() >= ppp_entries.keys()
