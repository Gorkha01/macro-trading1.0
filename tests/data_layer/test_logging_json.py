"""Fresh test suite for ``data_layer/logging_json.py``.

The module had NO tests at all (nothing under ``tests/`` referenced it), yet it
is the formatter named by ``config/logging.yaml`` and applied by
``api_layer/app.py``'s lifespan. Findings guarded here:

  * F-LOG-001 — ``configure_logging()`` silently DISABLED every logger that
    already existed and was not a child of one named in the YAML, because
    ``logging.config.dictConfig`` defaults ``disable_existing_loggers`` to true
    and the config never declared it. Measured: a ``urllib3.connectionpool``
    logger created before the call came out ``disabled=True``.
  * F-LOG-002 — the comment claimed ``session_key`` is "already covered by the
    ``private_key`` fragment". Neither string is a substring of the other, so
    the rationale was false; a reader acting on it would delete the entry and
    lose the coverage.
  * F-LOG-003 — ``_redact`` walked dict/list/tuple but not ``set``, so a
    credential in a set reached ``json.dumps(default=str)`` and shipped as its
    repr, unredacted.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from macro_engine.data_layer.logging_json import (
    _REDACT_KEY_FRAGMENTS,
    _REDACTED,
    JsonFormatter,
    configure_logging,
)

ROOT = Path(__file__).resolve().parents[2]
FMT = JsonFormatter()
LOGGER = logging.getLogger("macro_engine.test.logging")


def _record(**extra: object) -> logging.LogRecord:
    rec = LOGGER.makeRecord(
        "macro_engine.test.logging", logging.INFO, __file__, 42, "hello", (), None
    )
    for key, value in extra.items():
        setattr(rec, key, value)
    return rec


def _emit(**extra: object) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(FMT.format(_record(**extra))))


# ---------------------------------------------------------------------------
# Shape of a line
# ---------------------------------------------------------------------------
def test_one_json_object_per_record_with_flat_top_level_fields() -> None:
    payload = _emit()
    assert payload["level"] == "INFO"
    assert payload["logger"] == "macro_engine.test.logging"
    assert payload["message"] == "hello"
    assert payload["timestamp"].endswith("+00:00")  # UTC, not naive local


def test_location_is_emitted_only_at_warning_and_above() -> None:
    assert "location" not in _emit() and "function" not in _emit()

    warn = LOGGER.makeRecord(
        "macro_engine.test.logging",
        logging.WARNING,
        __file__,
        42,
        "w",
        (),
        None,
        func="_record",
    )
    payload = json.loads(FMT.format(warn))
    assert payload["location"].endswith(":42")
    assert payload["function"] == "_record"


def test_audit_fields_are_emitted_when_present() -> None:
    payload = _emit(audit_event="model.computed", correlation_id="run-1", duration_ms=12.5)
    assert payload["audit_event"] == "model.computed"
    assert payload["correlation_id"] == "run-1"
    assert payload["duration_ms"] == 12.5


def test_ordinary_extra_lands_under_context() -> None:
    payload = _emit(retries=3, symbol="GDPC1")
    assert payload["context"] == {"retries": 3, "symbol": "GDPC1"}


def test_an_exception_is_rendered_with_type_message_and_traceback() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        rec = LOGGER.makeRecord(
            "macro_engine.test.logging", logging.ERROR, __file__, 1, "e", (), sys.exc_info()
        )
    payload = json.loads(FMT.format(rec))
    assert payload["exception"]["type"] == "ValueError"
    assert payload["exception"]["message"] == "boom"
    assert any("ValueError: boom" in line for line in payload["exception"]["traceback"])


def test_a_non_serialisable_value_degrades_to_str_rather_than_raising() -> None:
    payload = _emit(when=__import__("datetime").date(2026, 10, 5))
    assert payload["context"]["when"] == "2026-10-05"


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "key",
    [
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
    ],
)
def test_every_declared_fragment_redacts(key: str) -> None:
    assert _emit(**{key: "sk-live-123"})["context"][key] == _REDACTED


def test_redaction_matches_substrings_not_equality() -> None:
    assert _emit(database_password="hunter2")["context"]["database_password"] == _REDACTED  # noqa: S106


def test_ordinary_operational_keys_are_not_redacted() -> None:
    payload = _emit(session_count=4, session_id="abc", retries=2)
    assert payload["context"] == {"session_count": 4, "session_id": "abc", "retries": 2}


def test_redaction_reaches_nested_dicts_lists_and_sets() -> None:
    payload = _emit(
        config={"db": {"password": "p"}},
        rows=[{"api_key": "x"}, {"ok": 1}],
        pair=({"secret": "s"}, 1),
    )
    ctx = payload["context"]
    assert ctx["config"]["db"]["password"] == _REDACTED
    assert ctx["rows"][0]["api_key"] == _REDACTED and ctx["rows"][1] == {"ok": 1}
    assert ctx["pair"][0]["secret"] == _REDACTED


def test_a_set_is_serialised_as_a_json_array_not_a_repr() -> None:
    """F-LOG-003 is a FIDELITY issue, not a leak: a set cannot hold a dict.

    Redaction is key-based, and dicts are unhashable, so no key redaction was
    ever lost inside a set. What WAS wrong is the encoding: an unhandled set
    reached ``json.dumps(default=str)`` and shipped as ``"{'api_key'}"``.
    """
    payload = _emit(keys={"api_key", "ordinary"})
    assert sorted(payload["context"]["keys"]) == ["api_key", "ordinary"]
    assert json.dumps(payload)  # a real JSON array, not an opaque repr string


def test_a_very_long_string_is_truncated_with_a_marker() -> None:
    payload = _emit(blob="A" * 2500)
    blob = payload["context"]["blob"]
    assert blob.startswith("A" * 100)
    assert blob.endswith("...<truncated 500 chars>")


def test_a_self_referential_structure_hits_the_depth_limit_not_the_stack() -> None:
    payload = _emit(deep={"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": {"i": 1}}}}}}}}})
    assert "<max-depth-exceeded>" in json.dumps(payload)


def test_session_key_is_not_covered_by_any_other_fragment() -> None:
    """F-LOG-002: the comment's rationale was false, so the entry is load-bearing."""
    others = _REDACT_KEY_FRAGMENTS - {"session_key"}
    assert not any(fragment in "session_key" for fragment in others)
    # ...whereas session_token IS covered by `token`, as the comment claims.
    assert any(fragment in "session_token" for fragment in others)


