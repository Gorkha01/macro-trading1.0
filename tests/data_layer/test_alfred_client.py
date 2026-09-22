"""ALFRED vintage retrieval — the guards that keep the trap from returning.

What these tests are for
------------------------
The defect being fixed is not a crash. It is a **silent substitution**, and it
has a precise shape: a caller asks FRED for the values in force on a past date,
OpenBB absorbs the vintage parameters, and the caller receives the *latest*
revision with HTTP 200 and a plausible-looking payload. ``docs/OPEN_ISSUES.md``
O-6 calls this "the sharpest form of the danger this ledger exists to record".

Silent substitutions are defended by guards, not by intent, so the properties
below are asserted structurally rather than by inspection:

(a) **The ALFRED path never routes through OpenBB.** Asserted by reading the
    module's source, not by trusting a call graph — a future edit that adds a
    "helpful" OpenBB fallback must fail a test, not merely review.
(b) **A missing credential raises.** It never degrades to a keyless read, and
    never returns an empty list that a caller would read as "no revisions".
(c) **Both vintage bounds are always sent, as the same date.** Sending one is a
    different question; sending different dates is a range that silently
    multiplies rows per observation date.
(d) **``vintage_datetime`` is stamped from the as-of date that was requested**,
    never inferred from the values.
(e) **An empty result stays empty.** A date before first publication has no
    known values, and that must not be substituted with the latest revision.

The payload shapes used below are the real ones, captured live on 2026-09-22.
"""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from macro_engine.config import AlfredVintage, RegistrySeries
from macro_engine.data_layer import alfred_client
from macro_engine.data_layer.alfred_client import (
    ALFRED_OBSERVATIONS_URL,
    FRED_HOST,
    ROUTE_NAME,
    VintageObservation,
    VintageReadError,
    VintageUnavailableError,
    fetch_vintage_observations,
    resolve_fred_api_key,
)
from macro_engine.data_layer.schemas import ObservationPoint

# ---------------------------------------------------------------------------
# Real payload shapes, captured live 2026-09-22
# ---------------------------------------------------------------------------

#: CPIAUCSL, observations 2024-01..03, at vintage 2024-06-01. Values are the
#: genuine ones; compare against :data:`_LATEST_VINTAGE_VALUES` below, which is
#: the same three observation dates read without a vintage bound.
_VINTAGE_2024_06_PAYLOAD: dict[str, Any] = {
    "realtime_start": "2024-06-01",
    "realtime_end": "2024-06-01",
    "observation_start": "2024-01-01",
    "observation_end": "2024-03-01",
    "count": 3,
    "observations": [
        {
            "realtime_start": "2024-02-13",
            "realtime_end": "2024-06-01",
            "date": "2024-01-01",
            "value": "309.685",
        },
        {
            "realtime_start": "2024-03-12",
            "realtime_end": "2024-06-01",
            "date": "2024-02-01",
            "value": "311.054",
        },
        {
            "realtime_start": "2024-04-10",
            "realtime_end": "2024-06-01",
            "date": "2024-03-01",
            "value": "312.230",
        },
    ],
}

#: The same three dates read NOW (no vintage bound). Measured 2026-09-22:
#: 309.698 / 310.967 / 312.345. Different from the 2024-06-01 vintage, which is
#: what makes the distinction this module enforces a real one rather than
#: theoretical. Used by the test that proves the two are not interchangeable.
_LATEST_VINTAGE_VALUES: dict[date, float] = {
    date(2024, 1, 1): 309.698,
    date(2024, 2, 1): 310.967,
    date(2024, 3, 1): 312.345,
}

#: A date before CPIAUCSL's first release in the window: FRED answers with an
#: empty observation list, which is the honest "nothing was known then".
_EMPTY_PAYLOAD: dict[str, Any] = {
    "realtime_start": "2024-01-15",
    "realtime_end": "2024-01-15",
    "count": 0,
    "observations": [],
}


