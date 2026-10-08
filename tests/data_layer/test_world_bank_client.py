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


# ===========================================================================
# D-119 — the general indicator reader and the DERIVED coverage ratio
# ===========================================================================
# `em_vulnerability_checklist` needed three indicators and a two-leg division,
# so the transport core was extracted into a shared helper and two public
# functions were added. These tests assert the properties that make the new
# surface safe, in the same structural style as the PPP block above:
#
# (f) The shared helper is SHARED — `fetch_ppp_conversion_factor` must delegate
#     to it, because two copies of "newest non-null year, empty is not failed"
#     is how the two routes drift apart.
# (g) The coverage ratio PERFORMED the division and did NOT convert units.
# (h) A zero denominator raises rather than returning an infinite ratio, which
#     would read as "perfectly covered" to any caller comparing against 1.0.
# (i) The two indicators really are the ones Section 21.1 names.


def _indicator_row(
    year: str, value: float | None, *, indicator: str, iso3: str = "TUR"
) -> dict[str, Any]:
    """A real World Bank row for an arbitrary indicator."""
    return {
        "indicator": {"id": indicator, "value": indicator},
        "country": {"id": "TR", "value": "Turkiye"},
        "countryiso3code": iso3,
        "date": year,
        "value": value,
        "unit": "",
        "obs_status": "",
        "decimal": 0,
    }


def test_the_indicator_codes_are_the_ones_the_authority_names() -> None:
    """(i) A wrong indicator code returns a different series, not an error.

    Section 21.1 names `BN.CAB.XOKA.GD.ZS` for the current account, and the
    coverage ratio is DERIVED from reserves over short-term external debt. The
    codes are asserted here so a typo that silently fetches an unrelated series
    fails a test rather than producing a plausible-looking wrong number.
    """
    assert world_bank_client.CURRENT_ACCOUNT_PCT_GDP_INDICATOR == "BN.CAB.XOKA.GD.ZS"
    assert world_bank_client.RESERVES_TOTAL_USD_INDICATOR == "FI.RES.TOTL.CD"
    assert world_bank_client.SHORT_TERM_EXTERNAL_DEBT_USD_INDICATOR == "DT.DOD.DSTC.CD"