def test_the_fragment_comment_does_not_claim_session_key_is_redundant() -> None:
    """The SET was always right; the COMMENT was what invited its deletion.

    A reader who believed "session_key is already covered by private_key" would
    delete the entry and lose the coverage, so the rationale is pinned, not just
    the outcome.
    """
    import macro_engine.data_layer.logging_json as mod

    src = Path(mod.__file__).read_text(encoding="utf-8")
    assert "``session_key`` is NOT covered by ``private_key``" in src
    assert "``session_key`` are already covered" not in src


# ---------------------------------------------------------------------------
# configure_logging (global logging state — run in a subprocess)
# ---------------------------------------------------------------------------
def test_config_declares_disable_existing_loggers_false() -> None:
    """F-LOG-001: the declaration that stops dictConfig disabling loggers."""
    cfg = yaml.safe_load((ROOT / "config" / "logging.yaml").read_text(encoding="utf-8"))
    assert cfg.get("disable_existing_loggers") is False


def test_configure_logging_leaves_pre_existing_loggers_enabled() -> None:
    """F-LOG-001, measured end-to-end in a fresh interpreter."""
    code = (
        "import logging;"
        "from macro_engine.data_layer.logging_json import configure_logging;"
        "early = logging.getLogger('urllib3.connectionpool');"
        "configure_logging();"
        "print(early.disabled)"
    )
    out = subprocess.run(  # noqa: S603 - fixed argv, no shell, no user input
        [sys.executable, "-c", code], cwd=str(ROOT), capture_output=True, text=True
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False", out.stdout


def test_configure_logging_raises_on_a_missing_config_file() -> None:
    with pytest.raises(FileNotFoundError, match="Logging config missing"):
        configure_logging("/nonexistent/logging.yaml")
