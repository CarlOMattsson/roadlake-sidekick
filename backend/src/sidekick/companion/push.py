"""Push subscriptions of paired companion devices (ADR-005; D-078, push through UnifiedPush).

A device registers the UnifiedPush endpoint its distributor gave it. The endpoint is a capability
to push to that phone and the server will later POST to it, so it is validated as an SSRF guard
before it is stored: https only, no userinfo, no IP literal, port 443, at most 512 characters, and
the host must be one of `SIDEKICK_PUSH_ALLOWED_HOSTS` (default `ntfy.sh`). `validate_endpoint` is
pure and needs no framework or database.

At most one subscription per pairing is active: a new registration replaces the old one in place
(one atomic upsert on the partial unique index). Nothing here logs or audits an endpoint; audit
rows carry closed-vocabulary events and the device id, and a subscription is identified in logs
by its host alone.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Callable, Collection
from datetime import datetime
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from sidekick.shared.errors.core import NotFoundError, ValidationError
from sidekick.shared.persistence.models import (
    AuditEventRow,
    CompanionPairingRow,
    PushSubscriptionRow,
)
from sidekick.shared.types import new_uuid7, utc_now

MAX_ENDPOINT_LENGTH = 512
PUSH_PORT = 443


class EndpointRejected(ValidationError):
    """The endpoint is not an acceptable push destination. The text never echoes the input."""


class PairingNotFound(NotFoundError):
    """The device has no companion pairing (revoked or unknown)."""


def validate_endpoint(endpoint: str, allowed_hosts: Collection[str]) -> str:
    """The endpoint's host when it is an acceptable push destination, else `EndpointRejected`."""

    if not endpoint or len(endpoint) > MAX_ENDPOINT_LENGTH:
        raise EndpointRejected("endpoint length")
    # Printable ASCII without blanks or backslashes: nothing a URL parser could read two ways.
    if not endpoint.isascii() or any(
        not character.isprintable() or character in " \\" for character in endpoint
    ):
        raise EndpointRejected("endpoint characters")
    try:
        parts = urlsplit(endpoint)
        port = parts.port
    except ValueError:
        raise EndpointRejected("endpoint form") from None
    if parts.scheme != "https":
        raise EndpointRejected("endpoint scheme")
    if "@" in parts.netloc:
        raise EndpointRejected("endpoint userinfo")
    host = parts.hostname
    if not host:
        raise EndpointRejected("endpoint host")
    if _is_ip_literal(host):
        raise EndpointRejected("endpoint host")
    if port is not None and port != PUSH_PORT:
        raise EndpointRejected("endpoint port")
    if parts.fragment or host not in {item.lower() for item in allowed_hosts}:
        raise EndpointRejected("endpoint host")
    return host


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True


class PushSubscriptionService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        allowed_hosts: Collection[str],
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._allowed_hosts = frozenset(allowed_hosts)
        self._clock = clock

    def subscribe(
        self,
        user_id: UUID,
        device_id: UUID,
        endpoint: str,
        *,
        correlation_id: str | None = None,
    ) -> str:
        """Register (or replace) the device's endpoint; returns its host. Raises
        `EndpointRejected` for an unacceptable endpoint and `PairingNotFound` for an unknown
        device."""

        host = validate_endpoint(endpoint, self._allowed_hosts)
        now = self._clock()
        with self._session_factory.begin() as session:
            pairing_id = _pairing_of(session, user_id, device_id)
            if pairing_id is None:
                raise PairingNotFound
            statement = insert(PushSubscriptionRow).values(
                id=new_uuid7(),
                pairing_id=pairing_id,
                user_id=user_id,
                endpoint=endpoint,
                endpoint_host=host,
                created_at=now,
                updated_at=now,
                failure_count=0,
            )
            session.execute(
                statement.on_conflict_do_update(
                    index_elements=[PushSubscriptionRow.pairing_id],
                    index_where=PushSubscriptionRow.revoked_at.is_(None),
                    set_={
                        "endpoint": statement.excluded.endpoint,
                        "endpoint_host": statement.excluded.endpoint_host,
                        "updated_at": now,
                        "failure_count": 0,
                    },
                )
            )
            record_device_event(
                session, user_id, "companion.push_subscribed", device_id, correlation_id
            )
        return host

    def unsubscribe(
        self, user_id: UUID, device_id: UUID, *, correlation_id: str | None = None
    ) -> bool:
        """Revoke the device's active subscription. Idempotent; `False` when there was none."""

        with self._session_factory.begin() as session:
            revoked = revoke_for_device(session, user_id, device_id, self._clock())
            if revoked:
                record_device_event(
                    session, user_id, "companion.push_unsubscribed", device_id, correlation_id
                )
            return revoked

    def active_endpoint_host(self, user_id: UUID, device_id: UUID) -> str | None:
        """The host of the device's active subscription, for tests and status; never the URL."""

        with self._session_factory() as session:
            return session.scalar(
                select(PushSubscriptionRow.endpoint_host)
                .join(CompanionPairingRow, CompanionPairingRow.id == PushSubscriptionRow.pairing_id)
                .where(
                    CompanionPairingRow.device_token_id == device_id,
                    PushSubscriptionRow.user_id == user_id,
                    PushSubscriptionRow.revoked_at.is_(None),
                )
            )


def revoke_for_device(session: Session, user_id: UUID, device_id: UUID, now: datetime) -> bool:
    """Revoke the active subscription of the pairing behind `device_id`, in the caller's
    transaction. The device service calls this when it revokes the device."""

    pairing_ids = select(CompanionPairingRow.id).where(
        CompanionPairingRow.device_token_id == device_id, CompanionPairingRow.user_id == user_id
    )
    result = session.execute(
        update(PushSubscriptionRow)
        .where(
            PushSubscriptionRow.pairing_id.in_(pairing_ids),
            PushSubscriptionRow.user_id == user_id,
            PushSubscriptionRow.revoked_at.is_(None),
        )
        .values(revoked_at=now, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


def _pairing_of(session: Session, user_id: UUID, device_id: UUID) -> UUID | None:
    return session.scalar(
        select(CompanionPairingRow.id).where(
            CompanionPairingRow.device_token_id == device_id,
            CompanionPairingRow.user_id == user_id,
        )
    )


def record_device_event(
    session: Session,
    user_id: UUID,
    event: str,
    device_id: UUID,
    correlation_id: str | None,
) -> None:
    session.add(
        AuditEventRow(
            id=new_uuid7(),
            actor_id=user_id,
            event=event,
            outcome="success",
            reason=None,
            correlation_id=correlation_id,
            target_type="companion_device",
            target_id=device_id,
            occurred_at=utc_now(),
        )
    )
