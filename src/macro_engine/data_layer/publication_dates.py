"""Section 6 exact publication-date lookup — ``last_updated`` per series.

Why this exists, and how it relates to ``release_calendar.py``
--------------------------------------------------------------
``release_calendar.py`` fills ``release_datetime`` by joining a *scheduled
events calendar* to a registry series through a hand-written event-name map.
That works, but it is indirect: it only covers series whose release appears as a
named event, the join must be maintained by hand, and its route turned out to be
intermittent and edge-blocked.

This module is the direct route. Every FRED series carries ``last_updated`` in
its own metadata — the instant the source last wrote that series. No event map,
no join, no scheduled-date inference: the provider states the publication time
on the record itself.

**Measured live 2026-09-20: 42 of 42 then-resolvable registry symbols returned a
``last_updated``, 0 transport errors.** That is the coverage claim, and it is a
count, not an impression. The denominator is dated on purpose and it has since
moved: re-measured 2026-10-05, the registry declares **59** series of which
**50** resolve through this route, so 42/42 describes the 2026-09-20 registry
rather than today's. The ROUTE is unchanged — the registry grew.

What ``last_updated`` is, and is not
------------------------------------
It IS a publication timestamp. Verified by cross-check rather than assumed:
``PCEPILFE`` reports ``last_updated`` 2026-08-26 while the events calendar dates
the Core PCE release 2026-08-27. A one-day gap in that direction is what a
"source wrote it" versus "the release happened" pair looks like, and it confirms
the field tracks publication rather than the observation period. A quarterly
check agrees: ``GDP`` has ``observation_end`` 2026-04-01 (the Q2 quarter) and
``last_updated`` 2026-08-26 (the second estimate) — the observation period and
the write time are plainly different quantities.

It is NOT a vintage. ``fred_search`` also returns ``realtime_start`` and
``realtime_end``, which look like ALFRED's vintage bounds. They are not: for
every series both equal **today**, because they describe the vintage window in
force *now*, not the revisions that existed in the past. Passing
``realtime_start`` as a query parameter is silently ignored — A/B tested, and
the two responses differed only in request ``timestamp``/``duration`` metadata.

So this module can populate ``release_datetime`` and cannot populate
``vintage_datetime``. Those are different questions — "when did this become
public" versus "which revision is this" — and only the first is answerable here.
Reporting a current-vintage window as a revision identity would be the exact
substitution Section 6 prohibits, so it is not done.

**Superseded in part (D-088, 2026-09-22).** "Only the first is answerable here"
is a claim about **this module**, and it still holds — this route cannot fill a
vintage and the absorption finding above is unchanged. It is no longer a claim
about the engine: ``alfred_client.py`` reaches ALFRED directly and fills
``vintage_datetime`` for a series declared ``vintage_eligible``. The two are
complementary routes, and this module remains the one that answers publication
timing.

The exact-match rule
--------------------
``search_type=series_id`` is a **prefix** search. ``UNRATE`` is returned
alongside ``UNRATECTH``, ``UNRATECTL`` and other longer siblings, and at a small
limit the exact row can be crowded out entirely — measured: a limit of 5 for
``UNRATE``, ``GDP`` and ``GDPC1`` returned 5 prefix siblings and no exact match,
while a limit of 1000 surfaced all three.

So the reader requires an **exact** ``series_id`` equality and accepts nothing
else. A prefix sibling's ``last_updated`` belongs to a different series; using it
would attach one series' publication time to another, which is a wrong fact
rather than a missing one. Missing is recoverable; wrong is not.

Contract
--------
* Retry, because the route can fail transiently.
* On exhaustion, return an EMPTY mapping — never a guessed date, never an
  observation date.
* A series whose metadata could not be read simply has no entry, which the
  caller already renders as ``release_datetime=None`` (UNKNOWN) through
  ``has_known_release_timing``.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

import httpx

from macro_engine.config import PublicationDates, get_registry, get_settings
from macro_engine.data_layer.release_calendar import ReleaseDateIndex

logger = logging.getLogger(__name__)

__all__ = [
    "PublicationDateError",
    "fetch_publication_dates",
]


class PublicationDateError(Exception):
    """Raised only for a misconfiguration that a retry could never resolve."""


def _resolve_series_symbols() -> dict[str, str]:
    """Registry series name -> provider symbol, for series that have one.

    Three conditions, and only three:

    * Curve entries (``tenors``) are skipped: a curve is not a single series and
      has no one publication time, so attributing the first tenor's stamp to the
      whole curve would be a fabricated fact.
    * An entry with no ``symbol`` is skipped, because there is nothing to query.
    * An entry whose ``provider`` is not ``fred`` is skipped: this route is the
      FRED ``economy.fred_search`` endpoint, which only knows FRED series. World
      Bank and EIA symbols (``PA.NUS.PPP``, ``WCESTUS1``) are not FRED series,
      and the lookup against them returns a non-JSON body that cannot be parsed —
      measured 2026-09-29: 7 of the then-57 registry symbols (all non-fred, all
      ``not_a_snapshot_field``) produced 21 failing calls per build, every one a
      guaranteed ``JSONDecodeError``, purely to learn that no FRED ``last_updated``
      exists for them. Skipping them at the source removes the wasted calls and
      the misleading warnings; their release timing correctly stays UNKNOWN,
      because no FRED publication stamp exists for them anyway. (The 7 is
      unchanged as of 2026-10-05; only the denominator moved, 57 -> 59.)

    ``status`` is **deliberately not consulted here**. An earlier version of this
    docstring claimed ``blocked``/``unverified`` entries were "skipped too"; they
    are not, and they do not need to be. Measured (re-measured 2026-10-05): the
    registry declares **59** series and **every carried entry is
    ``status: verified``** —
    ``grep -oE "status: [a-z_]+" config/series_registry.yaml`` returns exactly one
    value, 59 times.

    Note the SHAPE of that grep, because the earlier revision got it wrong: a
    bare ``grep -c "unverified"`` returns **3** and ``grep -c "blocked"`` returns
    **13**, since both words also appear in the registry's own status legend
    (lines 12-14) and in the separate top-level ``blocked:`` key — never as
    ``status:`` fields. The old text claimed those greps return 0, which was
    itself the reassuring-but-unchecked kind of claim this paragraph exists to
    warn about: a grep has to be shaped to the field it is meant to measure, and
    a number nobody re-ran is not evidence.

    ``blocked`` entries are not carried in ``.series`` at all, so they are absent
    by construction rather than by this filter. Should a route ever be re-pointed
    to ``unverified``, **this function would still return its symbol** and the
    fetch would raise at the boundary that owns that rule (Section 21.0 rule 5),
    which is the correct place for the refusal.
    """
    resolved: dict[str, str] = {}
    for name, entry in get_registry().series.items():
        if entry.symbol and not entry.tenors and entry.provider == "fred":
            resolved[name] = entry.symbol
    return resolved


def _extract_exact(symbol: str, payload: object) -> datetime | None:
    """The ``last_updated`` for ``symbol`` parsed to a datetime, or ``None``.

    Three requirements here are load-bearing. The ``series_id`` equality rejects
    prefix siblings (``UNRATECTH`` for ``UNRATE``). The dict-shaped row check
    rejects any payload that is not the expected object, rather than letting an
    ``AttributeError`` escape from deep inside the loop. And the parse is
    strict: the provider returns an OFFSET-AWARE stamp
    (``2026-09-11T08:37:49-05:00``), and that offset is PRESERVED rather than
    normalised to UTC, because it is the source's own statement of when it
    wrote the value. ``datetime.fromisoformat`` keeps it; a naive parse would
    silently drop the offset and shift the instant.
    """
    if not isinstance(payload, dict):
        return None
    results = payload.get("results")
    if not isinstance(results, list):
        return None
    for row in results:
        if not isinstance(row, dict):
            continue
        if row.get("series_id") != symbol:
            continue
        stamp = row.get("last_updated")
        if not isinstance(stamp, str) or not stamp.strip():
            continue
        try:
            return datetime.fromisoformat(stamp)
        except ValueError:
            logger.warning("publication date for %s: unparseable last_updated %r", symbol, stamp)
            return None
    return None


def fetch_publication_dates(
    *,
    client: httpx.Client | None = None,
    cfg: PublicationDates | None = None,
) -> ReleaseDateIndex:
    """Read ``last_updated`` for every resolvable registry series.

    Returns a ``ReleaseDateIndex`` so the caller consumes one type regardless of
    which source answered. ``route_read`` is True when at least one series was
    read, which is the honest signal here: this route is per-series, so a single
    failure must not mark the whole read as broken.

    A series that cannot be read is simply absent from ``dates``, and its
    ``release_datetime`` stays ``None`` downstream. There is deliberately no
    partial-substitution path.
    """
    config = cfg or get_registry().publication_dates
    if not config.enabled:
        raise PublicationDateError(
            "publication_dates is disabled in config/series_registry.yaml; "
            "enable it before requesting publication dates"
        )

    symbols = _resolve_series_symbols()
    if not symbols:
        raise PublicationDateError(
            "no registry series declare a `symbol`, so there is nothing to look "
            "up a publication date for"
        )

    owns_client = client is None
    if client is None:
        openbb = get_settings().openbb
        client = httpx.Client(
            base_url=openbb.base_url.rstrip("/"),
            timeout=openbb.timeout,
            verify=openbb.ssl_verify,
            limits=httpx.Limits(max_keepalive_connections=0),
        )

    url = f"/api/v1/{config.endpoint.replace('.', '/')}"
    dates: dict[str, datetime] = {}
    failures: list[str] = []

    try:
        for series, symbol in symbols.items():
            params = {
                "provider": config.provider,
                "query": symbol,
                "search_type": config.search_type,
                "limit": str(config.limit),
            }
            for attempt in range(1, config.max_attempts + 1):
                try:
                    resp = client.get(url, params=params)
                    resp.raise_for_status()
                    payload = resp.json()
                except (httpx.HTTPError, ValueError) as exc:
                    logger.warning(
                        "publication date for %s (%s) attempt %s/%s failed: %s",
                        series,
                        symbol,
                        attempt,
                        config.max_attempts,
                        exc,
                    )
                    if attempt < config.max_attempts:
                        time.sleep(config.backoff_seconds * attempt)
                    continue

                stamp = _extract_exact(symbol, payload)
                if stamp is not None:
                    dates[series] = stamp
                    break

                # No exact match. Two DIFFERENT situations hide here, and
                # collapsing them is a bug either way round:
                #
                #   * An EMPTY result set. The route returned nothing at all,
                #     which this provider does intermittently (the same
                #     non-determinism the events calendar showed). Retryable.
                #   * A NON-EMPTY result set with no exact row. The read
                #     succeeded and the symbol genuinely is not there — e.g. a
                #     prefix search whose exact row fell outside the limit, or a
                #     symbol FRED does not carry. Retrying cannot change a
                #     well-formed answer, so it is pure latency.
                #
                # Treating empty-as-absent would skip the retry budget entirely
                # and turn a transient blank into a permanent data gap;
                # treating absent-as-empty would burn the budget on every
                # genuinely-unmapped symbol in every build.
                results = payload.get("results") if isinstance(payload, dict) else None
                if not results:
                    logger.warning(
                        "publication date for %s (%s) attempt %s/%s: empty result set",
                        series,
                        symbol,
                        attempt,
                        config.max_attempts,
                    )
                    if attempt < config.max_attempts:
                        time.sleep(config.backoff_seconds * attempt)
                    continue

                logger.warning(
                    "publication date for %s (%s): no exact series_id match among "
                    "%s rows (prefix siblings do not qualify)",
                    series,
                    symbol,
                    len(results),
                )
                break
            else:
                failures.append(series)
    finally:
        if owns_client:
            client.close()

    if failures:
        logger.warning(
            "publication dates unread for %s of %s series after retries: %s",
            len(failures),
            len(symbols),
            ", ".join(sorted(failures)),
        )

    logger.info(
        "publication dates read for %s of %s registry series",
        len(dates),
        len(symbols),
    )
    return ReleaseDateIndex(
        dates=dates,
        match_counts=dict.fromkeys(dates, 1),
        route_read=bool(dates),
    )
