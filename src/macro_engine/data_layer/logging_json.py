"""Structured JSON logging — one machine-parseable object per line.

AGENTS.md Section 10.3 mandates structured logging. ``config/logging.yaml``
already references ``macro_engine.data_layer.logging_json.JsonFormatter``; this
module is that reference, implemented rather than assumed.

Why JSON-per-line rather than a human-readable format
-----------------------------------------------------
A macro engine's logs are consumed by aggregators, not read by eye during an
incident. The format decision therefore follows from the consumer: every record
is emitted as a single JSON object so that ``jq``, Loki, Datadog, or CloudWatch
can filter on a field without a bespoke regex. Specifying the format in
``logging.yaml`` and implementing it here keeps the *shape* of the output in
config while the *serialization* lives in code, which is the correct split —
a formatter is executable behaviour, not configuration.

Audit-trail fields
------------------
Beyond the standard record attributes, this formatter emits whichever of the
audit fields are present on the record:

``audit_event``
    A stable, machine-checkable event name (e.g. ``model.computed``).
``correlation_id``
    Ties every log line produced while handling one request or one thesis build
    together. Without it, a 20-model build interleaves in the logs and a failure
    cannot be attributed to the run that produced it.
``actor``
    Who or what caused the event — a service account, an operator, a scheduled
    job. Required for an audit trail to answer "who did this".
``duration_ms``
    Wall-clock cost, so latency regressions are visible in logs rather than
    discovered in production.

None of these are invented here: they are the minimum set an audit trail needs
to answer *what happened, to which run, caused by whom, and at what cost*.

Redaction
---------
``_REDACT_KEY_FRAGMENTS`` covers credential-shaped keys, matched as
substrings so that ``database_password`` is caught as well as ``password``. A
logger is the single easiest place to leak a secret in an institutional
system, because ``extra={...}`` accepts anything and logs are shipped off-box
by default. Redaction is applied recursively so a credential nested inside a
config dump is caught too.
"""

from __future__ import annotations

import json
import logging
import traceback
from datetime import UTC, datetime
from typing import Any

__all__ = ["JsonFormatter", "configure_logging", "get_logger"]

# Substrings that mark a key as credential-shaped. Matched case-insensitively
# as a *substring* of the key, not by equality — ``database_password`` and
# ``db_password`` and ``user_password`` all carry a password, and an equality
# check silently missed every one of them. Over-redaction is the correct
# direction to err in: a redacted field costs a debug session, a leaked one
# costs the institution.
#
# ``session`` is deliberately absent despite being credential-shaped in some
# frameworks: as a plain substring it also matches ``session_count``,
# ``session_id``, and ``session_duration``, which are ordinary operational
# counters. ``session_token`` IS covered by the ``token`` fragment, but
# ``session_key`` is NOT covered by ``private_key`` — neither string is a
# substring of the other (measured) — so both are listed explicitly below.
# Removing either because it "looks redundant" is the mistake this note exists
# to prevent; the narrow set keeps diagnostic fields readable without losing a
# credential-shaped key.
_REDACT_KEY_FRAGMENTS: frozenset[str] = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "credential",
        "passwd",
        "password",
        "private_key",
        "secret",
        "session_key",
        "sessionid",
        "session_token",
        "token",
    }
)

_REDACTED = "***REDACTED***"


def _is_credential_shaped(key: object) -> bool:
    """Whether a mapping key looks like it holds a credential."""
    lowered = str(key).lower()
    return any(fragment in lowered for fragment in _REDACT_KEY_FRAGMENTS)


# Fields a LogRecord carries by default. Anything outside this set arrived via
# ``extra={...}`` and is therefore deliberate context worth emitting.
_STANDARD_ATTRS: frozenset[str] = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)

# The audit-trail fields, listed explicitly so the formatter's contract is
# readable in one place rather than implied by a set difference.
_AUDIT_FIELDS: tuple[str, ...] = ("audit_event", "correlation_id", "actor", "duration_ms")