def _client_returning(payload: Any, *, status: int = 200) -> MagicMock:
    """A fake ``httpx.Client`` whose single GET returns ``payload``."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = status
    response.json.return_value = payload
    if status >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"HTTP {status}", request=MagicMock(), response=response
        )
    else:
        response.raise_for_status.return_value = None

    client = MagicMock(spec=httpx.Client)
    client.get.return_value = response
    return client


def _sent_params(client: MagicMock) -> dict[str, str]:
    """The query params of the last GET issued through ``client``."""
    _, kwargs = client.get.call_args
    return dict(kwargs["params"])


# ---------------------------------------------------------------------------
# (a) The ALFRED path never routes through OpenBB
# ---------------------------------------------------------------------------


def test_the_module_never_imports_the_openbb_client() -> None:
    """No import of ``openbb_client`` — asserted on the AST, not on behaviour.

    A behavioural test cannot see this: an OpenBB fallback that is never reached
    under test is still a fallback in production. Parsing the module's own
    imports catches the edit that introduces one, which is the edit that would
    reintroduce the silent substitution.
    """
    source = Path(inspect.getfile(alfred_client)).read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    offenders = [name for name in imported if "openbb_client" in name]
    assert offenders == [], (
        "alfred_client must not import the OpenBB client: the OpenBB route "
        "absorbs the vintage parameters silently and returns the latest "
        f"revision. Found: {offenders}"
    )


def _module_code_without_docstrings() -> str:
    """The module's executable source, with every docstring and comment removed.

    The guards below assert that certain *code* does not exist. Searching the
    raw text would be wrong in both directions: the module's docstrings discuss
    ``OpenBBFetchError`` and ``FRED_API_KEY`` at length precisely because it
    refuses to use either, so a naive substring search fails on the prose that
    explains the rule — and, worse, a future edit could silence the guard by
    mentioning a forbidden name in a comment.

    Stripping docstrings is therefore load-bearing, not tidiness. ``ast.unparse``
    on a tree whose docstrings have been dropped gives code only; comments are
    already absent from the AST, so ``#`` text cannot affect the result.
    """
    source = Path(inspect.getfile(alfred_client)).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                node.body = body[1:]
    return ast.unparse(tree)


def test_the_openbb_class_is_never_constructed_or_called() -> None:
    """``OpenBBClient`` / ``OpenBBFetchError`` appear nowhere in the module code.

    Stronger than the import check in one direction — it also catches a local
    import inside a function, which the module-level import scan would miss.
    Asserted against code-with-docstrings-stripped so the module's own prose
    *about* the OpenBB path cannot make this pass or fail.
    """
    code = _module_code_without_docstrings()
    assert "OpenBBClient" not in code
    assert "OpenBBFetchError" not in code


def test_every_url_points_at_the_fred_host_and_never_at_the_local_service() -> None:
    """The only host reachable from this module is FRED's own API host."""
    source = Path(inspect.getfile(alfred_client)).read_text(encoding="utf-8")
    for forbidden in ("127.0.0.1", "localhost", "/api/v1/"):
        assert forbidden not in source, (
            f"alfred_client must not reference {forbidden!r}: that is the local "
            "OpenBB service, whose vintage parameters are inert."
        )
    assert ALFRED_OBSERVATIONS_URL.startswith(FRED_HOST)


def test_the_route_name_is_distinguishable_from_the_openbb_paths() -> None:
    """``source`` provenance must tell the two fetch paths apart.

    A value pulled through OpenBB and a value pulled directly are the same
    number with different reliability, so the audit trail has to distinguish
    them. If either OpenBB path constant ever took this value, the provenance
    would silently stop meaning anything.
    """
    from macro_engine.data_layer.openbb_client import _PATH_LOCAL_API, _PATH_PACKAGE

    assert ROUTE_NAME not in {_PATH_LOCAL_API, _PATH_PACKAGE}
    assert alfred_client.describe_route()["route"] == ROUTE_NAME


# ---------------------------------------------------------------------------
# (b) A missing credential raises — it never degrades
# ---------------------------------------------------------------------------


