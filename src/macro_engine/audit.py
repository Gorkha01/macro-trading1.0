"""Append-only audit trail for model computations and thesis builds.

What this records, and why each field is there
---------------------------------------------
An institutional macro system must answer four questions about any number it
ever published:

1. **What was computed?** — model name, value, confidence, warnings.
2. **From what?** — the inputs, captured by value and by observation date.
3. **In what configuration?** — the parameters in force, so a later change to a
   coefficient does not retroactively alter the explanation of a past result.
4. **Under whose authority, and when?** — actor and timestamp.

The design consequence is that this table stores *inputs*, not input references.
Storing a pointer to a snapshot would be cheaper and would fail the audit test
the moment the snapshot is re-fetched: FRED revises, so the snapshot a pointer
resolves to today is not the data the model actually consumed. The audit record
must be self-contained, because its purpose is to survive the disappearance of
everything it refers to.

Why append-only
---------------
There is no update and no delete method on this ledger, and that is deliberate
rather than an omission. A mutable audit trail cannot attest to anything — the
party it is meant to hold accountable is exactly the party with write access. An
append-only table with a recorded ``actor`` is weak evidence, but it is
qualitatively different from no evidence.

Failure policy
--------------
``record()`` raises on failure rather than swallowing the exception. A model
computation that succeeds while its audit write silently fails produces a
result with no provenance, which is worse than a failed computation — the
failure is visible, the missing provenance is not.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import DateTime, Integer, String, Text, create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Mapped, Session, mapped_column

from macro_engine.models.contracts import ModelResult, utc_now
from macro_engine.settings_store import Base

__all__ = [
    "AuditLedger",
    "ModelComputationRecord",
    "ThesisBuildRecord",
    "get_audit_ledger",
    "reset_audit_ledger_cache",
]


class ModelComputationRecord(Base):
    """One model computation, recorded with its inputs and configuration.

    ``inputs_json`` holds the actual input values, not a reference. See the
    module docstring: FRED revisions mean a reference is not reproducible.
    """

    __tablename__ = "model_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Identity
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    country: Mapped[str] = mapped_column(String(8), nullable=False, index=True)

    # The result, denormalized so a reader needs no join and no code to read it.
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    interpretation: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[str] = mapped_column(Text, nullable=False)
    warnings_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    # Provenance
    inputs_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    inputs_used_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    config_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    # Attribution
    actor: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    duration_ms: Mapped[float | None] = mapped_column(nullable=True, default=None)


class ThesisBuildRecord(Base):
    """One ``build_us_macro_thesis()`` invocation.

    Kept separate from ``ModelComputationRecord`` because a thesis is the unit a
    human reviews and promotes, while a model computation is the unit an
    engineer debugs. They have different retention needs and different readers,
    and a thesis references many models — a parent row makes that relationship
    explicit instead of requiring a log correlation.
    """

    __tablename__ = "thesis_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    thesis_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    country: Mapped[str] = mapped_column(String(8), nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    convergence_classification: Mapped[str] = mapped_column(String(32), nullable=False)
    regime_state: Mapped[str] = mapped_column(String(64), nullable=False)

    model_count: Mapped[int] = mapped_column(Integer, nullable=False)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False)

    thesis_json: Mapped[str] = mapped_column(Text, nullable=False)
    config_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    actor: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    duration_ms: Mapped[float | None] = mapped_column(nullable=True, default=None)


class AuditEntry(BaseModel):
    """Result of an audit write, returned so a caller can surface the id."""

    model_config = ConfigDict(frozen=True)

    record_id: int
    correlation_id: str
    recorded_at: datetime


class AuditLedger:
    """Append-only writes and reads against the audit tables."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @classmethod
    def from_url(cls, database_url: str, *, echo: bool = False) -> AuditLedger:
        return cls(create_engine(database_url, echo=echo, future=True))

    def create_schema(self) -> None:
        """Idempotent schema creation; shares ``Base`` with the settings store."""
        Base.metadata.create_all(self._engine)

    def record_model(
        self,
        result: ModelResult,
        *,
        correlation_id: str,
        actor: str,
        inputs: dict[str, Any] | None = None,
        config_snapshot: dict[str, Any] | None = None,
        duration_ms: float | None = None,
    ) -> AuditEntry:
        """Record one model computation.

        ``duration_ms`` is stored rather than logged because it is queried:
        "which model got slower after the last release" is a question answered
        by a SQL aggregate, not by grepping log files.
        """
        if not correlation_id.strip():
            raise ValueError(
                "correlation_id is required — an audit row with no run context is unusable."
            )
        if not actor.strip():
            raise ValueError("actor is required — see settings_store for the same rule.")

        moment = utc_now()
        with Session(self._engine) as session:
            record = ModelComputationRecord(
                correlation_id=correlation_id,
                model_name=result.model_name,
                country=result.country,
                as_of=result.as_of,
                value_json=json.dumps(result.value, default=str),
                confidence=result.confidence,
                interpretation=result.interpretation,
                context=result.context,
                warnings_json=json.dumps(result.warnings),
                inputs_json=json.dumps(inputs or {}, default=str),
                inputs_used_json=json.dumps(result.inputs_used),
                config_snapshot_json=json.dumps(config_snapshot or {}, default=str),
                actor=actor,
                recorded_at=moment,
                duration_ms=duration_ms,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return AuditEntry(
                record_id=record.id, correlation_id=correlation_id, recorded_at=moment
            )

    def record_thesis(
        self,
        thesis: dict[str, Any],
        *,
        correlation_id: str,
        actor: str,
        model_count: int,
        config_snapshot: dict[str, Any] | None = None,
        duration_ms: float | None = None,
    ) -> AuditEntry:
        """Record one thesis build.

        Takes the thesis as a mapping rather than importing ``MacroThesis`` to
        avoid a circular import: ``thesis_layer`` imports the audit ledger, so
        the ledger must not import ``thesis_layer``.
        """
        if not correlation_id.strip() or not actor.strip():
            raise ValueError("correlation_id and actor are both required.")

        moment = utc_now()
        thesis_id = str(thesis.get("thesis_id", "unknown"))
        regime = thesis.get("regime") or {}
        warnings = thesis.get("warnings") or []

        with Session(self._engine) as session:
            record = ThesisBuildRecord(
                correlation_id=correlation_id,
                thesis_id=thesis_id,
                country=str(thesis.get("country", "us")),
                created_at=moment,
                status=str(thesis.get("status", "DRAFT")),
                convergence_classification=str(
                    thesis.get("convergence_classification", "NO_SIGNAL")
                ),
                regime_state=str(regime.get("state", "unknown")),
                model_count=model_count,
                warning_count=len(warnings),
                thesis_json=json.dumps(thesis, default=str),
                config_snapshot_json=json.dumps(config_snapshot or {}, default=str),
                actor=actor,
                duration_ms=duration_ms,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return AuditEntry(
                record_id=record.id, correlation_id=correlation_id, recorded_at=moment
            )

    def computations_for(self, correlation_id: str) -> list[dict[str, Any]]:
        """Every model computation belonging to one run, in completion order.

        This is the reconstruction primitive: given the ``correlation_id``
        printed alongside a thesis, this returns exactly the models that fed it,
        with the inputs each consumed.
        """
        with Session(self._engine) as session:
            rows = session.scalars(
                select(ModelComputationRecord)
                .where(ModelComputationRecord.correlation_id == correlation_id)
                .order_by(ModelComputationRecord.id)
            ).all()
            return [
                {
                    "id": row.id,
                    "model_name": row.model_name,
                    "value": json.loads(row.value_json),
                    "confidence": row.confidence,
                    "interpretation": row.interpretation,
                    "context": row.context,
                    "warnings": json.loads(row.warnings_json),
                    "inputs": json.loads(row.inputs_json),
                    "inputs_used": json.loads(row.inputs_used_json),
                    "as_of": row.as_of.isoformat(),
                    "recorded_at": row.recorded_at.isoformat(),
                    "actor": row.actor,
                    "duration_ms": row.duration_ms,
                }
                for row in rows
            ]

    def theses_for(self, correlation_id: str) -> list[dict[str, Any]]:
        """Thesis builds for one run."""
        with Session(self._engine) as session:
            rows = session.scalars(
                select(ThesisBuildRecord)
                .where(ThesisBuildRecord.correlation_id == correlation_id)
                .order_by(ThesisBuildRecord.id)
            ).all()
            return [
                {
                    "id": row.id,
                    "thesis_id": row.thesis_id,
                    "status": row.status,
                    "convergence": row.convergence_classification,
                    "regime_state": row.regime_state,
                    "model_count": row.model_count,
                    "warning_count": row.warning_count,
                    "thesis": json.loads(row.thesis_json),
                    "created_at": row.created_at.isoformat(),
                    "actor": row.actor,
                    "duration_ms": row.duration_ms,
                }
                for row in rows
            ]

    def model_latency_summary(self) -> list[dict[str, Any]]:
        """Mean and max duration per model.

        Exists so a performance regression is a query rather than an
        investigation. Returns rows only for computations that recorded a
        duration, so an older deployment's rows do not appear as zeros.
        """
        from sqlalchemy import func

        with Session(self._engine) as session:
            rows = session.execute(
                select(
                    ModelComputationRecord.model_name,
                    func.count(ModelComputationRecord.id),
                    func.avg(ModelComputationRecord.duration_ms),
                    func.max(ModelComputationRecord.duration_ms),
                )
                .where(ModelComputationRecord.duration_ms.is_not(None))
                .group_by(ModelComputationRecord.model_name)
                .order_by(func.avg(ModelComputationRecord.duration_ms).desc())
            ).all()
            return [
                {
                    "model_name": name,
                    "computation_count": count,
                    "mean_duration_ms": float(mean) if mean is not None else None,
                    "max_duration_ms": float(maximum) if maximum is not None else None,
                }
                for name, count, mean, maximum in rows
            ]


_ledger: AuditLedger | None = None


def get_audit_ledger() -> AuditLedger:
    """Process-level ledger built from ``MACRO_DATABASE_URL``."""
    global _ledger
    if _ledger is None:
        from macro_engine.deployment import get_deployment_config

        config = get_deployment_config()
        _ledger = AuditLedger.from_url(config.database_url, echo=config.database_echo_sql)
    return _ledger


def reset_audit_ledger_cache() -> None:
    """Drop the cached ledger. For tests."""
    global _ledger
    _ledger = None
