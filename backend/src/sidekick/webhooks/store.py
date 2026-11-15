"""Storage of webhook tokens: the token rows and the audit rows of their lifecycle.

Every method takes the open transaction that `WebhookTokenStore.transaction` (or `read`) hands out;
the service decides what to read and write, this module only knows how. Rows never leave it: the
service sees `WebhookTokenRecord`. Nothing here logs, and nothing writes a token, only its keyed
digest and its display prefix.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TypeVar
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from sidekick.shared.persistence.models import AuditEventRow, UserRow, WebhookTokenRow
from sidekick.shared.types import TxSession, new_uuid7

T = TypeVar("T")

# A token's `last_used_at` is rewritten at most this often.
LAST_USED_WRITE_INTERVAL = timedelta(minutes=1)


@dataclass(frozen=True, slots=True)
class WebhookTokenRecord:
    """One token row as stored; the digest is not part of it."""

    id: UUID
    user_id: UUID
    label: str
    token_prefix: str
    scopes: tuple[str, ...]
    rate_limit_per_minute: int
    expires_at: datetime
    revoked_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime


def _record(row: WebhookTokenRow) -> WebhookTokenRecord:
    return WebhookTokenRecord(
        id=row.id,
        user_id=row.user_id,
        label=row.label,
        token_prefix=row.token_prefix,
        scopes=tuple(sorted(row.scopes)),
        rate_limit_per_minute=row.rate_limit_per_minute,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        last_used_at=row.last_used_at,
        created_at=row.created_at,
    )


class WebhookTokenStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def transaction(self, operation: Callable[[TxSession], T]) -> T:
        with self._session_factory.begin() as session:
            return operation(session)

    def read(self, operation: Callable[[TxSession], T]) -> T:
        with self._session_factory() as session:
            return operation(session)

    @staticmethod
    def user_is_active(session: TxSession, user_id: UUID) -> bool:
        return bool(session.scalar(select(UserRow.active).where(UserRow.id == user_id)))

    @staticmethod
    def active_owner_ids(session: TxSession, limit: int) -> list[UUID]:
        """At most `limit` ids of active users."""

        return list(
            session.scalars(select(UserRow.id).where(UserRow.active.is_(True)).limit(limit))
        )

    @staticmethod
    def add(
        session: TxSession,
        *,
        user_id: UUID,
        label: str,
        token_prefix: str,
        token_digest: str,
        scopes: Iterable[str],
        rate_limit_per_minute: int,
        expires_at: datetime,
        now: datetime,
    ) -> WebhookTokenRecord:
        row = WebhookTokenRow(
            id=new_uuid7(),
            user_id=user_id,
            label=label,
            token_prefix=token_prefix,
            token_digest=token_digest,
            scopes=sorted(scopes),
            rate_limit_per_minute=rate_limit_per_minute,
            expires_at=expires_at,
            revoked_at=None,
            last_used_at=None,
            created_at=now,
        )
        session.add(row)
        session.flush()
        return _record(row)

    @staticmethod
    def list_for_owner(session: TxSession, user_id: UUID) -> list[WebhookTokenRecord]:
        rows = session.scalars(
            select(WebhookTokenRow)
            .where(WebhookTokenRow.user_id == user_id)
            .order_by(WebhookTokenRow.created_at.desc())
        )
        return [_record(row) for row in rows]

    @staticmethod
    def revoke(session: TxSession, user_id: UUID, token_id: UUID, now: datetime) -> bool | None:
        """Revoke this owner's token: `True` if it was live, `False` if already revoked, `None` if
        there is no such token. The row is locked, so two revocations record one."""

        row = session.scalar(
            select(WebhookTokenRow)
            .where(WebhookTokenRow.id == token_id, WebhookTokenRow.user_id == user_id)
            .with_for_update()
        )
        if row is None:
            return None
        if row.revoked_at is not None:
            return False
        row.revoked_at = now
        return True

    @staticmethod
    def live_by_digest(
        session: TxSession, token_digest: str, now: datetime
    ) -> WebhookTokenRecord | None:
        """The token with this digest if it is not revoked or expired and its owner is active."""

        row = session.scalar(
            select(WebhookTokenRow)
            .join(UserRow, UserRow.id == WebhookTokenRow.user_id)
            .where(
                WebhookTokenRow.token_digest == token_digest,
                WebhookTokenRow.revoked_at.is_(None),
                WebhookTokenRow.expires_at > now,
                UserRow.active.is_(True),
            )
        )
        return None if row is None else _record(row)

    @staticmethod
    def touch(session: TxSession, token_id: UUID, now: datetime) -> None:
        """Record a use, at most once per `LAST_USED_WRITE_INTERVAL`. The condition is in the
        UPDATE itself, so two concurrent calls cannot both write."""

        session.execute(
            update(WebhookTokenRow)
            .where(
                WebhookTokenRow.id == token_id,
                or_(
                    WebhookTokenRow.last_used_at.is_(None),
                    WebhookTokenRow.last_used_at <= now - LAST_USED_WRITE_INTERVAL,
                ),
            )
            .values(last_used_at=now)
            .execution_options(synchronize_session=False)
        )

    @staticmethod
    def append_audit(
        session: TxSession, actor_id: UUID, event: str, token_id: UUID, occurred_at: datetime
    ) -> None:
        session.add(
            AuditEventRow(
                id=new_uuid7(),
                actor_id=actor_id,
                event=event,
                outcome="success",
                reason=None,
                correlation_id=None,
                target_type="webhook_token",
                target_id=token_id,
                occurred_at=occurred_at,
            )
        )