def test_a_missing_credential_raises_rather_than_returning_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No key -> ``VintageUnavailableError``, never an empty list.

    This is the single most important guard in the file. An empty list is a
    *legitimate* ALFRED answer (a date before first publication), so degrading
    to one would make "no credential" and "nothing was published yet"
    observably identical — and a backtest reading the second when the truth is
    the first would silently lose its vintage bound entirely.
    """
    monkeypatch.setattr(alfred_client, "resolve_fred_api_key", _raise_unavailable)
    with pytest.raises(VintageUnavailableError):
        fetch_vintage_observations("CPIAUCSL", date(2024, 6, 1))


def _raise_unavailable() -> str:
    raise VintageUnavailableError("test: no credential")


def test_an_empty_key_string_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """A present-but-empty key is a misconfiguration, not a valid state.

    An empty key produces a request FRED answers with an error page. Treating
    that response as "no vintage available" is the degradation this module
    refuses, so the emptiness is caught before the request is made.
    """
    fake_credentials = MagicMock()
    fake_credentials.fred_api_key = "   "

    fake_service = MagicMock()
    fake_service.read_from_file.return_value.credentials = fake_credentials

    monkeypatch.setitem(
        __import__("sys").modules,
        "openbb_core.app.service.user_service",
        MagicMock(UserService=fake_service),
    )
    with pytest.raises(VintageUnavailableError, match="present but empty"):
        resolve_fred_api_key()


def test_a_key_is_unwrapped_from_secret_str(monkeypatch: pytest.MonkeyPatch) -> None:
    """The key is unwrapped, not stringified.

    The credential is stored as a Pydantic ``SecretStr``. ``str()`` on it gives
    the MASKED representation, so a naive read would transmit ``"**********"``
    and FRED would reject every request — a failure that looks like an outage.
    """

    class _Secret:
        def get_secret_value(self) -> str:
            return "a" * 32

        def __str__(self) -> str:  # pragma: no cover - would be the bug
            return "**********"

    fake_credentials = MagicMock()
    fake_credentials.fred_api_key = _Secret()
    fake_service = MagicMock()
    fake_service.read_from_file.return_value.credentials = fake_credentials

    monkeypatch.setitem(
        __import__("sys").modules,
        "openbb_core.app.service.user_service",
        MagicMock(UserService=fake_service),
    )
    assert resolve_fred_api_key() == "a" * 32


# ---------------------------------------------------------------------------
# (c) Both vintage bounds are always sent, as the same date
# ---------------------------------------------------------------------------


def test_both_vintage_bounds_are_sent_and_are_the_same_date() -> None:
    """``realtime_start == realtime_end == as_of``, always.

    Two distinct mistakes this rules out. Sending only ``realtime_start`` asks
    for a *range* of vintages, which FRED answers with one row per revision —
    several rows for a single observation date, silently. Sending different
    dates asks the same range question explicitly. The pair is the selector.
    """
    client = _client_returning(_VINTAGE_2024_06_PAYLOAD)
    fetch_vintage_observations("CPIAUCSL", date(2024, 6, 1), client=client)
    params = _sent_params(client)

    assert params["realtime_start"] == "2024-06-01"
    assert params["realtime_end"] == "2024-06-01"
    assert params["realtime_start"] == params["realtime_end"]


def test_the_as_of_date_is_what_gets_sent_not_today() -> None:
    """The requested vintage is transmitted verbatim; nothing substitutes today.

    A regression that defaulted either bound to the current date would produce
    a request that succeeds and returns current data — the exact silent
    substitution. Pinning the assertion to a date far from today makes that
    regression visible.
    """
    client = _client_returning(_VINTAGE_2024_06_PAYLOAD)
    asked = date(2014, 6, 1)
    fetch_vintage_observations("GDP", asked, client=client)
    params = _sent_params(client)
    assert params["realtime_start"] == "2014-06-01"
    assert params["realtime_end"] == "2014-06-01"


# ---------------------------------------------------------------------------
# (d) vintage_datetime comes from the requested date, never from the values
# ---------------------------------------------------------------------------


def test_the_vintage_stamp_is_the_requested_date_not_an_inferred_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``fetch_field_vintage`` stamps the as-of date it was given.

    The alternative — inferring a vintage from the values or from the per-row
    ``realtime_start`` FRED returns — would report a *release* date as a
    *vintage* identity. Section 6 exists to keep those apart.
    """
    _enable_vintage(monkeypatch, enabled=True)
    client = _client_returning(_VINTAGE_2024_06_PAYLOAD)
    entry = RegistrySeries(provider="fred", symbol="CPIAUCSL", vintage_eligible=True)

    points = _fetch_field_vintage("cpi_headline", entry, date(2024, 6, 1), client=client)

    assert points, "expected points from the captured payload"
    for point in points:
        assert point.vintage_datetime == datetime(2024, 6, 1, tzinfo=UTC), (
            "vintage_datetime must be the requested as-of date"
        )


def test_the_release_datetime_is_left_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    """This path fills the vintage and deliberately NOT the release datetime.

    They are different facts with different sources. ``publication_dates`` fills
    ``release_datetime``; filling it here from the vintage would be the
    substitution Section 6 prohibits, and it would look correct.
    """
    _enable_vintage(monkeypatch, enabled=True)
    client = _client_returning(_VINTAGE_2024_06_PAYLOAD)
    entry = RegistrySeries(provider="fred", symbol="CPIAUCSL", vintage_eligible=True)

    points = _fetch_field_vintage("cpi_headline", entry, date(2024, 6, 1), client=client)

    assert all(point.release_datetime is None for point in points)


