"""Tests for the enterprise infrastructure: deployment config, settings store, audit.

These cover the components the user's requirement added: environment-based
configuration, database-driven settings, structured logging, and audit trails.
Each is tested for the *failure* behaviour as well as the happy path, because
in each case the dangerous failure is a silent one — a missing required
variable defaulting, an unattributed settings change, an audit write that
fails without the caller noticing.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from macro_engine.audit import AuditLedger, reset_audit_ledger_cache
from macro_engine.data_layer.logging_json import JsonFormatter, _redact
from macro_engine.deployment import (
    AppEnvironment,
    MissingConfigurationError,
    get_deployment_config,
    reset_deployment_config_cache,
)
from macro_engine.models.contracts import ModelResult, utc_now
from macro_engine.settings_store import SettingsStore

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Isolate every test from the ambient environment and both caches.

    Without this, a developer with MACRO_ENVIRONMENT=production exported would
    see a different suite than CI, and the config cache would leak between tests
    in a way that makes ordering matter.
    """
    for name in (
        "MACRO_ENVIRONMENT",
        "MACRO_API_HOST",
        "MACRO_API_PORT",
        "MACRO_API_ROOT_PATH",
        "MACRO_API_DOCS_ENABLED",
        "MACRO_API_CORS_ORIGINS",
        "MACRO_API_KEY_REQUIRED",
        "MACRO_API_KEY_HASH",
        "MACRO_DATABASE_URL",
        "MACRO_DATABASE_ECHO_SQL",
        "OPENBB_API_URL",
        "MACRO_DATA_STORE_PATH",
        "MACRO_LOG_LEVEL",
        "MACRO_AUDIT_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)
    reset_deployment_config_cache()
    reset_audit_ledger_cache()
    yield
    reset_deployment_config_cache()
    reset_audit_ledger_cache()


# ---------------------------------------------------------------------------
# Deployment configuration
# ---------------------------------------------------------------------------


def test_development_defaults_resolve_without_any_environment() -> None:
    """A developer must be able to run the suite with nothing exported."""
    config = get_deployment_config()
    assert config.environment is AppEnvironment.DEVELOPMENT
    assert config.api_port == 8000
    assert config.api_host == "127.0.0.1"
    assert config.log_level == "INFO"


def test_environment_variable_overrides_the_yaml_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Precedence 1 over 2: the operator's deployment choice wins."""
    monkeypatch.setenv("MACRO_API_PORT", "9100")
    reset_deployment_config_cache()
    assert get_deployment_config().api_port == 9100


def test_production_without_required_variables_fails_fast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Precedence 3: a required setting with no safe default must raise.

    The alternative — quietly defaulting to a local SQLite file — would work in
    development and fail in production, deferring discovery of the
    misconfiguration to the moment it does the most damage.
    """
    monkeypatch.setenv("MACRO_ENVIRONMENT", "production")
    reset_deployment_config_cache()
    with pytest.raises(MissingConfigurationError) as exc_info:
        get_deployment_config()
    message = str(exc_info.value)
    assert "MACRO_DATABASE_URL" in message
    assert "MACRO_API_HOST" in message
    assert "MACRO_API_PORT" in message


def test_all_missing_production_requirements_are_reported_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One startup must surface the full set, not one variable per restart."""
    monkeypatch.setenv("MACRO_ENVIRONMENT", "production")
    reset_deployment_config_cache()
    with pytest.raises(MissingConfigurationError) as exc_info:
        get_deployment_config()
    # All three appear in a single message — see the test above, which asserts
    # each independently. This one asserts they co-occur.
    assert str(exc_info.value).count("MACRO_") >= 3


def test_production_with_complete_configuration_resolves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MACRO_ENVIRONMENT", "production")
    monkeypatch.setenv("MACRO_DATABASE_URL", "sqlite:///./prod.db")
    monkeypatch.setenv("MACRO_API_HOST", "0.0.0.0")  # noqa: S104 — test fixture
    monkeypatch.setenv("MACRO_API_PORT", "8080")
    # Production requires the key hash too: a production API reachable without
    # authentication is not a complete configuration, whatever else is set.
    monkeypatch.setenv("MACRO_API_KEY_HASH", "a" * 64)
    reset_deployment_config_cache()
    config = get_deployment_config()
    assert config.environment is AppEnvironment.PRODUCTION
    assert config.is_production is True
    assert config.api_port == 8080
    assert config.api_key_hash == "a" * 64


def test_api_key_required_without_a_hash_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A service requiring a key but holding none would reject everything or,
    far worse, accept everything. Caught at construction instead."""
    monkeypatch.setenv("MACRO_API_KEY_REQUIRED", "true")
    reset_deployment_config_cache()
    with pytest.raises(MissingConfigurationError, match="MACRO_API_KEY_HASH is unset"):
        get_deployment_config()


def test_api_key_hash_is_not_stored_in_plaintext() -> None:
    """The declaration must mark the hash secret so it is never logged."""
    from macro_engine.deployment import _VARIABLES

    assert _VARIABLES["MACRO_API_KEY_HASH"].is_secret is True


def test_invalid_boolean_is_refused_with_an_actionable_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MACRO_API_DOCS_ENABLED", "maybe")
    reset_deployment_config_cache()
    with pytest.raises(MissingConfigurationError, match="not a recognised boolean"):
        get_deployment_config()


def test_invalid_integer_is_refused_with_an_actionable_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`MACRO_API_PORT=eight_thousand` must not reach the socket binding."""
    monkeypatch.setenv("MACRO_API_PORT", "eight_thousand")
    reset_deployment_config_cache()
    with pytest.raises(MissingConfigurationError, match="not an integer"):
        get_deployment_config()


def test_invalid_log_level_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MACRO_LOG_LEVEL", "verbose")
    reset_deployment_config_cache()
    with pytest.raises(MissingConfigurationError, match="MACRO_LOG_LEVEL"):
        get_deployment_config()


def test_invalid_environment_name_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MACRO_ENVIRONMENT", "prod")
    reset_deployment_config_cache()
    with pytest.raises(MissingConfigurationError, match="MACRO_ENVIRONMENT"):
        get_deployment_config()


def test_cors_origins_parse_as_a_comma_separated_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MACRO_API_CORS_ORIGINS", "https://a.example, https://b.example ,")
    reset_deployment_config_cache()
    config = get_deployment_config()
    assert config.api_cors_origins == ["https://a.example", "https://b.example"]


def test_empty_cors_origins_means_same_origin_only() -> None:
    """An empty list, not a wildcard — the safe direction for the default."""
    assert get_deployment_config().api_cors_origins == []


def test_an_invalid_value_is_reported_rather_than_another_variables_absence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Field-at-a-time resolution reports whichever variable happens to be first.

    Before the preflight existed, a malformed ``MACRO_API_PORT`` was invisible
    behind an unset ``MACRO_API_KEY_HASH``: the operator fixed the key,
    restarted, and only then discovered the port. Both problems are in the
    environment at the same moment, so both belong in the same message.
    """
    monkeypatch.setenv("MACRO_API_PORT", "eight_thousand")
    reset_deployment_config_cache()
    with pytest.raises(MissingConfigurationError) as exc_info:
        get_deployment_config()
    message = str(exc_info.value)
    assert "MACRO_API_PORT" in message
    assert "not an integer" in message


def test_all_declared_variables_must_be_resolvable_in_development() -> None:
    """A declared variable with no default outside production is a config defect.

    This is the guard on ``_VARIABLES`` itself: adding a knob derived only from
    the environment, without a development default, would make the test suite
    unrunnable on a clean checkout. Asserting it here means the mistake is
    caught where it is introduced rather than by the next engineer.
    """
    config = get_deployment_config()
    assert config.environment is AppEnvironment.DEVELOPMENT
    # Reaching this line at all means every declared variable resolved.
    assert config.database_url  # non-empty, not None


def test_optional_secret_resolves_to_none_rather_than_raising() -> None:
    """Three states, not two: set, required-but-missing, and legitimately absent.

    A secret that only some deployments hold cannot be modelled with two
    states. Treating "absent" as a configuration defect would make a valid
    development environment unstartable; treating it as an empty string would
    make "not configured" indistinguishable from "configured to nothing".
    ``None`` is the only honest representation, and this test holds the
    resolver to it.
    """
    config = get_deployment_config()
    assert config.api_key_required is False
    assert config.api_key_hash is None


def test_optional_secret_is_still_required_where_declared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Optionality is per-environment, and production does not honour it."""
    monkeypatch.setenv("MACRO_ENVIRONMENT", "production")
    monkeypatch.setenv("MACRO_DATABASE_URL", "sqlite:///./prod.db")
    monkeypatch.setenv("MACRO_API_HOST", "127.0.0.1")
    monkeypatch.setenv("MACRO_API_PORT", "8080")
    reset_deployment_config_cache()
    with pytest.raises(MissingConfigurationError, match="MACRO_API_KEY_HASH"):
        get_deployment_config()


# ---------------------------------------------------------------------------
# Structured JSON logging
# ---------------------------------------------------------------------------


def _record(**extra: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="macro_engine.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="computed %s",
        args=("output_gap",),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_json_formatter_emits_one_parseable_object() -> None:
    payload = json.loads(JsonFormatter().format(_record()))
    assert payload["level"] == "INFO"
    assert payload["logger"] == "macro_engine.test"
    assert payload["message"] == "computed output_gap"
    assert "timestamp" in payload


def test_json_formatter_carries_the_audit_fields() -> None:
    """The four fields an audit trail needs to answer what/which-run/who/cost."""
    payload = json.loads(
        JsonFormatter().format(
            _record(
                audit_event="model.computed",
                correlation_id="run-123",
                actor="thesis-builder",
                duration_ms=4.2,
            )
        )
    )
    assert payload["audit_event"] == "model.computed"
    assert payload["correlation_id"] == "run-123"
    assert payload["actor"] == "thesis-builder"
    assert payload["duration_ms"] == 4.2


def test_redaction_applies_to_record_context_keys_not_only_values() -> None:
    """The distinction that the first implementation of this formatter got wrong.

    Redacting a value cannot catch a credential-shaped *key*, because the key is
    an ordinary string. ``extra={"api_key": "..."}`` is precisely how a secret
    reaches a log line, so the key itself must be tested. Asserted separately
    from the happy-path test above, because this is the failure mode that
    silently ships a secret rather than raising.
    """
    payload = json.loads(JsonFormatter().format(_record(session_token="abc")))  # noqa: S106
    assert payload["context"]["session_token"] == "***REDACTED***"  # noqa: S105
    # A structurally similar but non-credential key must survive.
    payload = json.loads(JsonFormatter().format(_record(session_count=3)))
    assert payload["context"]["session_count"] == 3


def test_redaction_matches_credential_fragments_not_only_exact_names() -> None:
    """``database_password`` carries a password and must be redacted.

    An equality-based key check misses every prefixed variant, which in practice
    is most of them — the credential is nearly always namespaced by what it
    belongs to.
    """
    payload = json.loads(
        JsonFormatter().format(_record(database_password="hunter2"))  # noqa: S106
    )
    assert payload["context"]["database_password"] == "***REDACTED***"  # noqa: S105


def test_json_formatter_redacts_credential_shaped_keys() -> None:
    """A logger is the easiest place to leak a secret, so redaction is tested."""
    payload = json.loads(
        JsonFormatter().format(_record(api_key="sk-live-abc123", safe_field="visible"))
    )
    assert payload["context"]["api_key"] == "***REDACTED***"
    assert payload["context"]["safe_field"] == "visible"


def test_redaction_reaches_nested_structures() -> None:
    """A credential inside a nested config dump must be caught too."""
    nested = {"outer": {"database_password": "hunter2", "host": "db.internal"}}
    redacted = _redact(nested)
    assert redacted["outer"]["database_password"] == "***REDACTED***"  # noqa: S105
    assert redacted["outer"]["host"] == "db.internal"


def test_redaction_is_case_insensitive_on_keys() -> None:
    assert _redact({"API_KEY": "abc"})["API_KEY"] == "***REDACTED***"
    assert _redact({"Authorization": "Bearer x"})["Authorization"] == "***REDACTED***"


def test_redaction_is_depth_limited() -> None:
    """A self-referential structure must not recurse to the stack limit."""
    cyclic: dict[str, object] = {}
    cyclic["self"] = cyclic
    result = _redact(cyclic)  # must not raise RecursionError
    assert isinstance(result, dict)


def test_long_strings_are_truncated() -> None:
    """A multi-kilobyte string in a log line is usually an accident."""
    payload = json.loads(JsonFormatter().format(_record(blob="x" * 5000)))
    assert "truncated" in payload["context"]["blob"]


def test_location_is_emitted_only_at_warning_and_above() -> None:
    """Location is triage information; on a routine INFO line it is noise."""
    info_payload = json.loads(JsonFormatter().format(_record()))
    assert "location" not in info_payload

    warning_record = _record()
    warning_record.levelno = logging.WARNING
    warning_record.levelname = "WARNING"
    warning_payload = json.loads(JsonFormatter().format(warning_record))
    assert "location" in warning_payload
    assert "function" in warning_payload


def test_exception_records_capture_type_message_and_traceback() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = logging.LogRecord(
            name="macro_engine.test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="failed",
            args=(),
            exc_info=sys.exc_info(),
        )
    payload = json.loads(JsonFormatter().format(record))
    assert payload["exception"]["type"] == "ValueError"
    assert payload["exception"]["message"] == "boom"
    assert any("ValueError: boom" in line for line in payload["exception"]["traceback"])


def test_formatter_survives_an_unserialisable_context_value() -> None:
    """A logger that can throw is worse than one that loses type fidelity."""
    payload = json.loads(JsonFormatter().format(_record(moment=datetime.now(UTC))))
    assert "moment" in payload["context"]


# ---------------------------------------------------------------------------
# Settings store — bitemporal revisions
# ---------------------------------------------------------------------------


@pytest.fixture
def store() -> SettingsStore:
    """An in-memory store, created fresh per test."""
    settings_store = SettingsStore.from_url("sqlite:///:memory:")
    settings_store.create_schema()
    return settings_store


def test_unset_setting_returns_none_rather_than_a_default(store: SettingsStore) -> None:
    """The caller decides the fallback; a silent default would mask an
    unset production setting."""
    assert store.get("policy", "r_star") is None


def test_set_then_get_round_trips(store: SettingsStore) -> None:
    store.set(
        "policy",
        "r_star",
        0.65,
        value_type="float",
        actor="alice",
        reason="updated to the latest HLW estimate",
    )
    snapshot = store.get("policy", "r_star")
    assert snapshot is not None
    assert snapshot.value == pytest.approx(0.65)
    assert snapshot.source == "database"
    assert snapshot.revision == 1
    assert snapshot.changed_by == "alice"


def test_update_creates_a_new_revision_and_supersedes_the_old(store: SettingsStore) -> None:
    """History is preserved, not overwritten."""
    store.set("policy", "r_star", 0.5, value_type="float", actor="alice", reason="initial")
    store.set("policy", "r_star", 0.65, value_type="float", actor="bob", reason="HLW revision")

    current = store.get("policy", "r_star")
    assert current is not None
    assert current.value == pytest.approx(0.65)
    assert current.revision == 2
    assert current.changed_by == "bob"

    history = store.history("policy", "r_star")
    assert len(history) == 2
    assert [entry.revision for entry in history] == [2, 1]
    assert history[1].value == pytest.approx(0.5)


def test_value_at_reconstructs_a_past_configuration(store: SettingsStore) -> None:
    """The question an audit trail exists to answer: what was this value then?

    Note the assertion target. An earlier version of this test captured
    ``utc_now()`` *between* the two writes and queried with that instant plus a
    millisecond, which quietly assumed the wall clock and the store's write
    timestamps were the same clock at the same resolution. They are not
    reliably so — the store bumps its timestamp to keep revisions ordered — and
    the test failed for a reason that had nothing to do with the behaviour it
    meant to check. Asking the store for its own history is the honest way to
    obtain a genuine historical instant.
    """
    store.set("risk", "limit", 100.0, value_type="float", actor="alice", reason="initial")
    store.set("risk", "limit", 80.0, value_type="float", actor="bob", reason="de-risked")

    first = store.history("risk", "limit")[-1]  # oldest revision
    second = store.history("risk", "limit")[0]  # newest revision
    assert first.revision == 1
    assert second.revision == 2

    # At the instant revision 1 was created, revision 1 is what was in force.
    at_first = store.value_at("risk", "limit", moment=first.revision_instant())
    assert at_first is not None
    assert at_first.value == pytest.approx(100.0)
    assert at_first.revision == 1

    # At the instant revision 2 landed, revision 2 is in force — the interval
    # is half-open, so the boundary belongs to the incoming revision, not the
    # outgoing one.
    at_second = store.value_at("risk", "limit", moment=second.revision_instant())
    assert at_second is not None
    assert at_second.value == pytest.approx(80.0)
    assert at_second.revision == 2


def test_value_at_returns_none_before_any_write(store: SettingsStore) -> None:
    """Absence is ``None``, never a default — the caller must decide."""
    store.set("risk", "limit", 100.0, value_type="float", actor="alice", reason="initial")
    created = store.history("risk", "limit")[0].revision_instant()
    assert store.value_at("risk", "limit", moment=created - timedelta(days=1)) is None


def test_consecutive_writes_are_strictly_ordered(store: SettingsStore) -> None:
    """Revisions must be totally ordered in time, not merely in revision number.

    A plain loop of writes does *not* prove this: a SQLite round-trip costs more
    than a microsecond, so the wall clock advances naturally and the guard being
    tested never fires. That was discovered by removing the guard and watching
    this test still pass — a test that cannot fail is not a test. The collision
    is therefore injected: the clock is frozen so that every write observes the
    same instant, which is exactly the degenerate case a monotonic store must
    survive.
    """
    frozen = utc_now()
    with patch("macro_engine.settings_store.utc_now", return_value=frozen):
        for index in range(10):
            store.set(
                "risk",
                "limit",
                float(index),
                value_type="float",
                actor="alice",
                reason="frozen clock",
            )

    history = store.history("risk", "limit")
    assert len(history) == 10
    timestamps = [entry.revision_instant() for entry in reversed(history)]

    # Strictly increasing with no duplicates, even though the clock never moved.
    assert timestamps == sorted(timestamps)
    assert len(set(timestamps)) == 10

    # And every intermediate value is reconstructible at its own instant. This
    # is the property that matters: the history must exist in time, not merely
    # as rows.
    for index, entry in enumerate(reversed(history)):
        restored = store.value_at("risk", "limit", moment=entry.revision_instant())
        assert restored is not None
        assert restored.value == pytest.approx(float(index))


def test_every_mutation_requires_an_actor(store: SettingsStore) -> None:
    """An unattributed change to a risk parameter is indistinguishable from
    tampering, so the schema refuses to record one."""
    with pytest.raises(ValueError, match="actor is required"):
        store.set("risk", "limit", 1.0, value_type="float", actor="  ", reason="why")


def test_every_mutation_requires_a_reason(store: SettingsStore) -> None:
    with pytest.raises(ValueError, match="reason is required"):
        store.set("risk", "limit", 1.0, value_type="float", actor="alice", reason="")


def test_unknown_value_type_is_refused(store: SettingsStore) -> None:
    with pytest.raises(ValueError, match="value_type"):
        store.set("risk", "limit", 1.0, value_type="decimal", actor="a", reason="r")


def test_boolean_values_round_trip(store: SettingsStore) -> None:
    store.set("feature", "enabled", True, value_type="bool", actor="alice", reason="rollout")
    snapshot = store.get("feature", "enabled")
    assert snapshot is not None
    assert snapshot.value is True


def test_json_values_round_trip(store: SettingsStore) -> None:
    payload = {"tiers": [{"drawdown": 10, "reduction": 50}]}
    store.set(
        "risk",
        "drawdown_thresholds",
        payload,
        value_type="json",
        actor="alice",
        reason="pre-committed mechanical rules",
    )
    snapshot = store.get("risk", "drawdown_thresholds")
    assert snapshot is not None
    assert snapshot.value == payload


def test_retire_keeps_the_row_and_marks_it_inactive(store: SettingsStore) -> None:
    """A literal delete would make any past thesis unexplainable."""
    store.set("risk", "limit", 100.0, value_type="float", actor="alice", reason="initial")
    assert store.get("risk", "limit") is not None

    assert store.delete("risk", "limit", actor="bob", reason="withdrawn") is True
    assert store.get("risk", "limit") is None
    # The history survives, which is the point.
    assert len(store.history("risk", "limit")) == 1


def test_retire_of_a_nonexistent_setting_returns_false(store: SettingsStore) -> None:
    assert store.delete("nothing", "here", actor="a", reason="r") is False


def test_retire_requires_actor_and_reason(store: SettingsStore) -> None:
    store.set("risk", "limit", 1.0, value_type="float", actor="a", reason="r")
    with pytest.raises(ValueError, match="actor and reason"):
        store.delete("risk", "limit", actor="", reason="r")


# ---------------------------------------------------------------------------
# Audit ledger
# ---------------------------------------------------------------------------


@pytest.fixture
def ledger() -> AuditLedger:
    audit_ledger = AuditLedger.from_url("sqlite:///:memory:")
    audit_ledger.create_schema()
    return audit_ledger


def _sample_result() -> ModelResult:
    from macro_engine.config import get_settings

    return ModelResult(
        model_name="output_gap",
        country="us",
        as_of=utc_now(),
        value=0.83,
        confidence=get_settings().scalar("confidence.base"),
        interpretation="Output gap: +0.83% (above potential)",
        context="same-quarter pair at 2026-04-01",
        inputs_used=["actual_gdp", "potential_gdp"],
        warnings=["Potential GDP is an estimate"],
    )


def test_model_computation_is_recorded_with_its_inputs(ledger: AuditLedger) -> None:
    entry = ledger.record_model(
        _sample_result(),
        correlation_id="run-abc",
        actor="thesis-builder",
        inputs={"actual_gdp": 24269.613, "potential_gdp": 24070.9386484},
        duration_ms=3.1,
    )
    assert entry.record_id > 0
    assert entry.correlation_id == "run-abc"


def test_recorded_inputs_are_retrievable_by_value(ledger: AuditLedger) -> None:
    """The reconstruction primitive: given a run id, get exactly what fed it.

    Inputs are stored by value rather than by reference, because FRED revisions
    mean a snapshot pointer resolves to different data later.
    """
    ledger.record_model(
        _sample_result(),
        correlation_id="run-abc",
        actor="thesis-builder",
        inputs={"actual_gdp": 24269.613, "potential_gdp": 24070.9386484},
    )
    computations = ledger.computations_for("run-abc")
    assert len(computations) == 1
    assert computations[0]["inputs"]["actual_gdp"] == pytest.approx(24269.613)
    assert computations[0]["model_name"] == "output_gap"
    assert computations[0]["warnings"] == ["Potential GDP is an estimate"]


def test_correlation_id_separates_concurrent_runs(ledger: AuditLedger) -> None:
    """Without this, a 20-model build interleaves and a failure cannot be
    attributed to the run that produced it."""
    ledger.record_model(_sample_result(), correlation_id="run-1", actor="a")
    ledger.record_model(_sample_result(), correlation_id="run-2", actor="a")
    ledger.record_model(_sample_result(), correlation_id="run-1", actor="a")

    assert len(ledger.computations_for("run-1")) == 2
    assert len(ledger.computations_for("run-2")) == 1


def test_audit_write_requires_a_correlation_id(ledger: AuditLedger) -> None:
    with pytest.raises(ValueError, match="correlation_id is required"):
        ledger.record_model(_sample_result(), correlation_id="  ", actor="a")


def test_audit_write_requires_an_actor(ledger: AuditLedger) -> None:
    with pytest.raises(ValueError, match="actor is required"):
        ledger.record_model(_sample_result(), correlation_id="run", actor="")


def test_thesis_build_is_recorded_and_retrievable(ledger: AuditLedger) -> None:
    thesis = {
        "thesis_id": "us-2026-09-a1",
        "country": "us",
        "status": "DRAFT",
        "convergence_classification": "HIGH",
        "regime": {"state": "disinflation", "confidence": 0.5},
        "warnings": ["r* is unobservable", "Potential GDP is an estimate"],
    }
    entry = ledger.record_thesis(
        thesis, correlation_id="run-xyz", actor="thesis-builder", model_count=9
    )
    assert entry.record_id > 0

    theses = ledger.theses_for("run-xyz")
    assert len(theses) == 1
    assert theses[0]["thesis_id"] == "us-2026-09-a1"
    assert theses[0]["regime_state"] == "disinflation"
    assert theses[0]["model_count"] == 9
    assert theses[0]["warning_count"] == 2


def test_latency_summary_exposes_per_model_timings(ledger: AuditLedger) -> None:
    """A performance regression should be a query, not an investigation."""
    ledger.record_model(_sample_result(), correlation_id="r1", actor="a", duration_ms=10.0)
    ledger.record_model(_sample_result(), correlation_id="r2", actor="a", duration_ms=30.0)
    summary = ledger.model_latency_summary()
    assert len(summary) == 1
    assert summary[0]["model_name"] == "output_gap"
    assert summary[0]["computation_count"] == 2
    assert summary[0]["mean_duration_ms"] == pytest.approx(20.0)
    assert summary[0]["max_duration_ms"] == pytest.approx(30.0)


def test_latency_summary_ignores_rows_without_a_duration(ledger: AuditLedger) -> None:
    """An older deployment's rows must not appear as zeros and drag the mean."""
    ledger.record_model(_sample_result(), correlation_id="r1", actor="a")
    ledger.record_model(_sample_result(), correlation_id="r2", actor="a", duration_ms=10.0)
    summary = ledger.model_latency_summary()
    assert summary[0]["computation_count"] == 1
    assert summary[0]["mean_duration_ms"] == pytest.approx(10.0)


def test_audit_ledger_has_no_update_or_delete_method(ledger: AuditLedger) -> None:
    """Append-only by construction, asserted so a future edit cannot quietly
    add a mutation path and call it a convenience.

    A mutable audit trail cannot attest to anything: the party it is meant to
    hold accountable is exactly the party with write access.
    """
    for forbidden in ("update", "delete", "remove"):
        assert not hasattr(ledger, forbidden), (
            f"AuditLedger must not expose '{forbidden}' — the ledger is append-only"
        )


# ---------------------------------------------------------------------------
# The config-accessor trap, guarded structurally
# ---------------------------------------------------------------------------
#
# Models read calibration values through ``.property`` accessors, never the raw
# ``CalibratedValue`` envelope. Comparing an envelope raises
# ``TypeError: '<' not supported between 'float' and 'CalibratedValue'`` — which
# is loud, but only at the moment the branch executes, so a branch no test
# covers survives until real data reaches it.
#
# The same mistake has now been made three times (`low_wage_decline_pct`,
# `eci_divergence_pp`, `shelter_converged_tolerance_pp`), each time costing a
# debugging cycle on a function that was otherwise finished. The guard below
# makes the class detectable at rest rather than at runtime: every
# ``CalibratedValue`` leaf anywhere in the settings tree must have at least one
# **numeric** sibling property, so a model always has an accessor to use.


def _iter_calibrated_leaves(
    node: object,
    path: str = "",
) -> list[str]:
    """Every ``{value, calibration_status}`` leaf in the settings tree, by path.

    ``model_fields`` is read from the **class**, not the instance — pydantic
    2.11 deprecates the instance form and removes it in v3.
    """
    from macro_engine.config import CalibratedValue

    if isinstance(node, CalibratedValue):
        return [path]
    found: list[str] = []
    fields = getattr(type(node), "model_fields", None)
    if isinstance(fields, dict):
        for name in fields:
            found.extend(
                _iter_calibrated_leaves(getattr(node, name), f"{path}.{name}" if path else name)
            )
    return found


def _accessor_candidates(parent: object) -> list[str]:
    """Property names declared on the settings class, without touching internals.

    Two exclusions, both learned by measurement:

    * ``dir(type(parent))`` reaches pydantic's machinery, so the MRO's class
      dictionaries are walked instead — only properties someone declared.
    * Dunder names are skipped because pydantic itself defines ``__fields__`` and
      ``__fields_set__`` *as deprecated properties*, which the walk would
      otherwise evaluate and warn on 73 times per run. They are not config
      accessors and no model should be reading them.
    """
    names: set[str] = set()
    for klass in type(parent).__mro__:
        for name, attribute in vars(klass).items():
            if isinstance(attribute, property) and not name.startswith("__"):
                names.add(name)
    return sorted(names)


def _numeric_properties_on_parent(config: object, leaf_name: str) -> list[str]:
    """Property names on ``config`` whose value is a plain number.

    Only properties are considered: a raw ``CalibratedValue`` field is the
    envelope the models must not use, and a string property cannot participate
    in an arithmetic comparison.

    No exception handling: these are this project's own settings classes, so a
    property that raises is a defect worth surfacing here rather than a case to
    swallow. An earlier version caught ``Exception`` and ``continue``d, which
    ruff correctly flagged (``S112``) — a silent skip would have made a broken
    accessor look like a missing one.
    """
    parent = config
    for part in leaf_name.split(".")[:-1]:
        parent = getattr(parent, part)
    names: list[str] = []
    for attr in _accessor_candidates(parent):
        value = getattr(parent, attr)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            names.append(attr)
    return names


def _scalar_readable(config: object, leaf_name: str) -> bool:
    """Whether ``Settings.scalar("a.b.c")`` returns a plain number for this leaf.

    ``scalar()`` accepts BOTH spellings that appear in ``settings.yaml`` — a raw
    mapping and a validated ``CalibratedValue`` — which is what makes it a
    legitimate alternative to a hand-written property accessor. Read this way an
    envelope can never be compared by accident, because the method unwraps it.

    A ``KeyError``/``ValueError`` from ``scalar()`` on a path that does not
    resolve means "not readable", which is the false branch of this predicate —
    so the narrow exception set is caught and reported as ``False`` rather than
    hidden behind a broad ``except``.
    """
    from macro_engine.config import Settings

    if not isinstance(config, Settings):
        return False
    try:
        return isinstance(config.scalar(leaf_name), (int, float))
    except (KeyError, ValueError, TypeError):
        return False


def test_every_calibrated_leaf_has_a_numeric_property_accessor() -> None:
    """Every envelope must be readable as a plain number by SOME stated route.

    There are two legitimate routes and the guard accepts either:

    * a numeric ``.property`` on the owning settings class, or
    * ``Settings.scalar("path.to.leaf")``, which unwraps the envelope itself.

    What neither route permits is a model reaching for the envelope directly,
    because that is the one spelling that raises ``TypeError`` only when the
    branch executes. This test ensures a readable route exists; the mutation
    sweep's "threshold from a literal instead of config" entry covers whether the
    model actually takes it.

    Nineteen leaves were unreadable by property when this guard was first
    written and were already being read through ``scalar()`` — which is why the
    guard checks both routes rather than mandating properties.
    """
    from macro_engine.config import get_settings

    settings = get_settings()
    leaves = _iter_calibrated_leaves(settings)
    assert leaves, "the settings tree should contain CalibratedValue leaves"

    unreadable = [
        leaf
        for leaf in leaves
        if not _numeric_properties_on_parent(settings, leaf)
        and not _scalar_readable(settings, leaf)
    ]
    assert not unreadable, (
        "these config leaves are CalibratedValue envelopes reachable by neither a "
        "numeric property nor Settings.scalar(), so any model consuming them must "
        "unwrap the envelope by hand — liable to be compared directly and raise "
        "TypeError only when that branch executes:\n  " + "\n  ".join(unreadable)
    )


def test_calibrated_values_do_not_support_arithmetic_directly() -> None:
    """Documents WHY the accessor rule exists.

    If ``CalibratedValue`` ever gained comparison operators, this test would
    fail and the rule above could be relaxed deliberately — rather than the
    guard silently becoming unnecessary or, worse, the envelope silently
    becoming comparable in a way that hides which field was compared.
    """
    from macro_engine.config import CalibratedValue

    envelope = CalibratedValue(value=0.3, calibration_status="conventional")
    with pytest.raises(TypeError):
        _ = envelope < 1.0  # type: ignore[operator]
    with pytest.raises(TypeError):
        _ = envelope <= 1.0  # type: ignore[operator]


# ---------------------------------------------------------------------------
# The property-vs-field structural guard (D-035, owed since the fifth hit)
# ---------------------------------------------------------------------------


def _settings_classes() -> list[type]:
    """Every ``BaseModel`` subclass declared in ``macro_engine.config``.

    Collected from the module's own namespace rather than by walking
    ``Settings.model_fields`` recursively, because the defect this guard exists
    for is that a property and a field can share a name — and a class that is
    currently *unreferenced* by ``Settings`` is exactly the kind of class that
    would carry an unnoticed collision until the day it is wired in.
    """
    from pydantic import BaseModel

    from macro_engine import config as config_module

    found: list[type] = []
    for name in dir(config_module):
        obj = getattr(config_module, name)
        if (
            isinstance(obj, type)
            and issubclass(obj, BaseModel)
            and obj is not BaseModel
            and obj.__module__ == config_module.__name__
        ):
            found.append(obj)
    return found


def _declared_property_names(klass: type) -> list[str]:
    """Property names visible in the class body, walking the MRO.

    Used only for the *healthy*-model assertion and for documentation. It CANNOT
    be used to detect the collision: pydantic consumes a property that shares a
    field's name and **removes it from the class dict** while storing the
    property object as the field's default, so by the time the class exists the
    property is no longer discoverable as a ``property`` — see
    ``_fields_holding_a_property_object`` for the signature that survives.
    """
    names: set[str] = set()
    for base in klass.__mro__:
        for name, attribute in vars(base).items():
            if isinstance(attribute, property) and not name.startswith("__"):
                names.add(name)
    return sorted(names)


def _fields_holding_a_property_object(klass: type) -> list[str]:
    """Fields whose stored DEFAULT is a ``property`` object.

    This is the only reliable signature of the collision, and it is a direct
    observation rather than a name-accounting coincidence. Measured against
    pydantic 2.13:

        class _After(BaseModel):
            threshold: float = 1.0

            @property
            def threshold(self) -> float: ...
            # -> _After.model_fields["threshold"].default is the property object
            # -> "threshold" is GONE from vars(_After)
            # -> _After().threshold returns the property object, not a float

    Pydantic does not simply let the property "win". It absorbs the descriptor as
    the field default and deletes the class attribute, so:

    * a name-intersection check finds NOTHING (the property is no longer in the
      class dict), which is why an earlier version of this guard was inert;
    * the field keeps its declared type annotation while holding a non-value;
    * and depending on declaration order the accessor either returns a
      descriptor object or a stale scalar forever.

    None of that raises at import, at class definition, or at validation.
    """
    fields = getattr(klass, "model_fields", None)
    if not isinstance(fields, dict):
        return []
    found: list[str] = []
    for name, info in fields.items():
        if isinstance(getattr(info, "default", None), property):
            found.append(name)
    return sorted(found)


def _fields_shadowed_by_an_annotation_mismatch(klass: type) -> list[str]:
    """Fields declared as an envelope but holding a real value of the wrong type.

    A second, independent net for the same defect after a partial fix: if a
    collision was resolved by renaming the *property* but the field kept a
    descriptor or a scalar as its default, the field is annotated
    ``CalibratedValue`` while holding something else, and the model that reads
    it gets a ``TypeError`` only on the branch that executes.

    Legitimate states are excluded explicitly, because getting this wrong makes
    the check unusable:

    * a **required** field has no default at all (``PydanticUndefined``), which
      is correct and by far the most common shape in this config;
    * ``None`` is a legal declared default and means "absent".

    Only a field that is **not required**, has a default that is **not** ``None``,
    and is **not** a ``CalibratedValue`` is reported.
    """
    from macro_engine.config import CalibratedValue

    fields = getattr(klass, "model_fields", None)
    if not isinstance(fields, dict):
        return []
    bad: list[str] = []
    for name, info in fields.items():
        annotation = getattr(info, "annotation", None)
        expects_envelope = annotation is CalibratedValue or (
            isinstance(annotation, type) and issubclass(annotation, CalibratedValue)
        )
        if not expects_envelope:
            continue
        if info.is_required():
            continue
        default = getattr(info, "default", None)
        if default is None or isinstance(default, CalibratedValue):
            continue
        bad.append(name)
    return sorted(bad)


def test_no_settings_model_declares_a_field_and_a_property_of_the_same_name() -> None:
    """The structural guard for a defect hit FIVE times (D-035).

    Three checks, because the defect has more than one surviving signature —
    see ``_fields_holding_a_property_object`` for the measured mechanism. The
    primary one is the field-default-is-a-descriptor test; a name-intersection
    test alone is provably blind to it, which an earlier version of this guard
    demonstrated by passing on a deliberately broken model.

    The guard is verified against broken models by
    ``test_the_collision_guard_catches_a_deliberately_broken_model`` below, so
    it cannot pass by being inert.
    """
    problems: list[str] = []
    for klass in _settings_classes():
        for name in _fields_holding_a_property_object(klass):
            problems.append(
                f"{klass.__name__}.{name} — field default is a `property` object, "
                f"so the field does not hold a value and the property never runs"
            )
        for name in _fields_shadowed_by_an_annotation_mismatch(klass):
            problems.append(
                f"{klass.__name__}.{name} — declared as a CalibratedValue but "
                f"holding something else; a shadowed declaration usually leaves "
                f"a descriptor or a stale scalar behind"
            )
    assert not problems, (
        "these settings models are hit by the property-vs-field collision. It "
        "raises nothing at import, definition or validation time, and the "
        "accessor either returns a descriptor object or a stale constant "
        "forever. Rename the field or the property:\n  " + "\n  ".join(problems)
    )


def test_the_collision_guard_catches_a_deliberately_broken_model() -> None:
    """Proves the guard above is load-bearing rather than vacuously true.

    Without this, a bug in the detection would make the guard pass on every
    codebase, including a broken one. The only way to tell "no collisions
    exist" apart from "the check does not work" is to build a model that HAS
    the defect and assert the guard reports it.

    **This test has already earned its place once.** The first version of this
    guard intersected ``model_fields`` names with ``property`` objects found in
    ``vars(klass)``. Against the deliberately broken model below that
    intersection was EMPTY — because pydantic consumes the property and deletes
    it from the class dict — so the guard would have passed on a real
    collision. Asserting the broken case is what exposed it.
    """
    from pydantic import BaseModel

    # ``F811``/``no-redef`` are silenced deliberately: the shadowing redefinition
    # below IS the defect this test exists to detect. "Fixing" it by renaming
    # either declaration would delete the test, and then the guard would be free
    # to regress to its first, blind version without anything noticing.
    class _PropertyAfterField(BaseModel):
        threshold: float = 1.0

        @property  # type: ignore[no-redef]
        def threshold(self) -> float:  # noqa: F811
            """Reuses the field name — the defect under test."""
            return 2.0

    # The surviving signature: the field's default IS the property object.
    assert _fields_holding_a_property_object(_PropertyAfterField) == ["threshold"]
    # And the class dict no longer contains it as a property — which is exactly
    # why a name-intersection guard is blind to this.
    assert vars(_PropertyAfterField).get("threshold", None) is None
    assert isinstance(_PropertyAfterField().threshold, property)


def test_a_healthy_settings_model_is_not_flagged() -> None:
    """The guard must not fire on the ordinary field-plus-property case.

    ``ConfidenceSettings`` has eight fields and two properties whose names do
    not collide, all eight fields holding real envelopes. A guard that reported
    those would be unusable, and the temptation on the next failure would be to
    weaken it rather than fix the declaration.
    """
    from macro_engine.config import ConfidenceSettings

    assert _fields_holding_a_property_object(ConfidenceSettings) == []
    assert _fields_shadowed_by_an_annotation_mismatch(ConfidenceSettings) == []
    # It does have properties, so the guard is not passing because there are none.
    assert set(_declared_property_names(ConfidenceSettings)) >= {"values"}


def test_every_settings_class_was_actually_walked() -> None:
    """A guard that walks zero classes passes for the wrong reason.

    ``_settings_classes`` reflects over a module namespace, which is easy to
    get wrong (a wrong module object, a filter that excludes everything). This
    asserts the walk found a substantial number of classes and that a known one
    is among them.
    """
    classes = _settings_classes()
    names = {klass.__name__ for klass in classes}
    from macro_engine.config import ConfidenceSettings

    assert len(classes) >= 20, f"only found {len(classes)} settings classes: {sorted(names)}"
    assert ConfidenceSettings in classes


# ---------------------------------------------------------------------------
# D-075: record_thesis must NOT invent defaults for missing fields.
#
# The sibling method `record_model` takes a typed `ModelResult` and reads
# attributes directly, so a missing field is impossible. `record_thesis` takes
# an untyped `dict` and previously substituted "unknown" / "us" / "DRAFT" /
# "NO_SIGNAL" for absent keys — the exact `missing -> invented default`
# conversion D-015 forbids for the audit trail:
#
#   "A model computation that succeeds while its audit write silently fails
#    produces a result with no provenance — worse than a failed computation."
#
# An audit row asserting `status="DRAFT"` when the thesis carried no status is
# worse than no row: it is a fabricated provenance fact that a reader cannot
# distinguish from a real one.
# ---------------------------------------------------------------------------


def test_record_thesis_refuses_a_thesis_missing_required_fields(
    ledger: AuditLedger,
) -> None:
    """RED before the fix: absent `status` was silently recorded as "DRAFT"."""
    thesis = {
        "thesis_id": "us-2026-09-b1",
        "country": "us",
        # no `status`, no `convergence_classification`, no `regime`
    }
    with pytest.raises(ValueError, match="status"):
        ledger.record_thesis(
            thesis, correlation_id="run-missing", actor="thesis-builder", model_count=9
        )


def test_record_thesis_does_not_invent_a_country(ledger: AuditLedger) -> None:
    """RED before the fix: absent `country` was silently recorded as "us"."""
    thesis = {
        "thesis_id": "us-2026-09-b2",
        "status": "DRAFT",
        "convergence_classification": "NO_SIGNAL",
        "regime": {"state": "disinflation"},
        # no `country`
    }
    with pytest.raises(ValueError, match="country"):
        ledger.record_thesis(
            thesis, correlation_id="run-nocountry", actor="thesis-builder", model_count=9
        )


def test_record_thesis_does_not_invent_a_thesis_id(ledger: AuditLedger) -> None:
    """RED before the fix: absent `thesis_id` was silently recorded as "unknown"."""
    thesis = {
        "country": "us",
        "status": "DRAFT",
        "convergence_classification": "NO_SIGNAL",
        "regime": {"state": "disinflation"},
    }
    with pytest.raises(ValueError, match="thesis_id"):
        ledger.record_thesis(
            thesis, correlation_id="run-noid", actor="thesis-builder", model_count=9
        )


def test_record_thesis_still_records_a_complete_thesis(ledger: AuditLedger) -> None:
    """GREEN guard: the refusal must not break the legitimate path."""
    thesis = {
        "thesis_id": "us-2026-09-b3",
        "country": "us",
        "status": "WATCH",
        "convergence_classification": "NO_SIGNAL",
        "regime": {"state": "disinflation", "confidence": 0.5},
        "warnings": ["gap inside dispersion"],
    }
    entry = ledger.record_thesis(
        thesis, correlation_id="run-complete", actor="thesis-builder", model_count=9
    )
    assert entry.record_id > 0
    stored = ledger.theses_for("run-complete")
    assert stored[0]["status"] == "WATCH"
    # `country` is not a projected column; it lives in the stored payload, which
    # is the point of storing the thesis by value (D-015).
    assert stored[0]["thesis"]["country"] == "us"
