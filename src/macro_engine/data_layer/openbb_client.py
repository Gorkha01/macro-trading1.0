"""Resilient OpenBB data gateway (AGENTS.md Section 5.1).

Implements the two-path fetch strategy: try the **local OpenBB Platform API**
first (``http://127.0.0.1:6901``) for lower latency and to avoid re-initialising
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
from math import isfinite
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
#
# `maturity` / `maturity_years` are part of the contract ONLY for a
# single-call curve endpoint, which answers every tenor in one response and has
# no other way to say which row is which tenor. They are carried when the
# provider sent them and absent otherwise, so a scalar series' frame is
# unchanged by their admission here. The alternative — letting `_normalize`
# drop them and having the curve fetcher recover the tenor by row position —
# would mis-assign an entire curve from a single reordered response, which is
# the silent-wrong-number class this module exists to refuse.
NORMALIZED_COLUMNS: tuple[str, ...] = ("date", "value", "series_id", "source", "retrieved_at")
#: Optional contract columns, present only when the provider supplied them.
NORMALIZED_OPTIONAL_COLUMNS: tuple[str, ...] = ("maturity", "maturity_years")
#: Columns that identify WHICH row a value belongs to, rather than being a
#: value themselves. `_pick_value_column`'s last-resort branch must never
#: return one of these: on a two-column curve frame (`date` + `maturity`) it
#: otherwise picks the label and the maturity NAME is cast as a rate. Derived
#: from `NORMALIZED_OPTIONAL_COLUMNS` rather than restated, so a label column
#: added to the contract is automatically protected here too.
LABEL_COLUMNS: frozenset[str] = frozenset(NORMALIZED_OPTIONAL_COLUMNS)

#: Which transport actually served a request. Recorded as provenance rather
#: than inferred from ``use_local_api_first``, because the cross-path fallback
#: means the two can disagree (see ``_normalize``).
_PATH_LOCAL_API = "local_api"
_PATH_PACKAGE = "package"


def _is_non_finite(value: object) -> bool:
    """Whether a value is a float that is neither finite nor a true null.

    ``dropna`` and this predicate are deliberately different tests, and the
    difference is the whole point: ``nan``/``inf`` are **not** null, so
    ``dropna`` leaves them in the frame. A provider that writes ``inf`` as its
    "no data" sentinel therefore delivers a value that is present, testable,
    and impossible to reject with a range comparison.

    A genuine ``None``/``np.nan`` is *not* reported here — it is ``dropna``'s
    job, and reporting it twice would double-log every ordinary gap.
    """
    if value is None:
        return False
    if not isinstance(value, (int, float)):
        # A non-numeric cell is `to_numeric(errors="coerce")`'s business; it has
        # already become nan by the time this runs, and this predicate only
        # classifies values that survived as numbers.
        return False
    return not isfinite(value)


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
        return self._normalize(raw, series_label, served_by=_PATH_LOCAL_API)

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
            return self._normalize(result.to_df(), series_label, served_by=_PATH_PACKAGE)
        return self._normalize(result, series_label, served_by=_PATH_PACKAGE)

    # -- normalization -----------------------------------------------------

    def _normalize(self, raw: Any, series_label: str, *, served_by: str) -> pd.DataFrame:
        """Coerce an OpenBB response into the normalized frame contract.

        ``served_by`` is the path that **actually** answered this request
        (``_PATH_LOCAL_API`` or ``_PATH_PACKAGE``), passed by the caller rather
        than inferred from ``use_local_api_first``. The two differ whenever the
        cross-path fallback fires, and reporting the *preferred* path as the
        *serving* path would attach a wrong provenance fact to every value
        fetched during a degradation — precisely when an operator needs to know
        which path produced the data. Missing is recoverable; wrong is not.

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

        # A curve endpoint answers ALL tenors in one response and identifies each
        # row by the provider's own maturity label. That label has to survive the
        # reduction to date/value or the caller cannot tell which tenor a row
        # belongs to — and a caller reduced to guessing by position would
        # mis-assign an entire curve. Per-row and null-preserved: it is carried
        # only when the provider actually sent it, never synthesized, because a
        # fabricated label would be indistinguishable from a real one.
        carry = [c for c in ("maturity", "maturity_years") if c in df.columns]
        out = df[[date_col, value_col, *carry]].rename(
            columns={date_col: "date", value_col: "value"}
        )
        # Drop nulls before the float cast so a trailing holiday/blank row does
        # not turn the whole column into object dtype.
        out = out.dropna(subset=["value"])
        out["value"] = pd.to_numeric(out["value"], errors="coerce")
        out = out.dropna(subset=["value"])
        # `dropna` removes nulls only. A coerced `inf`/`nan` is NOT null, so it
        # survives both drops above — `pd.to_numeric` preserves non-finite
        # floats, and a provider that exports `inf` as its "no data" sentinel
        # would otherwise deliver a poisoned value that every downstream range
        # check passes (`nan < min` and `nan > max` are both False). The row is
        # dropped, never repaired to 0 or to an interpolated value: a dropped
        # row makes the series shorter, whereas an invented value makes it
        # wrong (Section 21.0 rule 2).
        non_finite_mask = out["value"].map(_is_non_finite)
        if bool(non_finite_mask.any()):
            dropped = int(non_finite_mask.sum())
            logger.warning(
                "Dropped %d non-finite value(s) from %s: %s. A non-finite value is "
                "not missing data and is never repaired to a number.",
                dropped,
                series_label,
                out.loc[non_finite_mask, "date"].tolist(),
            )
            out = out[~non_finite_mask]
        if out.empty:
            raise OpenBBFetchError(f"All values were null/unparseable for {series_label}")

        out["date"] = pd.to_datetime(out["date"]).dt.date
        out["series_id"] = series_label
        # The path that SERVED this request, not the configured preference.
        # They differ whenever the cross-path fallback fired (see
        # `_fetch_series`), and a fallback is exactly when provenance matters:
        # `use_local_api_first=True` with the package having answered would
        # otherwise be recorded as "openbb:http://..." — a wrong fact.
        out["source"] = (
            f"openbb:{self.config.local_api_base_url}"
            if served_by == _PATH_LOCAL_API
            else "openbb:package"
        )
        out["retrieved_at"] = utc_now()
        out = out.sort_values("date").reset_index(drop=True)
        # Optional contract columns are kept ONLY when the provider sent them.
        # Projecting to the exact set present — rather than to a fixed list —
        # is what lets one contract serve both a scalar series and a
        # single-call curve without either shape acquiring a null column it
        # never had.
        present_optional = [c for c in NORMALIZED_OPTIONAL_COLUMNS if c in out.columns]
        return out[[*NORMALIZED_COLUMNS, *present_optional]]

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

        The last-resort branch excludes ``LABEL_COLUMNS`` as well as the date
        column. Without that, a single-call curve frame carrying only
        ``date`` + ``maturity`` (measured reachable: `_pick_value_column(['date',
        'maturity'])` returns ``'maturity'``) would rename the provider's
        **label** column to ``value`` and cast maturity NAMES to numbers. It
        would raise rather than publish a wrong number, so the blast radius is a
        misleading error — but "the maturity is the rate" is a defect worth
        refusing at the picker rather than discovering three frames later.
        """
        if "value" in columns and "value" not in exclude:
            return "value"
        for candidate in ("close", "adj_close", "rate", "yield", "price", "amount"):
            if candidate in columns and candidate not in exclude:
                return candidate
        remaining = [c for c in columns if c not in exclude and c not in LABEL_COLUMNS]
        if len(remaining) == 1:
            return remaining[0]
        return None


def to_observation_date(value: object) -> date:
    """Coerce a provider date value to ``datetime.date``."""
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()  # type: ignore[arg-type]
