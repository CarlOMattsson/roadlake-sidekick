"""Concrete external-reference tables and owner-filtered PostgreSQL operations.

The identity unique index (`uq_external_references_identity`) is an expression index over
`COALESCE(instance_ref, '')` and is declared only in the 0.1.0 baseline schema.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    delete,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from sidekick.references.domain import ExternalReferenceDetails
from sidekick.shared.errors import NotFoundError
from sidekick.shared.persistence.models import SCHEMA, Base, TaskRow
from sidekick.shared.persistence.stores.keyset import rows_after
from sidekick.shared.types import KeyValue, new_uuid7
from sidekick.store import SqlAlchemyStore


class ExternalReferenceRow(Base):
    __tablename__ = "external_references"
    __table_args__ = (UniqueConstraint("id", "owner_id"), {"schema": SCHEMA})
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(20))
    provider: Mapped[str] = mapped_column(String(30))
    account_ref: Mapped[str] = mapped_column(String(200))
    external_id: Mapped[str] = mapped_column(String(500))
    instance_ref: Mapped[str | None] = mapped_column(String(500))
    title: Mapped[str] = mapped_column(String(300))
    url: Mapped[str | None] = mapped_column(String(2000))
    occurs_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(20))
    version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TaskExternalReferenceRow(Base):
    __tablename__ = "task_external_references"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "owner_id"],
            [f"{SCHEMA}.tasks.id", f"{SCHEMA}.tasks.owner_id"],
            name="fk_task_external_references_task",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["reference_id", "owner_id"],
            [f"{SCHEMA}.external_references.id", f"{SCHEMA}.external_references.owner_id"],
            name="fk_task_external_references_reference",
            ondelete="CASCADE",
        ),
        {"schema": SCHEMA},
    )
    owner_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), primary_key=True
    )
    task_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    reference_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def _lock_id(material: str) -> int:
    return int.from_bytes(hashlib.sha256(material.encode()).digest()[:8], signed=True)


class ExternalReferenceStore(SqlAlchemyStore):
    @staticmethod
    def require_task(session: Session, owner: UUID, task_id: UUID) -> None:
        """Refuse another owner's, archived and trashed Tasks with one indistinct error."""

        found = session.scalar(
            select(TaskRow.id).where(
                TaskRow.id == task_id,
                TaskRow.owner_id == owner,
                TaskRow.trashed_at.is_(None),
                TaskRow.archived_at.is_(None),
            )
        )
        if found is None:
            raise NotFoundError("task not found")

    @staticmethod
    def lock_task(session: Session, owner: UUID, task_id: UUID) -> None:
        """Serialize reference-count checks for one Task for this transaction."""

        session.execute(
            select(
                func.pg_advisory_xact_lock(_lock_id(f"sidekick:task-references:{owner}:{task_id}"))
            )
        )

    @staticmethod
    def lock_identity(session: Session, owner: UUID, details: ExternalReferenceDetails) -> None:
        """Serialize upserts of one external object so the unique index is a backstop."""

        digest = details.identity_fingerprint()
        session.execute(
            select(
                func.pg_advisory_xact_lock(
                    _lock_id(f"sidekick:reference-identity:{owner}:{digest}")
                )
            )
        )

    @staticmethod
    def find_by_identity(
        session: Session, owner: UUID, details: ExternalReferenceDetails
    ) -> ExternalReferenceRow | None:
        return session.scalar(
            select(ExternalReferenceRow)
            .where(
                ExternalReferenceRow.owner_id == owner,
                ExternalReferenceRow.kind == details.kind,
                ExternalReferenceRow.provider == details.provider,
                ExternalReferenceRow.account_ref == details.account_ref,
                ExternalReferenceRow.external_id == details.external_id,
                func.coalesce(ExternalReferenceRow.instance_ref, "")
                == (details.instance_ref or ""),
            )
            .with_for_update()
        )

    @staticmethod
    def upsert_reference(
        session: Session,
        owner: UUID,
        row: ExternalReferenceRow | None,
        details: ExternalReferenceDetails,
        *,
        source: str,
        now: datetime,
    ) -> ExternalReferenceRow:
        """Create the shared pointer row, or refresh `row` (found by identity) in place."""

        if row is None:
            row = ExternalReferenceRow(
                id=new_uuid7(),
                owner_id=owner,
                kind=details.kind,
                provider=details.provider,
                account_ref=details.account_ref,
                external_id=details.external_id,
                instance_ref=details.instance_ref,
                title=details.title,
                url=details.url,
                occurs_at=details.occurs_at,
                snapshot_at=now,
                source=source,
                version=1,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            return row
        row.title, row.url, row.occurs_at = details.title, details.url, details.occurs_at
        row.snapshot_at, row.source = now, source
        row.version += 1
        row.updated_at = now
        return row

    @staticmethod
    def add_relation(
        session: Session, owner: UUID, task_id: UUID, reference_id: UUID, now: datetime
    ) -> TaskExternalReferenceRow:
        session.flush()  # the pointer row must exist before the relation that names it
        relation = TaskExternalReferenceRow(
            owner_id=owner, task_id=task_id, reference_id=reference_id, created_at=now
        )
        session.add(relation)
        return relation

    @staticmethod
    def flush(session: Session) -> None:
        session.flush()

    @staticmethod
    def get_reference(
        session: Session, owner: UUID, reference_id: UUID, *, lock: bool = False
    ) -> ExternalReferenceRow:
        statement = select(ExternalReferenceRow).where(
            ExternalReferenceRow.id == reference_id, ExternalReferenceRow.owner_id == owner
        )
        row = session.scalar(statement.with_for_update() if lock else statement)
        if row is None:
            raise NotFoundError("external reference not found")
        return row

    @staticmethod
    def get_relation(
        session: Session, owner: UUID, task_id: UUID, reference_id: UUID
    ) -> TaskExternalReferenceRow | None:
        return session.scalar(
            select(TaskExternalReferenceRow).where(
                TaskExternalReferenceRow.owner_id == owner,
                TaskExternalReferenceRow.task_id == task_id,
                TaskExternalReferenceRow.reference_id == reference_id,
            )
        )

    @staticmethod
    def count_for_task(session: Session, owner: UUID, task_id: UUID) -> int:
        return (
            session.scalar(
                select(func.count())
                .select_from(TaskExternalReferenceRow)
                .where(
                    TaskExternalReferenceRow.owner_id == owner,
                    TaskExternalReferenceRow.task_id == task_id,
                )
            )
            or 0
        )

    @staticmethod
    def count_for_reference(session: Session, owner: UUID, reference_id: UUID) -> int:
        return (
            session.scalar(
                select(func.count())
                .select_from(TaskExternalReferenceRow)
                .where(
                    TaskExternalReferenceRow.owner_id == owner,
                    TaskExternalReferenceRow.reference_id == reference_id,
                )
            )
            or 0
        )

    @staticmethod
    def delete_relation(session: Session, owner: UUID, task_id: UUID, reference_id: UUID) -> None:
        session.execute(
            delete(TaskExternalReferenceRow).where(
                TaskExternalReferenceRow.owner_id == owner,
                TaskExternalReferenceRow.task_id == task_id,
                TaskExternalReferenceRow.reference_id == reference_id,
            )
        )

    @staticmethod
    def delete_reference(session: Session, owner: UUID, reference_id: UUID) -> None:
        session.execute(
            delete(ExternalReferenceRow).where(
                ExternalReferenceRow.owner_id == owner, ExternalReferenceRow.id == reference_id
            )
        )

    @classmethod
    def release_task_references(cls, session: Session, owner: UUID, task_id: UUID) -> None:
        """Drop a Task's relations and the pointers no other Task uses (before its removal)."""

        cls.lock_task(session, owner, task_id)
        reference_ids = list(
            session.scalars(
                select(TaskExternalReferenceRow.reference_id).where(
                    TaskExternalReferenceRow.owner_id == owner,
                    TaskExternalReferenceRow.task_id == task_id,
                )
            )
        )
        for reference_id in sorted(reference_ids):
            session.execute(
                select(ExternalReferenceRow.id)
                .where(
                    ExternalReferenceRow.id == reference_id, ExternalReferenceRow.owner_id == owner
                )
                .with_for_update()
            ).all()
            cls.delete_relation(session, owner, task_id, reference_id)
            if cls.count_for_reference(session, owner, reference_id) == 0:
                cls.delete_reference(session, owner, reference_id)

    @staticmethod
    def list_for_task(
        session: Session,
        owner: UUID,
        task_id: UUID,
        *,
        limit: int,
        after: tuple[KeyValue, ...] | None,
    ) -> list[tuple[ExternalReferenceRow, datetime]]:
        """Oldest link first; `after` is the (linked_at, reference id) of the last one read."""

        statement = (
            select(ExternalReferenceRow, TaskExternalReferenceRow.created_at)
            .join(
                TaskExternalReferenceRow,
                (TaskExternalReferenceRow.reference_id == ExternalReferenceRow.id)
                & (TaskExternalReferenceRow.owner_id == ExternalReferenceRow.owner_id),
            )
            .where(
                TaskExternalReferenceRow.owner_id == owner,
                TaskExternalReferenceRow.task_id == task_id,
            )
            .order_by(TaskExternalReferenceRow.created_at, ExternalReferenceRow.id)
            .limit(limit)
        )
        if after is not None:
            statement = statement.where(
                rows_after(
                    (TaskExternalReferenceRow.created_at, ExternalReferenceRow.id),
                    after,
                    descending=False,
                )
            )
        rows = session.execute(statement)
        return [(row, linked_at) for row, linked_at in rows]