def _redact(value: Any, *, depth: int = 0) -> Any:
    """Recursively redact credential-shaped keys.

    Depth-limited: a self-referential structure would otherwise recurse until
    the interpreter's stack limit, turning a logging call into a crash. Eight
    levels is far beyond any legitimate log payload.

    Every container is walked so a credential-shaped KEY is caught wherever it
    sits: dicts by key, and lists/tuples/sets by element (recursing into any
    dict inside). A ``set`` can never hold a dict — dicts are unhashable — so no
    key redaction is lost by walking one. It is included for FIDELITY: a set is
    not JSON-serialisable, so before it was handled here it reached
    ``json.dumps``'s ``default=str`` and shipped as its repr (``"{'a', 'b'}"``)
    instead of a real JSON array. Note that redaction is KEY-based by design: a
    bare credential VALUE (a string in a list, say) has no key to test and is
    not redacted anywhere, which is why secrets belong in ``extra={...}`` under
    a credential-shaped key rather than interpolated into the message.
    """
    if depth > 8:
        return "<max-depth-exceeded>"
    if isinstance(value, dict):
        return {
            key: (_REDACTED if _is_credential_shaped(key) else _redact(item, depth=depth + 1))
            for key, item in value.items()
        }
    if isinstance(value, list | tuple | set | frozenset):
        return [_redact(item, depth=depth + 1) for item in value]
    if isinstance(value, str) and len(value) > 2000:
        # A multi-kilobyte string in a log line is usually a whole document
        # pasted in by accident. Truncate with a marker rather than shipping it.
        return value[:2000] + f"...<truncated {len(value) - 2000} chars>"
    return value


class JsonFormatter(logging.Formatter):
    """Render a ``LogRecord`` as one JSON object.

    AGENTS.md Section 10.3. The output is deliberately flat at the top level —
    ``timestamp``, ``level``, ``logger``, ``message`` — with everything else
    under ``context``. Flat top-level fields let an aggregator index on them
    without a path expression, which is the difference between a query that
    runs and one that scans.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Location is emitted only at WARNING and above: it is the first thing
        # needed when triaging, and pure noise on a routine INFO line.
        if record.levelno >= logging.WARNING:
            payload["location"] = f"{record.pathname}:{record.lineno}"
            payload["function"] = record.funcName

        for field in _AUDIT_FIELDS:
            found = getattr(record, field, None)
            if found is not None:
                payload[field] = _redact(found)

        # Redact the keys as well as the values. Calling ``_redact`` on the
        # value alone is not enough and was the original defect here: ``api_key``
        # is an ordinary string, so redacting it by *value* returns it unchanged
        # and the secret ships in the log line. The key is the signal, so the
        # key is what must be tested. Routing the whole dict through ``_redact``
        # keeps one implementation of the rule rather than two that can drift.
        context = _redact(
            {
                key: value
                for key, value in record.__dict__.items()
                if key not in _STANDARD_ATTRS
                and key not in _AUDIT_FIELDS
                and not key.startswith("_")
            }
        )
        if context:
            payload["context"] = context

        if record.exc_info:
            payload["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]),
                "traceback": "".join(traceback.format_exception(*record.exc_info)).splitlines(),
            }

        if record.stack_info:
            payload["stack"] = record.stack_info

        # ``default=str`` so a date, Decimal, or Path in an ``extra`` payload
        # degrades to its string form rather than raising inside the logger and
        # losing the record — a logger that can throw is worse than one that
        # loses type fidelity.
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(config_path: str | None = None) -> None:
    """Apply ``config/logging.yaml`` to the stdlib logging tree.

    Configuration lives in YAML (Section 10.4's "no hardcoded values" rule);
    this function only points the stdlib at it. A missing config file is a hard
    error rather than a silent fallback to ``basicConfig``, because a service
    that logs unstructured JSON-less output when its config is absent is a
    service whose logs cannot be trusted during the incident that removed the
    config.
    """
    import logging.config
    from pathlib import Path

    import yaml

    from macro_engine.config import project_root

    path = Path(config_path) if config_path else project_root() / "config" / "logging.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Logging config missing: {path}")
    with path.open("r", encoding="utf-8") as handle:
        logging.config.dictConfig(yaml.safe_load(handle))


def get_logger(name: str) -> logging.Logger:
    """Namespaced logger accessor.

    A thin wrapper, but it makes the convention explicit: every module logs
    under ``macro_engine.*`` so the logger config in ``logging.yaml`` applies
    without each module re-declaring handlers.
    """
    return logging.getLogger(name)
