"""Webhook tokens: one token per integration (Home Assistant, Tasker, ...), for `/webhooks/v1/`.

A webhook token is not a personal access token. It lives in its own table, is accepted only by the
webhook routes (an MCP token or a companion device credential is never one), holds webhook scopes
that are not application scopes, has a rate limit of its own and always expires. The operator
creates, lists and revokes tokens (`sidekick.webhooks.cli`); the token itself is shown once, when it
is created. Only its keyed digest and its first characters (`token_prefix`, to tell tokens apart in
the operator's list) are stored.

Nothing here logs or audits a token or a label: audit rows carry closed event names and record ids.
The routes map each scope to one fixed use case with fixed application scopes
(`sidekick.webhooks.operations`), so a webhook token reaches nothing else.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sidekick.shared.auth import AuthService
from sidekick.shared.auth.verification_signal import mark_verified
from sidekick.shared.errors import InvalidInputError
from sidekick.shared.errors.core import RefusedError
from sidekick.shared.types import TxSession, utc_now
from sidekick.webhooks.store import WebhookTokenRecord, WebhookTokenStore

WEBHOOK_SHOPPING_ADD = "webhook:shopping:add"
WEBHOOK_TASKS_CREATE = "webhook:tasks:create"
WEBHOOK_SCOPES: frozenset[str] = frozenset({WEBHOOK_SHOPPING_ADD, WEBHOOK_TASKS_CREATE})

TOKEN_PREFIX = "rsw_"  # noqa: S105  # public format prefix, not a credential
# What the list shows of a token: the format prefix and the first characters of its random part.
DISPLAY_PREFIX_LENGTH = len(TOKEN_PREFIX) + 6
DEFAULT_LIFETIME_DAYS = 365
MAX_LIFETIME_DAYS = 730
DEFAULT_RATE_LIMIT_PER_MINUTE = 30
MAX_RATE_LIMIT_PER_MINUTE = 600
MAX_LABEL_LENGTH = 120


@dataclass(frozen=True, slots=True)
class WebhookCredential:
    """A verified webhook token: which token, whose, what it may do and how fast."""

    token_id: UUID
    user_id: UUID
    scopes: frozenset[str]
    rate_limit_per_minute: int


@dataclass(frozen=True, slots=True)
class IssuedWebhookToken:
    """What creating a token answers: the token, shown once, and its record."""

    token: str
    record: WebhookTokenRecord


def validate_new_token(
    label: str, scopes: Iterable[str], lifetime_days: int, rate_limit_per_minute: int
) -> tuple[str, frozenset[str]]:
    """The cleaned label and the scope set of a token to create, or `InvalidInputError`."""

    text = label.strip()
    if not text or len(text) > MAX_LABEL_LENGTH:
        raise InvalidInputError(f"token label must be 1 to {MAX_LABEL_LENGTH} characters")
    if any(not character.isprintable() for character in text):
        raise InvalidInputError("token label must not contain control characters")
    chosen = frozenset(scopes)
    if not chosen or not chosen <= WEBHOOK_SCOPES:
        raise InvalidInputError("webhook scopes must be a non-empty subset of the webhook scopes")
    if not 1 <= lifetime_days <= MAX_LIFETIME_DAYS:
        raise InvalidInputError(f"token lifetime must be 1 to {MAX_LIFETIME_DAYS} days")
    if not 1 <= rate_limit_per_minute <= MAX_RATE_LIMIT_PER_MINUTE:
        raise InvalidInputError(f"rate limit must be 1 to {MAX_RATE_LIMIT_PER_MINUTE} per minute")
    return text, chosen


def _system_now() -> datetime:
    # Looked up at call time so a test can pin the clock of a whole app.
    return utc_now()


class WebhookTokenService:
    def __init__(
        self,
        store: WebhookTokenStore,
        auth: AuthService,
        clock: Callable[[], datetime] = _system_now,
    ) -> None:
        self._store = store
        self._auth = auth
        self._clock = clock

    def create(
        self,
        user_id: UUID,
        label: str,
        scopes: Iterable[str],
        *,
        lifetime_days: int = DEFAULT_LIFETIME_DAYS,
        rate_limit_per_minute: int = DEFAULT_RATE_LIMIT_PER_MINUTE,
    ) -> IssuedWebhookToken:
        clean_label, chosen = validate_new_token(
            label, scopes, lifetime_days, rate_limit_per_minute
        )
        token = f"{TOKEN_PREFIX}{secrets.token_urlsafe(32)}"
        now = self._clock()

        def create(session: TxSession) -> WebhookTokenRecord:
            if not self._store.user_is_active(session, user_id):
                raise RefusedError("active user not found")
            record = self._store.add(
                session,
                user_id=user_id,
                label=clean_label,
                token_prefix=token[:DISPLAY_PREFIX_LENGTH],
                token_digest=self._auth.digest(token),
                scopes=chosen,
                rate_limit_per_minute=rate_limit_per_minute,
                expires_at=now + timedelta(days=lifetime_days),
                now=now,
            )
            self._store.append_audit(session, user_id, "webhook.token_created", record.id, now)
            return record

        return IssuedWebhookToken(token=token, record=self._store.transaction(create))

    def list_tokens(self, user_id: UUID) -> list[WebhookTokenRecord]:
        return self._store.read(lambda session: self._store.list_for_owner(session, user_id))

    def revoke(self, user_id: UUID, token_id: UUID) -> bool:
        """Revoke one of this owner's tokens. Idempotent; `False` only for an unknown token."""

        now = self._clock()

        def revoke(session: TxSession) -> bool:
            revoked = self._store.revoke(session, user_id, token_id, now)
            if revoked:
                self._store.append_audit(session, user_id, "webhook.token_revoked", token_id, now)
            return revoked is not None

        return self._store.transaction(revoke)

    def active_owner_ids(self, limit: int) -> list[UUID]:
        """At most `limit` ids of active users."""

        return self._store.read(lambda session: self._store.active_owner_ids(session, limit))

    def verify(self, token: str) -> WebhookCredential | None:
        """The credential behind this token, checked afresh on every call, or `None`.

        Unknown, expired and revoked tokens, and tokens of a disabled owner, all answer `None`.
        The scopes are clipped to the webhook scopes, so a row never carries an application scope.
        """

        now = self._clock()
        digest = self._auth.digest(token)

        def verify(session: TxSession) -> WebhookCredential | None:
            record = self._store.live_by_digest(session, digest, now)
            if record is None:
                return None
            scopes = frozenset(record.scopes) & WEBHOOK_SCOPES
            if not scopes:
                return None
            self._store.touch(session, record.id, now)
            mark_verified()
            return WebhookCredential(
                token_id=record.id,
                user_id=record.user_id,
                scopes=scopes,
                rate_limit_per_minute=record.rate_limit_per_minute,
            )

        return self._store.transaction(verify)
