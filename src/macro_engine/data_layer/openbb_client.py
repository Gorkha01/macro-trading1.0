"""Resilient OpenBB data gateway (AGENTS.md Section 5.1).

Implements the two-path fetch strategy: try the **local OpenBB Platform API**
first (``http://127.0.0.1:6900``) for lower latency and to avoid re-initialising
the SDK per call, then **fall back to the Python package** if the local API is
unreachable. After retries are exhausted it attempts the *other* path once
before giving up.

The contract callers depend on: every public method either returns a
normalized ``pandas.DataFrame`` with columns ``[date, value, series_id,
source, retrieved_at]``, or raises ``OpenBBFetchError``. Callers handle **one**
exception type and never see a raw provider exception.

Fixes applied relative to the specification's sample code:

* ``datetime.utcnow()`` -> timezone-aware ``utc_now()``. The sample wrote a
  naive datetime into ``retrieved_at``, which makes the future-dating check in
  ``validation.py`` ambiguous about which timezone it is comparing against.
* The local-API URL is built with an explicit ``/api/v1/`` prefix once, at
  client construction, rather than string-replacing dots per call.
* ``_normalize`` handles the several shapes OpenBB actually returns (a
  ``results`` list, a ``to_df()`` object, or a bare frame) and refuses to
  guess when the date column is missing.
"""

from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any

import httpx
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from macro_engine.config import get_settings
from macro_engine.models.contracts import utc_now

__all__ = [
    "OpenBBClient",
    "OpenBBClientConfig",
    "OpenBBFetchError",
]

logger = logging.getLogger(__name__)

# OpenBB's normalized frame contract. Anything else is a parse failure and
# must surface as OpenBBFetchError rather than a downstream KeyError.
NORMALIZED_COLUMNS: tuple[str, ...] = ("date", "value", "series_id", "source", "retrieved_at")


class OpenBBFetchError(RuntimeError):
    """Raised when both the local API and the Python package path fail.

    The single exception type the rest of the system catches for data
    problems. A subclass of ``RuntimeError`` so that a top-level handler which
    only knows builtins still catches it.
    """


class OpenBBClientConfig(BaseModel):
    """Client tuning.

    Every value defaults from ``config/settings.yaml`` (the ``openbb:`` block)
    rather than from a literal here. ``OPENBB_API_URL`` in the environment
    overrides the base URL, so a deployment can redirect the client without
    editing a committed file.
    """

    model_config = ConfigDict(extra="forbid")

    local_api_base_url: str = Field(default_factory=lambda: get_settings().openbb.base_url)
    use_local_api_first: bool = Field(default_factory=lambda: get_settings().openbb.local_first)
    max_retries: int = Field(default_factory=lambda: get_settings().openbb.retries, ge=1)
    backoff_seconds: float = Field(default_factory=lambda: get_settings().openbb.backoff, ge=0.0)
    timeout_seconds: float = Field(default_factory=lambda: get_settings().openbb.timeout, gt=0.0)
    verify_ssl: bool = Field(default_factory=lambda: get_settings().openbb.ssl_verify)