def test_fetch_indicator_reading_returns_the_latest_non_null_year(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The newest YEAR wins, and a null in a newer row is skipped, not read as 0."""
    rows = [
        _indicator_row("2025", None, indicator="BN.CAB.XOKA.GD.ZS"),
        _indicator_row("2024", -0.77, indicator="BN.CAB.XOKA.GD.ZS"),
        _indicator_row("2023", -3.63, indicator="BN.CAB.XOKA.GD.ZS"),
    ]
    _patch_client(monkeypatch, _payload(rows))
    reading = world_bank_client.fetch_indicator_reading("TUR", "BN.CAB.XOKA.GD.ZS")
    assert reading.year == 2024
    assert reading.value == -0.77
    assert reading.iso3 == "TUR"


def test_fetch_indicator_reading_raises_on_an_empty_series(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty series is a failure, never a zero (the EMU-aggregate lesson)."""
    rows = [_indicator_row("2024", None, indicator="BN.CAB.XOKA.GD.ZS")]
    _patch_client(monkeypatch, _payload(rows))
    with pytest.raises(WorldBankUnavailableError, match="no populated"):
        world_bank_client.fetch_indicator_reading("TUR", "BN.CAB.XOKA.GD.ZS")


def test_fetch_ppp_conversion_factor_delegates_to_the_shared_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(f) The PPP route must go through `_fetch_latest_reading`, not its own copy.

    If this delegation is removed, the two routes can drift — the retry budget,
    the newest-year rule and the empty/failed distinction would then exist twice
    and diverge. Asserted by watching the helper, so a future re-inlining fails
    here.
    """
    calls: list[tuple[str, str]] = []
    original = world_bank_client._fetch_latest_reading

    def _spy(iso3: str, indicator: str, *, timeout: float) -> Any:
        calls.append((iso3, indicator))
        return original(iso3, indicator, timeout=timeout)

    monkeypatch.setattr(world_bank_client, "_fetch_latest_reading", _spy)
    rows = [_indicator_row("2024", 32.5, indicator="PA.NUS.PPP", iso3="DEU")]
    _patch_client(monkeypatch, _payload(rows))
    world_bank_client.fetch_ppp_conversion_factor("DEU")
    assert calls == [("DEU", "PA.NUS.PPP")]


def test_the_coverage_ratio_divides_the_two_legs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(g) The DERIVED ratio performs the division — measured, not assumed.

    Both legs are the same unit, so a mutant that hardcoded 1.0, or returned the
    numerator, or divided the wrong way round, would produce a plausible-looking
    coverage ratio. The expected value is computed from the two inputs here.
    """
    reserves = 155_548_682_878.169
    short_term = 178_133_840_000.0
    rows_a = [_indicator_row("2024", reserves, indicator="FI.RES.TOTL.CD")]
    rows_b = [_indicator_row("2024", short_term, indicator="DT.DOD.DSTC.CD")]

    def _fake(iso3: str, indicator: str, *, timeout: float = 30.0) -> Any:
        rows = rows_a if indicator == "FI.RES.TOTL.CD" else rows_b
        return world_bank_client._parse_rows_to_reading(iso3, indicator, rows, date(2026, 7, 13))

    monkeypatch.setattr(world_bank_client, "fetch_indicator_reading", _fake)
    ratio, disclosure = world_bank_client.reserves_to_short_term_debt("TUR")

    assert ratio == pytest.approx(reserves / short_term, rel=1e-12)
    assert ratio < 1.0
    assert "FI.RES.TOTL.CD" in disclosure and "DT.DOD.DSTC.CD" in disclosure


def test_a_zero_short_term_debt_raises_rather_than_returning_infinity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(h) An infinite ratio reads as 'perfectly covered' — refuse it instead."""
    rows_a = [_indicator_row("2024", 1.0e11, indicator="FI.RES.TOTL.CD")]
    rows_b = [_indicator_row("2024", 0.0, indicator="DT.DOD.DSTC.CD")]

    def _fake(iso3: str, indicator: str, *, timeout: float = 30.0) -> Any:
        rows = rows_a if indicator == "FI.RES.TOTL.CD" else rows_b
        return world_bank_client._parse_rows_to_reading(iso3, indicator, rows, date(2026, 7, 13))

    monkeypatch.setattr(world_bank_client, "fetch_indicator_reading", _fake)
    with pytest.raises(WorldBankUnavailableError, match="undefined"):
        world_bank_client.reserves_to_short_term_debt("TUR")


def test_the_coverage_disclosure_names_both_legs_and_their_years(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ratio is a statement about two series; one date cannot describe it."""
    rows_a = [_indicator_row("2024", 2.0e11, indicator="FI.RES.TOTL.CD")]
    rows_b = [_indicator_row("2023", 1.0e11, indicator="DT.DOD.DSTC.CD")]

    def _fake(iso3: str, indicator: str, *, timeout: float = 30.0) -> Any:
        rows = rows_a if indicator == "FI.RES.TOTL.CD" else rows_b
        return world_bank_client._parse_rows_to_reading(iso3, indicator, rows, date(2026, 7, 13))

    monkeypatch.setattr(world_bank_client, "fetch_indicator_reading", _fake)
    _, disclosure = world_bank_client.reserves_to_short_term_debt("TUR")
    assert "2024" in disclosure and "2023" in disclosure
    assert "no unit conversion" in disclosure


# ===========================================================================
# R-3 — the registry `symbol` and the client constant are ONE fact, twice
# ===========================================================================
# The defect these tests close is a **duplicated fact with one copy dead**.
#
# A `world_bank` registry entry declares its indicator code in TWO places:
#
#   1. `config/series_registry.yaml`, as the entry's `symbol`; and
#   2. `data_layer/world_bank_client.py`, as a module constant.
#
# For a SNAPSHOT field that duplication is harmless, because
# `snapshot_builder` reads `entry.symbol` and would fetch whatever the registry
# says. But ALL FIVE World Bank entries are `not_a_snapshot_field: true` — the
# builder SKIPS them (`validation.py:547`) and the only thing that ever fetches
# these series is this client, which uses its OWN constant and never read the
# registry at all. So the registry `symbol` was **dead at runtime**: the code
# path that fetches and the declaration that is supposed to name the source
# could disagree and nothing would notice until a wrong-series number appeared
# in a verdict.
#
# MEASURED (2026-09-29): all five pairs happened to MATCH — but only because
# they were transcribed carefully when written, not because anything ENFORCED
# it. `grep` over `tests/` found no test loading the registry for these
# entries, and the seven client tests that do assert the codes
# (`test_the_indicator_codes_are_the_ones_the_authority_names`) compare them
# against HARDCODED literals, which pins the client to a value without pinning
# it to the registry. Two independently-editable copies of one fact, with no
# link, is the exact "two copies of a fact drift" class this repository names —
# the same shape as O-141's undeclared key and R-1's dead `event_map` join.
#
# The fix is a binding: the registry `symbol` is the DECLARED source of a
# series (Section 21.1's whole purpose is that the source is auditable), so the
# two copies must be provably the same value. `test_registry_symbols_match_...`
# is the KILLER — it fails the moment either copy is edited alone.

#: `registry series name -> the client constant that fetches it`. Written
#: explicitly rather than derived, because the MAPPING is itself the fact under
#: test: a rename on either side must fail here rather than fall through a
#: comprehension. The five entries are the complete set of `provider: world_bank`
#: series; `test_every_world_bank_registry_entry_is_bound_here` proves that below.
_REGISTRY_TO_CLIENT_INDICATOR = {
    "current_account_pct_gdp_world_bank": world_bank_client.CURRENT_ACCOUNT_PCT_GDP_INDICATOR,
    "reserves_total_usd_world_bank": world_bank_client.RESERVES_TOTAL_USD_INDICATOR,
    "short_term_external_debt_usd": world_bank_client.SHORT_TERM_EXTERNAL_DEBT_USD_INDICATOR,
    "ppp_conversion_factor_eur": world_bank_client.PPP_CONVERSION_FACTOR_INDICATOR,
    "ppp_conversion_factor_usd": world_bank_client.PPP_CONVERSION_FACTOR_INDICATOR,
}


def test_registry_symbols_match_the_client_indicator_constants() -> None:
    """R-3 KILLER: the registry `symbol` and the client constant must agree.

    This is the test that would have caught a drift. Both a registry edit that
    left the client alone and a client edit that left the registry alone fail
    here — which is the point, because either one silently changes WHICH series
    the engine fetches while the other keeps claiming the old source.
    """
    from macro_engine.config import get_registry

    registry = get_registry()
    mismatches: list[str] = []
    for name, constant in _REGISTRY_TO_CLIENT_INDICATOR.items():
        entry = registry.series.get(name)
        assert entry is not None, (
            f"registry series '{name}' is gone, but the client ({constant}) still fetches it. "
            f"The registry is the auditable declaration of this source (Section 21.1) — a "
            f"deletion here must be deliberate, not a side effect."
        )
        if entry.symbol != constant:
            mismatches.append(
                f"  {name}: registry symbol={entry.symbol!r}, client constant={constant!r}"
            )
    assert not mismatches, (
        "The World Bank registry `symbol` and the client's indicator constant disagree "
        "(R-3 — a duplicated fact with one copy dead):\n"
        + "\n".join(mismatches)
        + "\nThese entries are not_a_snapshot_field, so the snapshot builder never reads "
        "`symbol`; the client is the only fetcher and it uses its own constant. Fix BOTH "
        "to the same code — the registry records the source, the constant performs the fetch."
    )


def test_every_world_bank_registry_entry_is_bound_here() -> None:
    """The binding table above must cover EVERY `provider: world_bank` entry.

    Without this, a sixth World Bank entry could be added to the registry and
    slip past the killer above simply by not being listed — the coverage gap
    that turns an enforcement into a coincidence. Derived from the registry, so
    a new entry with no client constant FAILS here.
    """
    from macro_engine.config import get_registry

    registry = get_registry()
    world_bank_entries = {
        name for name, entry in registry.series.items() if entry.provider == "world_bank"
    }
    unbound = sorted(world_bank_entries - set(_REGISTRY_TO_CLIENT_INDICATOR))
    assert not unbound, (
        f"registry series {unbound} declare `provider: world_bank` but are not bound to a "
        f"client indicator constant in _REGISTRY_TO_CLIENT_INDICATOR. Add each to the table "
        f"so its `symbol` is provably the code the client fetches (R-3); an unbound entry "
        f"can drift from the client with nothing to detect it."
    )
    assert world_bank_entries, (
        "no registry series declares `provider: world_bank` — the binding table is now "
        "vacuous, which means the killer above tests nothing."
    )


# ===========================================================================
# The 2026-10-05 review — measured claims, and one wrong series label
# ===========================================================================
# Four defects, each a claim that had been RECORDED and never re-measured
# against the live API (the D-043 "FALSE BLOCK" discipline, applied to prose and
# to a series label rather than to a route):
#
# (F-WBC-001) `_parse_iso3`'s docstring asserted "a lowercase or padded code
#     returns an empty payload" — while ALSO asserting the API is
#     "case-insensitive". MEASURED: `usa` returns the full 66-row USA series, so
#     the premise was false and self-contradictory.
# (F-WBC-002) `_parse_payload` did not recognise the API's own error shape
#     (`[{"message": [...]}]`, returned for an unknown indicator OR country), so
#     it failed on the missing `lastupdated` and reported THAT — naming the wrong
#     defect.
# (F-WBC-004) `DT.DOD.DSTC.CD` was labelled a residual-maturity series. The World
#     Bank's own `sourceNote` defines it as ORIGINAL maturity, and no
#     residual-maturity series exists. The mislabel hid a real over-optimism in
#     the coverage ratio.
# (F-WBC-006) `PPP_CONVERSION_FACTOR_INDICATOR` was absent from `__all__` while
#     its three D-119 siblings were present.


def test_the_iso3_docstring_does_not_claim_lowercase_returns_empty() -> None:
    """(F-WBC-001) The false premise must not come back.

    The docstring asserted that a lowercase code *"returns an empty payload
    rather than an error"* — MEASURED false (`usa` returns the full 66-row USA
    series) and contradicted by its own "case-insensitive" clause. This guard
    fails if the claim is re-introduced, the same shape
    ``test_the_module_never_references_the_local_openbb_host`` uses for the OpenBB
    route.
    """
    source = Path(inspect.getfile(world_bank_client)).read_text(encoding="utf-8")
    assert "empty payload rather than an error" not in source, (
        "world_bank_client again claims a lowercase/unresolvable code returns an "
        "empty payload; MEASURED, the API is case-insensitive and returns the "
        "full series (F-WBC-001)."
    )


def test_a_lowercase_code_is_normalised_not_refused() -> None:
    """(F-WBC-001) The API is case-INSENSITIVE — a lowercase code is normalised.

    MEASURED 2026-10-05: `usa` returns the full 66-row USA series. The docstring
    this replaces claimed the opposite ("a lowercase code returns an empty
    payload"), which would have justified a check for a behaviour the API does
    not have. The contract here is still ISO3, so the code is upper-cased rather
    than passed through.
    """
    assert world_bank_client._parse_iso3("deu") == "DEU"
    assert world_bank_client._parse_iso3("  jpn ") == "JPN"
    assert world_bank_client._parse_iso3("uSa") == "USA"


def test_the_api_error_shape_is_named_not_misreported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(F-WBC-002) The API's own refusal must be surfaced, not a missing date.

    MEASURED 2026-10-05: an unknown indicator (`FOO.BAR.BAZ`) and an unresolvable
    country (`ZZZ`) BOTH return
    `[{"message": [{"id": "120", "key": "Invalid value", "value": "..."}]}]` — a
    one-element list carrying no `lastupdated`. Before the fix the read failed on
    that missing date and reported *it* as the reason, sending a reader to look
    for a metadata problem that does not exist. The API's reason must be the one
    the caller sees.
    """
    error_payload = [
        {
            "message": [
                {
                    "id": "120",
                    "key": "Invalid value",
                    "value": "The provided parameter value is not valid",
                }
            ]
        }
    ]
    _patch_client(monkeypatch, error_payload)
    with pytest.raises(WorldBankUnavailableError) as excinfo:
        fetch_ppp_conversion_factor("USA")
    message = str(excinfo.value)
    assert "The provided parameter value is not valid" in message, (
        f"the World Bank's own error reason must reach the caller, got: {message!r}"
    )
    assert "lastupdated" not in message, (
        f"the failure must not be blamed on a missing 'lastupdated' — the API "
        f"refused the request and said why: {message!r}"
    )


def test_the_st_debt_series_is_not_mislabelled_residual_maturity() -> None:
    """(F-WBC-004) `DT.DOD.DSTC.CD` is ORIGINAL-maturity, not residual.

    The World Bank's own `sourceNote` for `DT.DOD.DSTC.CD` reads *"debt that has
    an original maturity of one year or less"* (measured 2026-10-05), and the
    full ~20 000-entry indicator catalogue contains NO residual-maturity series.
    The module must therefore state the measured basis and must not describe this
    leg as a residual-maturity measure — the conventional Guidotti-Greenspan
    denominator is the residual stock, which is LARGER, so the mislabel
    understated a real over-optimism in the coverage check.
    """
    source = Path(inspect.getfile(world_bank_client)).read_text(encoding="utf-8")
    assert "residual maturity basis" not in source, (
        "world_bank_client describes DT.DOD.DSTC.CD as a residual-maturity "
        "series; the World Bank defines it as ORIGINAL maturity and publishes no "
        "residual-maturity series (F-WBC-004)."
    )
    assert "original maturity" in source, (
        "the module must state the measured basis (original maturity) so the next "
        "reader cannot re-introduce the residual-maturity claim (F-WBC-004)."
    )


def test_the_coverage_disclosure_names_the_maturity_basis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(F-WBC-004) The ratio says which maturity basis it divides by.

    A caller comparing the ratio against the conventional 1.0 threshold is
    comparing a more forgiving number than the Guidotti-Greenspan check produces.
    Naming the basis on the disclosure is what keeps that visible on the VALUE
    rather than only in a source comment.
    """
    rows_a = [_indicator_row("2024", 2.0e11, indicator="FI.RES.TOTL.CD")]
    rows_b = [_indicator_row("2024", 1.0e11, indicator="DT.DOD.DSTC.CD")]

    def _fake(iso3: str, indicator: str, *, timeout: float = 30.0) -> Any:
        rows = rows_a if indicator == "FI.RES.TOTL.CD" else rows_b
        return world_bank_client._parse_rows_to_reading(iso3, indicator, rows, date(2026, 7, 13))

    monkeypatch.setattr(world_bank_client, "fetch_indicator_reading", _fake)
    _, disclosure = world_bank_client.reserves_to_short_term_debt("TUR")
    lowered = disclosure.lower()
    assert "original-maturity" in lowered, (
        f"the disclosure must name the ORIGINAL-maturity basis it uses, got: {disclosure!r}"
    )
    assert "residual-maturity" in lowered, (
        f"the disclosure must say the residual-maturity convention is NOT what it "
        f"divides by, got: {disclosure!r}"
    )
    assert "guidotti" in lowered, (
        f"the disclosure should name the convention it departs from, got: {disclosure!r}"
    )


def test_every_public_indicator_constant_is_exported() -> None:
    """(F-WBC-006) `__all__` must not omit the PPP constant its siblings include.

    The three D-119 indicator constants were exported while the original D-117
    `PPP_CONVERSION_FACTOR_INDICATOR` — the default of
    `fetch_ppp_conversion_factor` — was not, so `from ... import *` silently
    dropped it. The asymmetry had no rationale.
    """
    for name in (
        "PPP_CONVERSION_FACTOR_INDICATOR",
        "CURRENT_ACCOUNT_PCT_GDP_INDICATOR",
        "RESERVES_TOTAL_USD_INDICATOR",
        "SHORT_TERM_EXTERNAL_DEBT_USD_INDICATOR",
    ):
        assert name in world_bank_client.__all__, (
            f"{name} is a public indicator constant but is missing from __all__ "
            f"(F-WBC-006); its siblings are exported."
        )
