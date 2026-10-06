"""Database-backed settings with an append-only change history.

Why a settings store exists at all
----------------------------------
``config/settings.yaml`` is the right home for analytical parameters: they are
reviewed in a pull request, diffed, and versioned alongside the code that reads
them. That is the strongest possible governance for values that shape a result.

It is the wrong home for *operational* settings — a threshold being tuned during
an incident, a feature enabled for one desk, a circuit breaker tripped. Editing
a committed YAML file and redeploying to change a number is too slow for those,
and using environment variables leaves no history of who changed what.

So this module holds the third category: settings that must change **without a
deploy**, where the change itself must be **attributable and reversible**. That
is the entire justification. It is not a replacement for ``settings.yaml``, and
``resolve_setting`` makes the precedence explicit rather than leaving a reader
to guess which source won.

The audit requirement
---------------------
An institutional system must be able to answer: *what was this value on the day
that thesis was produced, and who changed it?* Two design consequences follow,
and both are load-bearing:

1. **Update, never delete.** ``set()`` writes a new revision and marks the prior
   one superseded. Deleting a row would make a past thesis unexplainable.
2. **Every write records an actor and a reason.** Not optional, not defaulted.
   An unattributed change to a risk parameter is indistinguishable from
   tampering, so the schema refuses to record one.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    func,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from macro_engine.models.contracts import utc_now

__all__ = [
    "Base",
    "SettingChange",
    "SettingRecord",
    "SettingValueType",
    "SettingsStore",
    "get_settings_store",
]


class Base(DeclarativeBase):
    """Declarative base for the settings and audit tables."""


class SettingValueType(StrEnum):
    """The accepted ``SettingRecord.value_type`` vocabulary, and its single definition.

    MEASURED 2026-10-06: this was a bare ``class SettingValueType(str):`` — an
    empty marker with no members, exported in ``__all__`` but used nowhere, while
    the real vocabulary lived in a separate ``_VALID_VALUE_TYPES: frozenset`` that
    ``set()`` validated against. Two declarations of one vocabulary, one of them
    dead. It is now the single definition: ``_VALID_VALUE_TYPES`` is derived from
    its members (D-045a — the declared vocabulary and the producible one are the
    same object, so a test can assert ``declared == producible`` without a mirror
    to keep in step).
    """

    FLOAT = "float"
    INT = "int"
    STR = "str"
    BOOL = "bool"
    JSON = "json"


_VALID_VALUE_TYPES: frozenset[str] = frozenset(member.value for member in SettingValueType)


class SettingRecord(Base):
    """One revision of one setting.

    A revision is **never deleted**, and its **value columns are never
    rewritten** — ``value_json``/``value_type``/``created_at``/``created_by`` are
    fixed at the instant the row is inserted. What *does* change on the row is
    the three supersession columns: when ``set()`` writes the next revision it
    stamps the prior row's ``is_active = False``, ``superseded_at`` and
    ``superseded_by`` (see ``SettingsStore.set``). MEASURED 2026-10-06: an earlier
    version of this docstring over-claimed that the whole row is immutable, and
    that broader claim is false — it is exactly the sentence a reader relies on
    when reasoning about whether a concurrent writer can rewrite a past *value*,
    and the guarantee holds for the value columns and not for the whole row. A
    "current" setting is the row with ``is_active`` true. This costs a little
    storage and buys the ability to reconstruct the exact configuration in force
    at any past instant — which is the difference between an auditable system and
    one that merely logs.
    """

    __tablename__ = "settings"
    __table_args__ = (
        UniqueConstraint("namespace", "key", "revision", name="uq_settings_ns_key_rev"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    namespace: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    value_type: Mapped[str] = mapped_column(String(16), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String(256), nullable=False)
    change_reason: Mapped[str] = mapped_column(Text, nullable=False)
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    superseded_by: Mapped[str | None] = mapped_column(String(256), nullable=True, default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)

    def decoded_value(self) -> Any:
        """Return the stored value as its declared Python type."""
        if self.value_type == SettingValueType.JSON:
            return json.loads(self.value_json)
        if self.value_type == SettingValueType.FLOAT:
            return float(self.value_json)
        if self.value_type == SettingValueType.INT:
            return int(self.value_json)
        if self.value_type == SettingValueType.BOOL:
            return self.value_json == "true"
        return self.value_json


class SettingChange(Base):
    """Append-only audit log of every settings mutation.

    Separate from ``SettingRecord`` deliberately. ``SettingRecord`` is the
    *current state*; ``SettingChange`` is the *history of actions*. Keeping them
    apart means the audit table is append-only and never participates in the
    "which row is current" query, so no settings bug can rewrite history.
    """

    __tablename__ = "setting_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    namespace: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    old_value_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    new_value_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    actor: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True, default=None)


class SettingSnapshot(BaseModel):
    """A resolved setting plus the provenance of where its value came from.

    Provenance is part of the value, not metadata about it. A thesis must be
    able to record "this threshold came from a database override applied by
    operator X at time T" — because that is the only way a reader can tell
    whether a number reflects a reviewed default or an in-incident change.
    """

    model_config = ConfigDict(frozen=True)

    namespace: str
    key: str
    value: Any
    source: str = Field(
        description='"database" | "yaml" | "environment" — which layer supplied this value.'
    )
    revision: int | None = Field(default=None, description="Database revision, if applicable.")
    changed_by: str | None = Field(default=None, description="Actor of the active revision.")
    changed_at: datetime | None = Field(
        default=None, description="When the active revision landed."
    )
    change_reason: str | None = Field(default=None, description="Why the active revision landed.")

    @model_validator(mode="after")
    def _database_snapshots_carry_full_provenance(self) -> SettingSnapshot:
        """A database-sourced snapshot must be completely attributed.

        ``revision``/``changed_at`` are optional because a YAML- or
        environment-sourced value genuinely has none. But a *database* snapshot
        always does, and leaving them optional there lets a caller reconstruct a
        revision while silently dropping when it landed — which is precisely the
        field an audit needs.

        Enforcing the invariant in the model rather than at each call site means
        a consumer can rely on it: code that has checked ``source == "database"``
        knows the timestamps are present.
        """
        if self.source == "database" and (self.revision is None or self.changed_at is None):
            raise ValueError(
                f"a database-sourced snapshot must carry a revision and a "
                f"changed_at; got revision={self.revision!r}, "
                f"changed_at={self.changed_at!r} for {self.namespace}.{self.key}"
            )
        return self

    def revision_instant(self) -> datetime:
        """``changed_at``, asserted present. For database snapshots only.

        A narrow accessor rather than a non-optional field, because the field
        genuinely is optional for the other two sources and widening it would
        lose that. Callers that hold a database snapshot can depend on this
        returning a value; callers that do not are told so at runtime instead of
        propagating a ``None`` into arithmetic.
        """
        if self.changed_at is None:
            raise ValueError(
                f"{self.namespace}.{self.key} was resolved from {self.source!r} "
                f"and has no revision instant"
            )
        return self.changed_at


class SettingsStore:
    """Read/write access to the database-backed settings layer.

    All mutations require an ``actor`` and a ``reason``. This is enforced here
    rather than by convention so that a caller cannot record an anonymous
    change — the audit trail's value depends entirely on it being impossible to
    write to it incompletely.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @classmethod
    def from_url(cls, database_url: str, *, echo: bool = False) -> SettingsStore:
        """Build a store from a SQLAlchemy URL.

        ``future=True`` is the SQLAlchemy 2.x behaviour and is set explicitly so
        the engine does not silently fall back to legacy semantics on an older
        installed version.
        """
        engine = create_engine(database_url, echo=echo, future=True)
        return cls(engine)

    def create_schema(self) -> None:
        """Create tables if absent.

        Idempotent. In production this is a migration step; the method exists so
        local development and tests do not require a migration tool to be
        installed, and so CI can build a store from nothing.
        """
        Base.metadata.create_all(self._engine)

    # -- reads --------------------------------------------------------------

    def get(self, namespace: str, key: str) -> SettingSnapshot | None:
        """Return the active revision, or ``None`` if this setting is unset.

        ``None`` rather than a default: the caller decides the fallback, and a
        silent default here would mask an unset production setting.
        """
        with Session(self._engine) as session:
            row = session.scalars(
                select(SettingRecord)
                .where(
                    SettingRecord.namespace == namespace,
                    SettingRecord.key == key,
                    SettingRecord.is_active.is_(True),
                )
                .order_by(SettingRecord.revision.desc())
                .limit(1)
            ).first()
            if row is None:
                return None
            return SettingSnapshot(
                namespace=row.namespace,
                key=row.key,
                value=row.decoded_value(),
                source="database",
                revision=row.revision,
                changed_by=row.created_by,
                changed_at=row.created_at,
                change_reason=row.change_reason,
            )

    def history(self, namespace: str, key: str) -> list[SettingSnapshot]:
        """Every revision of a setting, newest first.

        This is what makes a past thesis explainable — the question "what was
        this parameter on the day we published?" is answered by
        ``history()`` plus the thesis's own ``created_at``.
        """
        with Session(self._engine) as session:
            rows = session.scalars(
                select(SettingRecord)
                .where(SettingRecord.namespace == namespace, SettingRecord.key == key)
                .order_by(SettingRecord.revision.desc())
            ).all()
            return [
                SettingSnapshot(
                    namespace=row.namespace,
                    key=row.key,
                    value=row.decoded_value(),
                    source="database",
                    revision=row.revision,
                    changed_by=row.created_by,
                    changed_at=row.created_at,
                    change_reason=row.change_reason,
                )
                for row in rows
            ]

    def value_at(self, namespace: str, key: str, *, moment: datetime) -> SettingSnapshot | None:
        """The revision that was active at ``moment``.

        Implemented from the immutable history rather than from any "as of"
        pointer, so it cannot be corrupted by a later write.

        The interval is half-open: ``[created_at, superseded_at)``. A revision
        is selected when ``created_at <= moment`` and either it has not been
        superseded or ``moment < superseded_at``. Using a closed interval on
        the upper bound instead would make the boundary instant ambiguous —
        the old revision and the new one would both claim it, and which one
        won would depend on scan order rather than on the data.

        ``moment`` is normalised to UTC-aware before comparison so a caller
        passing a naive datetime (or one read back from SQLite, which drops
        tzinfo) gets a comparison rather than a ``TypeError``.
        """
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)

        with Session(self._engine) as session:
            rows = session.scalars(
                select(SettingRecord)
                .where(SettingRecord.namespace == namespace, SettingRecord.key == key)
                .order_by(SettingRecord.revision.desc())
            ).all()
            for row in rows:
                created = row.created_at
                if created.tzinfo is None:
                    # SQLite drops tzinfo on round-trip. The values were written
                    # tz-aware, so re-attach UTC rather than comparing naive to
                    # aware and raising.
                    created = created.replace(tzinfo=UTC)
                if created > moment:
                    continue
                superseded = row.superseded_at
                if superseded is not None and superseded.tzinfo is None:
                    superseded = superseded.replace(tzinfo=UTC)
                if superseded is None or superseded > moment:
                    return SettingSnapshot(
                        namespace=row.namespace,
                        key=row.key,
                        value=row.decoded_value(),
                        source="database",
                        revision=row.revision,
                        changed_by=row.created_by,
                        changed_at=created,
                        change_reason=row.change_reason,
                    )
            return None

    # -- writes -------------------------------------------------------------

    def set(
        self,
        namespace: str,
        key: str,
        value: Any,
        *,
        value_type: str,
        actor: str,
        reason: str,
        description: str = "",
        correlation_id: str | None = None,
    ) -> SettingSnapshot:
        """Write a new active revision, superseding the previous one.

        Raises:
            ValueError: on an unknown ``value_type``, an empty ``actor``, or an
                empty ``reason``. These are refused rather than defaulted: an
                audit trail with unnamed actors and blank reasons is not an
                audit trail.
        """
        if value_type not in _VALID_VALUE_TYPES:
            raise ValueError(
                f"value_type {value_type!r} is not one of {sorted(_VALID_VALUE_TYPES)}."
            )
        if not actor.strip():
            raise ValueError(
                "actor is required. An unattributed settings change is "
                "indistinguishable from tampering, so it is refused."
            )
        if not reason.strip():
            raise ValueError(
                "reason is required. A settings change with no recorded reason "
                "cannot be reviewed after the fact."
            )

        encoded = (
            json.dumps(value)
            if value_type == SettingValueType.JSON
            else self._encode_scalar(value, value_type)
        )
        # One timestamp per write, advancing monotonically. ``utc_now()`` has
        # microsecond resolution, and two writes inside the same microsecond
        # would otherwise produce a revision whose ``created_at`` equals the
        # previous revision's ``superseded_at`` — collapsing the instant at
        # which the old value applied to nothing, so ``value_at`` could never
        # reconstruct it. The database is the last word on what was written,
        # so the bump happens inside the session, against the previous
        # revision's own timestamps.
        moment = utc_now()

        with Session(self._engine) as session:
            previous = session.scalars(
                select(SettingRecord)
                .where(
                    SettingRecord.namespace == namespace,
                    SettingRecord.key == key,
                    SettingRecord.is_active.is_(True),
                )
                .order_by(SettingRecord.revision.desc())
                .limit(1)
            ).first()

            highest = session.scalars(
                select(func.max(SettingRecord.created_at)).where(
                    SettingRecord.namespace == namespace,
                    SettingRecord.key == key,
                )
            ).one()
            if highest is not None:
                existing = highest if highest.tzinfo is not None else highest.replace(tzinfo=UTC)
                if existing >= moment:
                    moment = existing + timedelta(microseconds=1)

            next_revision = 1 if previous is None else previous.revision + 1
            old_encoded = None
            if previous is not None:
                previous.is_active = False
                previous.superseded_at = moment
                previous.superseded_by = actor
                old_encoded = previous.value_json

            record = SettingRecord(
                namespace=namespace,
                key=key,
                revision=next_revision,
                value_json=encoded,
                value_type=value_type,
                description=description,
                created_at=moment,
                created_by=actor,
                change_reason=reason,
                is_active=True,
            )
            session.add(record)
            session.add(
                SettingChange(
                    namespace=namespace,
                    key=key,
                    action="set" if previous is not None else "create",
                    revision=next_revision,
                    old_value_json=old_encoded,
                    new_value_json=encoded,
                    actor=actor,
                    reason=reason,
                    occurred_at=moment,
                    correlation_id=correlation_id,
                )
            )
            session.commit()

            return SettingSnapshot(
                namespace=namespace,
                key=key,
                value=value,
                source="database",
                revision=next_revision,
                changed_by=actor,
                changed_at=moment,
                change_reason=reason,
            )

    def delete(
        self,
        namespace: str,
        key: str,
        *,
        actor: str,
        reason: str,
        correlation_id: str | None = None,
    ) -> bool:
        """Retire a setting. The row is retained and marked inactive.

        Named ``delete`` for the caller's intent while being an update
        underneath. A literal delete would make any historical thesis that
        consumed this setting unexplainable, so the operation is deliberately
        non-destructive.
        """
        if not actor.strip() or not reason.strip():
            raise ValueError("actor and reason are both required to retire a setting.")

        moment = utc_now()
        with Session(self._engine) as session:
            previous = session.scalars(
                select(SettingRecord)
                .where(
                    SettingRecord.namespace == namespace,
                    SettingRecord.key == key,
                    SettingRecord.is_active.is_(True),
                )
                .order_by(SettingRecord.revision.desc())
                .limit(1)
            ).first()
            if previous is None:
                return False

            # Retiring is a supersession too, so it must carry a timestamp that
            # strictly exceeds the revision it retires — otherwise a retire
            # issued in the same microsecond as the create leaves the setting
            # active for zero time and ``value_at`` cannot see it at all.
            created = previous.created_at
            if created is not None:
                if created.tzinfo is None:
                    created = created.replace(tzinfo=UTC)
                if created >= moment:
                    moment = created + timedelta(microseconds=1)

            previous.is_active = False
            previous.superseded_at = moment
            previous.superseded_by = actor
            session.add(
                SettingChange(
                    namespace=namespace,
                    key=key,
                    action="retire",
                    revision=previous.revision,
                    old_value_json=previous.value_json,
                    new_value_json=None,
                    actor=actor,
                    reason=reason,
                    occurred_at=moment,
                    correlation_id=correlation_id,
                )
            )
            session.commit()
            return True

    @staticmethod
    def _encode_scalar(value: Any, value_type: str) -> str:
        if value_type == SettingValueType.BOOL:
            return "true" if value else "false"
        if value_type == SettingValueType.FLOAT:
            return repr(float(value))
        if value_type == SettingValueType.INT:
            return str(int(value))
        return str(value)


_store: SettingsStore | None = None


def get_settings_store() -> SettingsStore:
    """Process-level settings store built from ``MACRO_DATABASE_URL``.

    Lazily constructed and cached: a caller that never touches the settings
    layer should not pay for an engine, and importing this module must not
    require a reachable database.
    """
    global _store
    if _store is None:
        from macro_engine.deployment import get_deployment_config

        config = get_deployment_config()
        _store = SettingsStore.from_url(config.database_url, echo=config.database_echo_sql)
    return _store


def reset_settings_store_cache() -> None:
    """Drop the cached store. For tests that point at a different database."""
    global _store
    _store = None