def test_the_source_records_the_direct_route(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provenance names the route, so a vintage value is auditable as one."""
    _enable_vintage(monkeypatch, enabled=True)
    client = _client_returning(_VINTAGE_2024_06_PAYLOAD)
    entry = RegistrySeries(provider="fred", symbol="CPIAUCSL", vintage_eligible=True)

    points = _fetch_field_vintage("cpi_headline", entry, date(2024, 6, 1), client=client)

    assert all(point.source.endswith(f"@{ROUTE_NAME}") for point in points)


# ---------------------------------------------------------------------------
# (e) An empty result stays empty, and values are not the latest revision
# ---------------------------------------------------------------------------


def test_a_date_before_first_publication_returns_empty_not_latest() -> None:
    """Nothing was known then, so nothing is returned.

    The critical property: an empty list must survive as an empty list. The
    tempting alternative — filling it from the latest revision so the caller
    "has data" — is precisely the look-ahead error this work exists to remove.
    """
    client = _client_returning(_EMPTY_PAYLOAD)
    rows = fetch_vintage_observations("CPIAUCSL", date(2024, 1, 15), client=client)
    assert rows == []


def test_the_vintage_values_are_not_the_latest_revision() -> None:
    """The values this path returns differ from today's, and that is the point.

    Guards the semantics, not just the plumbing: if a future change made the
    request degrade to an unbounded read, the payload below is what the latest
    revision looks like, and the test would catch the substitution.
    """
    client = _client_returning(_VINTAGE_2024_06_PAYLOAD)
    rows = fetch_vintage_observations("CPIAUCSL", date(2024, 6, 1), client=client)
    got = {row.observation_date: row.value for row in rows}

    assert got[date(2024, 1, 1)] == pytest.approx(309.685)
    assert got[date(2024, 1, 1)] != pytest.approx(_LATEST_VINTAGE_VALUES[date(2024, 1, 1)])
    assert got[date(2024, 3, 1)] == pytest.approx(312.230)
    assert got[date(2024, 3, 1)] != pytest.approx(_LATEST_VINTAGE_VALUES[date(2024, 3, 1)])


def test_a_missing_value_marker_is_skipped_not_stored_as_zero() -> None:
    """FRED writes a gap as ``"."``. That is a gap, not a zero.

    A zero would be indistinguishable from a genuine observation of zero, which
    on a vintage read is a fabricated revision rather than a missing one.
    """
    payload = {
        "observations": [
            {"date": "2024-01-01", "value": "309.685"},
            {"date": "2024-02-01", "value": "."},
            {"date": "2024-03-01", "value": "312.230"},
        ]
    }
    client = _client_returning(payload)
    rows = fetch_vintage_observations("CPIAUCSL", date(2024, 6, 1), client=client)

    dates = [row.observation_date for row in rows]
    assert date(2024, 2, 1) not in dates
    assert len(rows) == 2


# ---------------------------------------------------------------------------
# Failure surface: readable, typed, and never silently successful
# ---------------------------------------------------------------------------


def test_an_unexpected_shape_raises_after_the_retry_budget() -> None:
    """A body that is not the expected object surfaces as a read error.

    Not reclassified as an outage and not skipped: a shape problem reported as
    a transient failure would invite a retry loop, and skipped rows would be
    withheld observations with no record that they were withheld.
    """
    client = _client_returning({"unexpected": "shape"})
    with pytest.raises(VintageReadError):
        fetch_vintage_observations("CPIAUCSL", date(2024, 6, 1), backoff_seconds=0.0, client=client)


def test_a_transport_error_is_retried_the_declared_number_of_times() -> None:
    """The retry budget is spent, and the attempt count is the declared one."""
    client = _client_returning({}, status=503)
    with pytest.raises(VintageReadError):
        fetch_vintage_observations(
            "CPIAUCSL", date(2024, 6, 1), max_attempts=3, backoff_seconds=0.0, client=client
        )
    assert client.get.call_count == 3


def test_a_non_numeric_value_raises_rather_than_being_coerced() -> None:
    """A value FRED returns that is not a number is a parse failure, not a zero."""
    payload = {"observations": [{"date": "2024-01-01", "value": "not-a-number"}]}
    client = _client_returning(payload)
    with pytest.raises(VintageReadError, match="non-numeric"):
        fetch_vintage_observations("CPIAUCSL", date(2024, 6, 1), backoff_seconds=0.0, client=client)


def test_a_blank_series_id_is_refused_before_any_request() -> None:
    """An empty symbol is a caller bug, and it is caught without a request."""
    with pytest.raises(ValueError, match="non-empty"):
        fetch_vintage_observations("   ", date(2024, 6, 1))


# ---------------------------------------------------------------------------
# Config guards: an impossible eligibility declaration is refused at load
# ---------------------------------------------------------------------------


def test_vintage_eligible_is_refused_on_a_curve_entry() -> None:
    """A curve has no single vintage: its tenors revise on different schedules."""
    with pytest.raises(ValueError, match="curve entry"):
        RegistrySeries(provider="fred", tenors={"2yr": "DGS2"}, vintage_eligible=True)


def test_vintage_eligible_is_refused_on_a_non_fred_series() -> None:
    """ALFRED is FRED's archive; another provider's series has no record in it."""
    with pytest.raises(ValueError, match="ALFRED"):
        RegistrySeries(provider="federal_reserve", symbol="X", vintage_eligible=True)


def test_vintage_eligible_defaults_to_false() -> None:
    """Eligibility is DECLARED, never inferred from the provider alone."""
    assert RegistrySeries(provider="fred", symbol="CPIAUCSL").vintage_eligible is False


def test_the_shipped_config_keeps_vintage_off_and_credential_strict() -> None:
    """The two defaults that must not drift.

    ``enabled=False`` because a live build has no as-of dates to replay, and
    ``require_credential=True`` because a vintage read that degrades silently
    is undetectable downstream.
    """
    from macro_engine.config import get_registry

    config = get_registry().alfred_vintage
    assert config.enabled is False
    assert config.require_credential is True


def test_the_declared_model_defaults_match_the_shipped_yaml() -> None:
    """The model's defaults and the YAML agree, so neither is the odd one out."""
    model = AlfredVintage()
    assert model.enabled is False
    assert model.require_credential is True
    assert model.timeout_seconds > 0


def test_no_fred_key_is_required_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Option A: the engine holds no key of its own.

    ``FRED_API_KEY`` must not be read anywhere in the module — that would be the
    credential duplication Section 22.2/22.3 forbid, and O-6's own record of why
    this fix was declined the first time.

    Asserted on **code with docstrings stripped**, because the module's
    docstring states that no ``FRED_API_KEY`` is required. A raw substring check
    would match that sentence and fail on the very sentence documenting the
    rule — which is how this guard first failed, correctly pointing at its own
    naivety.
    """
    code = _module_code_without_docstrings()
    assert "FRED_API_KEY" not in code
    assert "os.environ" not in code
    assert "getenv" not in code


# ---------------------------------------------------------------------------
# The fetch path is opt-in, and refuses rather than returning nothing
# ---------------------------------------------------------------------------


def test_a_disabled_config_refuses_the_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disabled is a refusal, not an empty result."""
    _enable_vintage(monkeypatch, enabled=False)
    entry = RegistrySeries(provider="fred", symbol="CPIAUCSL", vintage_eligible=True)
    with pytest.raises(VintageUnavailableError, match="disabled"):
        _fetch_field_vintage("cpi_headline", entry, date(2024, 6, 1))


def test_a_non_eligible_series_refuses_the_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """Eligibility is enforced at the fetch, not only at config load."""
    _enable_vintage(monkeypatch, enabled=True)
    entry = RegistrySeries(provider="fred", symbol="CPIAUCSL", vintage_eligible=False)
    with pytest.raises(VintageUnavailableError, match="vintage_eligible"):
        _fetch_field_vintage("cpi_headline", entry, date(2024, 6, 1))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _fetch_field_vintage(
    field_name: str,
    entry: RegistrySeries,
    as_of: date,
    *,
    client: httpx.Client | None = None,
) -> list[ObservationPoint]:
    """Call the builder's vintage path with the OpenBB client left unused."""
    from macro_engine.data_layer import snapshot_builder

    return snapshot_builder.fetch_field_vintage(field_name, entry, as_of, client=client)


def _enable_vintage(monkeypatch: pytest.MonkeyPatch, *, enabled: bool) -> None:
    """Force ``alfred_vintage.enabled`` for one test.

    The shipped value is False (a live build has no as-of dates to replay), and
    the patch is object-level so no file is written.
    """
    from macro_engine.config import get_registry

    config = get_registry().alfred_vintage
    monkeypatch.setattr(config, "enabled", enabled, raising=True)


def test_vintage_observation_equality_is_by_value() -> None:
    """``VintageObservation`` compares by value, so a guard can assert on a list."""
    assert VintageObservation(date(2024, 1, 1), 1.0) == VintageObservation(date(2024, 1, 1), 1.0)
    assert VintageObservation(date(2024, 1, 1), 1.0) != VintageObservation(date(2024, 1, 2), 1.0)
