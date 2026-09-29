"""ALFRED vintage retrieval — the only reachable route to a real revision identity.

Why this module exists, and what it replaces
--------------------------------------------
Section 6 names four timestamps per observation and insists they are not
interchangeable: ``observation_date`` (what period), ``release_datetime`` (when
public), ``vintage_datetime`` (which revision), ``retrieved_at`` (when read).
Three of the four are populated. The fourth — ``vintage_datetime`` — has been
``None`` on every point this system has ever produced, and ``None`` means
UNKNOWN, not "equal to the observation date".

That gap was not an oversight. ``docs/OPEN_ISSUES.md`` O-6 is a three-times
re-probed entry recording that **the OpenBB route this engine is specified to
use cannot deliver a vintage**, in the sharpest available form:

    ``.venv/Lib/site-packages/openbb_fred/models/series.py`` lines 156-157
        for d in observations:
            d.pop("realtime_start")
            d.pop("realtime_end")

FRED's API returns those fields on **every observation row**. The provider
deletes them one line later, and its query model declares no realtime field at
all, so the parameter cannot even be *transmitted* — ``get_querystring(...,
["series_id"])`` is built from a model that has no such key. Passing
``realtime_start`` through OpenBB therefore does not fail: it is silently
absorbed and the latest revision is returned with HTTP 200. O-6 calls that
"the sharpest form of the danger this ledger exists to record" — a silently
absorbed parameter is indistinguishable from a respected one unless payloads
are compared.

**This module is the direct route.** It calls FRED's documented observations
endpoint itself and asks for a specific vintage, so ``vintage_datetime``
becomes a measured fact rather than a documented absence.

The credential question, and why this is reuse rather than duplication
----------------------------------------------------------------------
Section 22.2/22.3 forbid the engine holding **its own** FRED key, and O-6's
final word cites exactly that as the reason the fix was declined:

    "Reaching it would require the engine to hold its own FRED key and call the
     provider directly, which is exactly the architecture and credential-
     duplication Section 22.2/22.3 forbid. Recorded, not implemented."

That objection is respected here rather than waived. **This module holds no key
of its own.** It reads the credential OpenBB already owns, through OpenBB's own
public accessor (``openbb_core.app.service.user_service.UserService``), from
OpenBB's own settings file. There is one FRED key on this machine, it is
OpenBB's, and this module borrows it. No ``FRED_API_KEY`` environment variable
is required, none is read, and none is added to ``.env.example``. A deployment
that reconfigures OpenBB reconfigures this too, because it is the same store.

If the key is absent this raises. It never falls back to a keyless or
latest-revision read — see ``VintageUnavailableError``.

The trap this module must never fall into
-----------------------------------------
There are two ways to obtain FRED data on this machine and **only one of them
can answer a vintage question**:

* via OpenBB — absorbed parameter, latest revision, silent, HTTP 200;
* via this module — direct call, specific vintage, or a raised error.

Those two must never be confused, and the confusion is invisible in the
payload: both return plausible numbers for the same dates. So the direct call
is made with ``httpx`` against the FRED host, and **no import of, call into, or
fallback path to OpenBB exists anywhere in this module.** The guard test
``tests/data_layer/test_alfred_client.py`` asserts that property structurally,
because a future edit that "helpfully" adds an OpenBB fallback would
reintroduce exactly the silent substitution this file was written to remove.

What ``realtime_start == realtime_end == D`` means (measured, not assumed)
-------------------------------------------------------------------------
It returns **the values that were in force on D** — neither the first release
nor the latest one, but the actually-known-on-that-date state. Measured against
the live API 2026-09-22 for CPIAUCSL / 2024-01..03:

    as-of 2024-01-15 (before any release)  -> {}          (honest empty set)
    as-of 2024-02-20 (Jan out, Feb not)    -> {Jan: 309.685}
    as-of 2024-06-01 (all three out)       -> {Jan: 309.685, Feb: 311.054, Mar: 312.230}

The empty set on the first line is load-bearing: a date before publication
returns *nothing* rather than a value, so a caller cannot accidentally treat
"not yet published" as "published as zero". And the per-row ``realtime_start``
FRED returns is that observation's own release date, which is why the results
below are anchored on the **as-of date the caller asked for** and not on
anything inferred from the values.

Transport
---------
``httpx`` with a pinned ``curl/8.0`` User-Agent and ``http2=False``, copied
deliberately from ``thesis_layer/catalysts.py`` (D-065, corrected by D-087.25).
That correction matters: the original note blamed a TLS/HTTP fingerprint, and
re-measurement showed the real variable is a **tool-like** versus a
**browser-like or empty** UA — FRED serves ``curl/8.0`` in ~0.2 s and *hangs*
on the browser strings ``openbb_core``'s ``get_user_agent()`` applies
unconditionally. The pinned UA is the load-bearing part; do not modernise it.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date
from typing import Any

import httpx

logger = logging.getLogger(__name__)

__all__ = [
    "ALFRED_OBSERVATIONS_URL",
    "FRED_HOST",
    "ROUTE_NAME",
    "AlfredVintageError",
    "VintageObservation",
    "VintageReadError",
    "VintageUnavailableError",
    "fetch_vintage_observations",
    "resolve_fred_api_key",
]

#: The provenance string this route stamps onto what it returns. Kept here
#: rather than imported from ``openbb_client``: that module's path constants are
#: private (underscore-prefixed, absent from its ``__all__``) and reaching into
#: them would couple this module to another module's internal naming, so that a
#: rename over there breaks vintage provenance over here — the D-087.21 class of
#: breakage, which only ``mypy --strict`` sees. Two independent literals that the
#: guard test asserts are distinct is the stronger arrangement: the test fails
#: if they ever collide, rather than the import failing if one is renamed.
ROUTE_NAME = "alfred_direct"

#: FRED's host. Recorded as a constant so the *absence* of an OpenBB host in
#: this module is visible at a glance — every URL built here is absolute and
#: points at ``api.stlouisfed.org``, never at the local OpenBB service.
FRED_HOST = "https://api.stlouisfed.org"

#: The vintage-capable observations endpoint. ``realtime_start`` /
#: ``realtime_end`` are the vintage SELECTORS here; every other parameter is an
#: ordinary observation filter and is optional.
ALFRED_OBSERVATIONS_URL = f"{FRED_HOST}/fred/series/observations"

#: Measured-good UA (D-087.25). See the module docstring: the distinction that
#: bites is tool-like versus browser-like, not the client library.
_REQUEST_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "curl/8.0",
}

#: The credential name in OpenBB's store. Spelled once; the whole point of the
#: Option-A ruling is that this is OpenBB's key and not a second one.
_OPENBB_CREDENTIAL_NAME = "fred_api_key"


class AlfredVintageError(Exception):
    """Base for every failure this module raises.

    Exists as a distinct root so a caller can catch vintage trouble without
    catching transport trouble from an unrelated layer — ``OpenBBFetchError``
    is the *other* fetch path's contract and must not be conflated with this
    one, precisely because the two behave differently under a vintage request.
    """


class VintageUnavailableError(AlfredVintageError):
    """The vintage capability is not reachable in this environment.

    Raised for a missing credential, or for a configuration that would make a
    vintage read meaningless. **This is deliberately fatal rather than
    degrading.**

    The alternative — returning an empty result, or quietly serving the latest
    revision — is the single failure mode this whole module exists to prevent.
    A caller that receives no vintage must know it received none, because a
    vintage that silently degrades to "latest" is worse than no vintage at all:
    the values are plausible, the dates match, and nothing downstream can
    detect that a backtest just read the future.
    """


class VintageReadError(AlfredVintageError):
    """A transient failure: transport, status, or an unparseable body.

    Retryable, and retried internally. Raised only after the budget is spent.
    """


class VintageObservation:
    """One ``(date, value)`` pair as it was known at a specific vintage.

    A plain class rather than a Pydantic model because this is an *internal
    transport shape*, not a domain object: it exists only between the HTTP
    boundary and ``ObservationPoint``, and ``vintage_datetime`` is attached
    once, by the caller, from the as-of date it actually requested. Giving it a
    schema of its own would invite it to be persisted, and what gets persisted
    is ``ObservationPoint``.
    """

    __slots__ = ("observation_date", "value")

    def __init__(self, observation_date: date, value: float) -> None:
        self.observation_date = observation_date
        self.value = value

    def __repr__(self) -> str:
        return f"VintageObservation({self.observation_date!r}, {self.value!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, VintageObservation):
            return NotImplemented
        return self.observation_date == other.observation_date and self.value == other.value


def resolve_fred_api_key() -> str:
    """Read FRED's key from OpenBB's own credential store.

    Uses OpenBB's public accessor rather than reading
    ``~/.openbb_platform/user_settings.json`` by hand. Two reasons, and the
    second is the one that matters:

    1. The path is OpenBB's to change. Delegating means a future relocation is
       OpenBB's problem, not a silent ``FileNotFoundError`` here.
    2. Hand-rolling the read means hand-rolling the *format* — the credential is
       stored as a Pydantic ``SecretStr``, so a naive ``json.load(...)
       ["credentials"]["fred_api_key"]`` returns the **masked** representation
       on some serialisations. Unwrapping through the documented attribute is
       the only way to get a value that is definitely the key.

    Raises ``VintageUnavailableError`` when no key is configured. Never returns
    an empty string, and never falls back to a keyless request.
    """
    # Imported here, not at module scope, to keep the failure legible: if
    # openbb_core is absent the message should say so rather than surfacing as
    # an ImportError from an unrelated import block.
    try:
        from openbb_core.app.service.user_service import UserService
    except ImportError as exc:  # pragma: no cover - openbb is a hard dependency
        raise VintageUnavailableError(
            "openbb_core is not importable, so the FRED credential OpenBB owns "
            "cannot be read. Vintage retrieval requires it (Option A: this "
            "engine borrows OpenBB's key and holds none of its own)."
        ) from exc

    try:
        credentials: Any = UserService.read_from_file().credentials
    except Exception as exc:
        raise VintageUnavailableError(
            "OpenBB's user settings could not be read, so no FRED credential is "
            "available for vintage retrieval. Configure FRED once for OpenBB "
            "(~/.openbb_platform/user_settings.json) and this route will use "
            "that same key."
        ) from exc

    raw = getattr(credentials, _OPENBB_CREDENTIAL_NAME, None)
    if raw is None:
        raise VintageUnavailableError(
            f"OpenBB's credential store holds no '{_OPENBB_CREDENTIAL_NAME}'. "
            "Vintage retrieval needs it and will not proceed without it."
        )

    # SecretStr is the documented shape; a plain str is accepted too so this
    # does not break if OpenBB ever loosens the field type.
    key = raw.get_secret_value() if hasattr(raw, "get_secret_value") else raw
    if not isinstance(key, str):
        raise VintageUnavailableError(
            f"OpenBB's '{_OPENBB_CREDENTIAL_NAME}' is a {type(key).__name__}, "
            "not a string; refusing to guess how to transmit it."
        )
    key = key.strip()
    if not key:
        raise VintageUnavailableError(
            f"OpenBB's '{_OPENBB_CREDENTIAL_NAME}' is present but empty. An empty "
            "key would produce a request FRED answers with an error page, and "
            "treating that as 'no vintage available' is the degradation this "
            "module refuses to perform."
        )
    return key


def _parse_observations(
    payload: object, *, series_id: str, as_of: date
) -> list[VintageObservation]:
    """Extract ``(date, value)`` pairs, skipping FRED's missing-value marker.

    FRED writes a missing observation as the string ``"."``. That is *not* a
    value and not a zero — it is a gap. ``openbb_fred`` handles it with
    ``.replace(".", None)`` and then ``dropna()``; the same treatment is applied
    here so the two routes agree on what a row set means.

    The parse is strict about shape: anything that is not the expected
    dictionary raises rather than being skipped. A silently-skipped row is a
    withheld observation with no record that it was withheld, and on a vintage
    read that is indistinguishable from a revision that had not happened yet.
    """
    if not isinstance(payload, dict):
        raise VintageReadError(
            f"FRED returned {type(payload).__name__}, not a JSON object, for "
            f"{series_id} as-of {as_of.isoformat()}"
        )

    rows = payload.get("observations")
    if not isinstance(rows, list):
        raise VintageReadError(
            f"FRED response for {series_id} as-of {as_of.isoformat()} has no "
            "'observations' list; keys present: "
            f"{sorted(payload.keys()) if isinstance(payload, dict) else 'n/a'}"
        )

    parsed: list[VintageObservation] = []
    for row in rows:
        if not isinstance(row, dict):
            raise VintageReadError(
                f"FRED returned a {type(row).__name__} observation row for "
                f"{series_id} as-of {as_of.isoformat()}"
            )
        raw_date = row.get("date")
        raw_value = row.get("value")
        if raw_value == "." or raw_value is None:
            # A documented gap, not a zero. Counted, not stored.
            logger.debug(
                "skipping missing value for %s at %s (vintage %s)",
                series_id,
                raw_date,
                as_of.isoformat(),
            )
            continue
        try:
            observation_date = date.fromisoformat(str(raw_date))
        except ValueError as exc:
            raise VintageReadError(
                f"FRED returned unparseable date {raw_date!r} for {series_id} "
                f"as-of {as_of.isoformat()}"
            ) from exc
        try:
            value = float(str(raw_value))
        except ValueError as exc:
            raise VintageReadError(
                f"FRED returned non-numeric value {raw_value!r} for {series_id} "
                f"on {observation_date.isoformat()}"
            ) from exc
        parsed.append(VintageObservation(observation_date, value))

    return parsed


def fetch_vintage_observations(
    series_id: str,
    as_of: date,
    *,
    observation_start: date | None = None,
    observation_end: date | None = None,
    max_attempts: int = 3,
    backoff_seconds: float = 1.0,
    timeout_seconds: float = 20.0,
    client: httpx.Client | None = None,
) -> list[VintageObservation]:
    """Read ``series_id`` **as it was known on ``as_of``**.

    ``realtime_start`` and ``realtime_end`` are both set to ``as_of``. Setting
    only one produces a *range* of vintages and FRED then returns one row per
    revision within it — a different question, and one that silently
    multiplies rows for a single observation date. The pair is the selector.

    Returns the values in force on that date, which may legitimately be an
    empty list: a date before the series' first publication has no known
    values, and an empty result is the honest answer. It is *not* an error, and
    it is *not* substituted with the latest revision.

    Raises ``VintageUnavailableError`` when no credential is configured and
    ``VintageReadError`` when the read fails after every attempt. Both are
    fatal by design — see the class docstrings.
    """
    if not series_id or not series_id.strip():
        raise ValueError("series_id must be a non-empty string")
    if observation_start and observation_end and observation_start > observation_end:
        raise ValueError(
            f"observation_start {observation_start} is after observation_end {observation_end}"
        )

    key = resolve_fred_api_key()

    params: dict[str, str] = {
        "series_id": series_id,
        "api_key": key,
        "file_type": "json",
        # THE SELECTOR. Both bounds, same date. See the module docstring for the
        # measured three-date table that establishes what this returns.
        "realtime_start": as_of.isoformat(),
        "realtime_end": as_of.isoformat(),
    }
    if observation_start is not None:
        params["observation_start"] = observation_start.isoformat()
    if observation_end is not None:
        params["observation_end"] = observation_end.isoformat()

    owns_client = client is None
    if client is None:
        # ``http2=False`` and ``follow_redirects=True`` mirror catalysts.py.
        # Keep-alive is left at httpx's default here, unlike the OpenBB local
        # client: that client disables it because the *local* service mishandles
        # reused connections (404 from a second request). FRED is a normal host
        # and does not have that defect.
        client = httpx.Client(
            http2=False,
            timeout=timeout_seconds,
            follow_redirects=True,
            headers=_REQUEST_HEADERS,
        )

    last_error: Exception | None = None
    try:
        for attempt in range(1, max_attempts + 1):
            try:
                response = client.get(ALFRED_OBSERVATIONS_URL, params=params)
                response.raise_for_status()
                return _parse_observations(response.json(), series_id=series_id, as_of=as_of)
            except (httpx.HTTPError, json.JSONDecodeError, VintageReadError) as exc:
                # A VintageReadError is included here because FRED can answer a
                # valid request with a body that is not the expected shape under
                # load. It is retried, but it is NOT reclassified: if the budget
                # is spent it surfaces as the read error it is, so a shape
                # problem is never reported as an outage.
                last_error = exc
                logger.warning(
                    "ALFRED vintage read for %s as-of %s attempt %s/%s failed: %s",
                    series_id,
                    as_of.isoformat(),
                    attempt,
                    max_attempts,
                    exc,
                )
                if attempt < max_attempts:
                    time.sleep(backoff_seconds * attempt)
    finally:
        if owns_client:
            client.close()

    raise VintageReadError(
        f"ALFRED vintage read for {series_id} as-of {as_of.isoformat()} failed "
        f"after {max_attempts} attempts: {last_error}"
    )


def describe_route() -> dict[str, str]:
    """Identify this fetch path for provenance and for the guard test.

    ``ObservationPoint.source`` records which path produced a value, and the two
    paths must be distinguishable in the audit trail — a value pulled through
    OpenBB and a value pulled directly are the same number with different
    reliability. The guard test asserts this returns a route name that is not
    either of ``openbb_client``'s path constants.
    """
    return {
        "route": ROUTE_NAME,
        "host": FRED_HOST,
    }