class OpenBBClient:
    """Thin, resilient wrapper around OpenBB (Section 5.1).

    Not thread-safe by design: the underlying ``httpx.Client`` is shared and
    reused, which is the point (connection pooling), but callers in a threaded
    context should construct one client per thread.
    """

    def __init__(self, config: OpenBBClientConfig | None = None) -> None:
        self.config = config or OpenBBClientConfig()
        # Keep-alive is DISABLED on purpose. Measured 2026-09-19 against the live
        # local OpenBB Platform API: a client that reuses its connection gets
        # 200 on the first request and **404 on every subsequent one**, for
        # every route including ``/openapi.json`` (whose own 278-path body was
        # returned 200 the first time). The server does not close the socket and
        # does not error; it serves ``{"detail":"Not Found"}`` from a reused
        # connection.
        #
        # Proven by isolation, three requests to ``/openapi.json`` each:
        #
        #     default client (keep-alive on)   [200, 404, 404]
        #     ``Connection: close`` header     [200, 200, 200]
        #     ``max_keepalive_connections=0``  [200, 200, 200]
        #
        # Consequence before this fix: ``is_local_api_available()`` returned
        # True, then False, then False, so ``/health`` reported the local server
        # as down from the second call onward; and every local-first fetch burned
        # three retries (~4.5s at the configured 1.5s backoff) before falling
        # back to the in-process package. That masking is why the 23x local-first
        # slowdown recorded in ``settings.yaml`` is *partly* this defect rather
        # than provider latency -- the measurement stands (the package path is
        # still faster), but a local-first run was paying retry cost on top of
        # it that a working connection would not have paid.
        #
        # One connection per request is the cost. For a 21-field snapshot that
        # is 21 TCP handshakes to localhost, which is negligible next to the
        # seconds the retry path was costing.
        self._http = httpx.Client(
            base_url=self.config.local_api_base_url.rstrip("/"),
            timeout=self.config.timeout_seconds,
            verify=self.config.verify_ssl,
            limits=httpx.Limits(max_keepalive_connections=0),
        )
        # Lazy-imported only if the local API path fails. Importing `openbb`
        # eagerly costs seconds of startup time for a path that may never run.
        self._obb: Any = None

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> OpenBBClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _lazy_import_obb(self) -> Any:
        if self._obb is None:
            from openbb import obb

            self._obb = obb
        return self._obb

    # -- public API --------------------------------------------------------

    def fetch_series(
        self,
        *,
        provider: str,
        endpoint: str,
        params: dict[str, Any],
        series_label: str,
    ) -> pd.DataFrame:
        """Fetch one series, with retries and cross-path fallback.

        Parameters
        ----------
        provider:
            OpenBB provider name, e.g. ``"fred"``. Passed through in the
            request body / kwargs; the registry is the only place that should
            be naming providers.
        endpoint:
            Dotted endpoint path, e.g. ``"economy.fred_series"``.
        params:
            Provider-specific query parameters, e.g. ``{"symbol": "CPIAUCSL"}``.
        series_label:
            The internal field name this maps to. Appears in ``series_id``
            and in error messages, so it should be the registry key, not the
            provider's symbol.
        """
        last_exc: Exception | None = None
        for attempt in range(1, self.config.max_retries + 1):
            try:
                if self.config.use_local_api_first:
                    return self._fetch_via_local_api(provider, endpoint, params, series_label)
                return self._fetch_via_package(endpoint, params, series_label)
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "fetch_series attempt %s/%s failed for %s: %s",
                    attempt,
                    self.config.max_retries,
                    series_label,
                    exc,
                )
                if attempt < self.config.max_retries:
                    time.sleep(self.config.backoff_seconds * attempt)
                else:
                    # Final attempt exhausted the primary path. Try the other
                    # one exactly once before declaring total failure.
                    try:
                        if self.config.use_local_api_first:
                            return self._fetch_via_package(endpoint, params, series_label)
                        return self._fetch_via_local_api(provider, endpoint, params, series_label)
                    except Exception as fallback_exc:
                        last_exc = fallback_exc
                        logger.warning(
                            "cross-path fallback also failed for %s: %s", series_label, fallback_exc
                        )
        raise OpenBBFetchError(
            f"Failed to fetch {series_label} via both local API and package "
            f"after {self.config.max_retries} attempts: {last_exc}"
        )

    def is_local_api_available(self) -> bool:
        """Probe the local API. Used by /health, never on the hot path.

        The OpenBB Platform API does **not** expose ``/api/v1/health``. Probing
        it returned 404, and the original ``status_code < 500`` test then
        reported a dead server as *available* — a false positive that would
        make ``/health`` lie. Verified against the live server's own
        ``/openapi.json`` (278 routes, none of them a health endpoint).

        The reliable liveness signal is ``/openapi.json``: it is served by the
        FastAPI app itself, it is cheap, and a 200 proves the app is up rather
        than merely that something is listening on the port.
        """
        try:
            resp = self._http.get("/openapi.json", timeout=2.0)
        except httpx.HTTPError:
            return False
        return resp.status_code == 200

    # -- fetch paths -------------------------------------------------------

    def _fetch_via_local_api(
        self, provider: str, endpoint: str, params: dict[str, Any], series_label: str
    ) -> pd.DataFrame:
        """GET from the local OpenBB Platform API.

        The provider arrives as a query parameter (``provider=fred``) rather
        than being baked into the URL path, because that is how OpenBB's REST
        surface is shaped: one endpoint, provider selected by parameter.
        """
        url = f"/api/v1/{endpoint.replace('.', '/')}"
        query: dict[str, Any] = {"provider": provider, **params}
        resp = self._http.get(url, params=query)
        resp.raise_for_status()
        payload = resp.json()
        if isinstance(payload, dict) and "results" in payload:
            raw: Any = payload["results"]
        else:
            raw = payload
        return self._normalize(raw, series_label)

    def _fetch_via_package(
        self, endpoint: str, params: dict[str, Any], series_label: str
    ) -> pd.DataFrame:
        """Call the ``openbb`` Python package directly, for the same endpoint."""
        obb = self._lazy_import_obb()
        target: Any = obb
        for part in endpoint.split("."):
            try:
                target = getattr(target, part)
            except AttributeError as exc:
                raise OpenBBFetchError(
                    f"openbb package has no endpoint '{endpoint}' (failed at '{part}')"
                ) from exc
        result = target(**params)
        if hasattr(result, "to_df"):
            return self._normalize(result.to_df(), series_label)
        return self._normalize(result, series_label)

    # -- normalization -----------------------------------------------------

    def _normalize(self, raw: Any, series_label: str) -> pd.DataFrame:
        """Coerce an OpenBB response into the normalized frame contract.

        Handles the shapes OpenBB actually produces, verified against the live
        FRED provider during Phase 0:

        * a ``DataFrame`` with a ``date`` column,
        * a ``DataFrame`` where the date is the **index** — this is what
          ``economy.fred_series`` returns: a single ``cpiaucsl`` column with a
          ``DatetimeIndex`` and no date column at all,
        * a list of records.

        Refuses to invent a date column. If OpenBB changes its response shape,
        this raises ``OpenBBFetchError`` with the observed columns, rather than
        producing a frame that silently mis-aligns every downstream model.
        """
        if isinstance(raw, pd.DataFrame):
            df = raw.copy()
        elif isinstance(raw, list | dict):
            df = pd.DataFrame(raw)
        else:
            raise OpenBBFetchError(
                f"Cannot normalize {type(raw).__name__} for {series_label}; "
                f"expected DataFrame/list/dict"
            )
        if df.empty:
            raise OpenBBFetchError(f"Provider returned an empty frame for {series_label}")

        # Promote a date-bearing INDEX to a real column BEFORE lowercasing.
        #
        # Verified against the live FRED provider, ``economy.fred_series``
        # returns a single ``CPIAUCSL`` column with the dates carried in the
        # INDEX — as an object-dtype ``Index`` of ``datetime.date`` objects
        # named "date", NOT a ``pd.DatetimeIndex``. Testing only for
        # ``DatetimeIndex`` therefore misses the common case entirely, which is
        # how the first implementation failed against the real provider.
        #
        # The date index is detected by name or by inspecting the first value,
        # never assumed.
        df.columns = [str(c).lower() for c in df.columns]
        if self._pick_date_column(df.columns.tolist()) is None and self._index_looks_like_dates(df):
            df = df.reset_index()
            df.columns = [
                "date" if position == 0 else str(name).lower()
                for position, name in enumerate(df.columns)
            ]
            logger.debug("Promoted date index to a 'date' column for %s", series_label)

        date_col = self._pick_date_column(df.columns.tolist())
        if date_col is None:
            raise OpenBBFetchError(
                f"Normalized frame for {series_label} has no recognizable date column; "
                f"got columns {df.columns.tolist()}, index type {type(raw).__name__}"
            )

        value_col = self._pick_value_column(df.columns.tolist(), exclude={date_col})
        if value_col is None:
            raise OpenBBFetchError(
                f"Normalized frame for {series_label} has no recognizable value column; "
                f"got columns {df.columns.tolist()}"
            )

        out = df[[date_col, value_col]].rename(columns={date_col: "date", value_col: "value"})
        # Drop nulls before the float cast so a trailing holiday/blank row does
        # not turn the whole column into object dtype.
        out = out.dropna(subset=["value"])
        out["value"] = pd.to_numeric(out["value"], errors="coerce")
        out = out.dropna(subset=["value"])
        if out.empty:
            raise OpenBBFetchError(f"All values were null/unparseable for {series_label}")

        out["date"] = pd.to_datetime(out["date"]).dt.date
        out["series_id"] = series_label
        out["source"] = (
            f"openbb:{self.config.local_api_base_url}"
            if self.config.use_local_api_first
            else "openbb:package"
        )
        out["retrieved_at"] = utc_now()
        out = out.sort_values("date").reset_index(drop=True)
        return out[list(NORMALIZED_COLUMNS)]

    @staticmethod
    def _index_looks_like_dates(df: pd.DataFrame) -> bool:
        """Whether a frame's index carries dates worth promoting to a column.

        Uses three signals, because no single one is reliable across providers:

        1. the index is named something date-like,
        2. the index is a ``pd.DatetimeIndex``,
        3. the first index value is a ``datetime.date``/``datetime`` instance.

        Signal (3) is the one that catches ``fred_series``, whose index is an
        object-dtype ``Index`` of ``datetime.date`` objects.
        """
        if df.index.name is not None and str(df.index.name).lower() in {
            "date",
            "datetime",
            "observation_date",
            "period",
            "timestamp",
        }:
            return True
        if isinstance(df.index, pd.DatetimeIndex):
            return True
        if len(df.index) > 0:
            first = df.index[0]
            # pd.Timestamp subclasses datetime.date, so one check covers both
            # the fred_series object-dtype-index case and a Timestamp index.
            if isinstance(first, date):
                return True
        return False

    @staticmethod
    def _pick_date_column(columns: list[str]) -> str | None:
        for candidate in ("date", "datetime", "observation_date", "period", "timestamp"):
            if candidate in columns:
                return candidate
        return None

    @staticmethod
    def _pick_value_column(columns: list[str], *, exclude: set[str]) -> str | None:
        """Choose the value column, preferring an exact ``value`` match.

        Deliberately does **not** fall back to "last column" blindly as the
        specification's sketch did — a mis-picked column is a silent
        wrong-number bug, which is precisely the failure class this system
        exists to prevent. It falls back only among known-plausible names.
        """
        if "value" in columns and "value" not in exclude:
            return "value"
        for candidate in ("close", "adj_close", "rate", "yield", "price", "amount"):
            if candidate in columns and candidate not in exclude:
                return candidate
        remaining = [c for c in columns if c not in exclude]
        if len(remaining) == 1:
            return remaining[0]
        return None


def to_observation_date(value: object) -> date:
    """Coerce a provider date value to ``datetime.date``."""
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()  # type: ignore[arg-type]
