"""Local pre-provisioning and scoped personal tokens (MCP and companion devices)."""

import hashlib
import hmac
import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from sidekick.shared.auth.verification_signal import mark_verified
from sidekick.shared.errors.core import RefusedError
from sidekick.shared.persistence.models import (
    AuditEventRow,
    PersonalAccessTokenRow,
    UserRow,
)
from sidekick.shared.types import Actor, new_uuid7, utc_now

#: Called inside the transaction that inserts a user, after the user row is flushed, with the open
#: session, the new user's id and the time of creation. The composition root passes the hooks of the
#: contexts that keep a row per owner, so auth itself knows none of them.
UserProvisionedHook = Callable[[Session, UUID, datetime], None]

# A personal token's `last_used_at` is rewritten at most this often.
LAST_USED_WRITE_INTERVAL = timedelta(minutes=1)

# The thirteen scopes the public MCP surface can ever carry, in their advertised order. This is the
# ceiling for every MCP credential: a personal token holds a subset the operator chose, and an
# OAuth session holds a subset the server policy chose. Neither can hold more than this.
MCP_SCOPES: tuple[str, ...] = (
    "projects:read",
    "projects:write",
    "tasks:read",
    "tasks:write",
    "contacts:read",
    "contacts:write",
    "journal:read",
    "journal:write",
    "shopping:read",
    "shopping:write",
    "license:write",
    "automation:read",
    "automation:write",
)

ALL_SCOPES: frozenset[str] = frozenset(MCP_SCOPES)

# Opt-in scopes are never part of a default personal token. An operator must name each one
# explicitly (sidekick-admin create-token --scope automation:write).
OPT_IN_SCOPES = frozenset({"automation:read", "automation:write"})
TOKEN_SCOPES = ALL_SCOPES - OPT_IN_SCOPES

# Device capabilities of a paired companion app (ADR-005). They are not application scopes:
# no session, personal token or MCP credential can hold them, and a companion credential holds
# nothing else. The companion adapter maps each one to a fixed set of operations
# (sidekick.companion.operations); the device is never handed `tasks:write` itself.
# `companion:push` registers the device's UnifiedPush endpoint (D-078); it reaches no use case.
# The rooms Inköp and Dagbok: a read and a write capability each. The write capability is the manual
# writing of the owner's own data (D-076: the journal is written and changed by hand in the room, no
# AI). A write operation answers with the record it wrote, so it also needs the room's read
# capability (`CompanionOperation.also`).
COMPANION_ROOM_SCOPES = frozenset(
    {
        "companion:shopping:read",
        "companion:shopping:write",
        "companion:journal:read",
        "companion:journal:write",
    }
)
# `companion:license` lets the device read the instance's license state and enter a key (D-081); it
# reaches no domain use case. Setting the key is further limited to the instance's only owner.
COMPANION_SCOPES = (
    frozenset(
        {"companion:tasks:read", "companion:tasks:complete", "companion:push", "companion:license"}
    )
    | COMPANION_ROOM_SCOPES
)

# What a credential row is for. A personal token (`mcp`) is accepted only by the MCP bearer
# verifier; a companion device credential only by `/companion/v1/`. The purpose is a column, not a
# prefix or a scope convention, so neither verifier can accept the other's rows by mistake.
TOKEN_PURPOSE_MCP = "mcp"  # noqa: S105  # a purpose label, not a credential
TOKEN_PURPOSE_COMPANION = "companion"  # noqa: S105  # a purpose label, not a credential


@dataclass(frozen=True, slots=True)
class PersonalTokenView:
    id: UUID
    label: str
    scopes: tuple[str, ...]
    expires_at: datetime | None
    revoked_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime
    purpose: str = TOKEN_PURPOSE_MCP


@dataclass(frozen=True, slots=True)
class CompanionCredential:
    """A verified companion device credential: which device, whose, and what it may do."""

    device_id: UUID
    user_id: UUID
    scopes: frozenset[str]


class AuthService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        pepper: str,
        on_user_provisioned: Sequence[UserProvisionedHook] = (),
    ) -> None:
        self._session_factory = session_factory
        self._on_user_provisioned = tuple(on_user_provisioned)
        self._pepper = pepper.encode()

    def digest(self, token: str) -> str:
        return hmac.new(self._pepper, token.encode(), hashlib.sha256).hexdigest()

    def provision_user(self, username: str, display_name: str) -> UUID:
        with self._session_factory.begin() as session:
            return self._insert_user(session, username.strip(), display_name.strip())

    def ensure_user(self, username: str, display_name: str) -> tuple[UUID, bool]:
        """Provision the user if missing, leaving an existing user and its credentials untouched.

        Returns the user id and whether the row was created. A disabled user is an error, never
        re-enabled here.
        """

        normalized_username = username.strip()
        with self._session_factory.begin() as session:
            existing = session.scalar(
                select(UserRow).where(UserRow.username == normalized_username)
            )
            if existing is not None:
                if not existing.active:
                    raise RefusedError("user exists but is disabled")
                return existing.id, False
            return self._insert_user(session, normalized_username, display_name.strip()), True

    def _insert_user(self, session: Session, username: str, display_name: str) -> UUID:
        user_id = new_uuid7()
        now = utc_now()
        session.add(
            UserRow(
                id=user_id,
                username=username,
                display_name=display_name,
                active=True,
                created_at=now,
            )
        )
        # No relationship links the user to the rows other contexts keep per owner, so flush the
        # user before the hooks write theirs.
        session.flush()
        for hook in self._on_user_provisioned:
            hook(session, user_id, now)
        return user_id

    def create_personal_token(
        self,
        user_id: UUID,
        label: str,
        scopes: frozenset[str],
        expires_at: datetime | None = None,
    ) -> str:
        if not scopes or not scopes <= TOKEN_SCOPES | OPT_IN_SCOPES:
            raise RefusedError("unknown or empty token scopes")
        token = f"rsp_{secrets.token_urlsafe(40)}"
        with self._session_factory.begin() as session:
            user = session.get(UserRow, user_id)
            if user is None or not user.active:
                raise RefusedError("active user not found")
            session.add(
                PersonalAccessTokenRow(
                    id=new_uuid7(),
                    user_id=user_id,
                    label=label,
                    token_digest=self.digest(token),
                    scopes=sorted(scopes),
                    expires_at=expires_at,
                    revoked_at=None,
                    last_used_at=None,
                    created_at=utc_now(),
                    purpose=TOKEN_PURPOSE_MCP,
                )
            )
            self._audit(session, user_id, "auth.token_created", "success")
        return token

    def list_personal_tokens(self, user_id: UUID) -> list[PersonalTokenView]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(PersonalAccessTokenRow)
                .where(PersonalAccessTokenRow.user_id == user_id)
                .order_by(PersonalAccessTokenRow.created_at.desc())
            )
            return [
                PersonalTokenView(
                    id=row.id,
                    label=row.label,
                    scopes=tuple(row.scopes),
                    expires_at=row.expires_at,
                    revoked_at=row.revoked_at,
                    last_used_at=row.last_used_at,
                    created_at=row.created_at,
                    purpose=row.purpose,
                )
                for row in rows
            ]

    def revoke_personal_token(self, token_id: UUID) -> bool:
        with self._session_factory.begin() as session:
            row = session.get(PersonalAccessTokenRow, token_id)
            if row is None:
                return False
            if row.revoked_at is None:
                row.revoked_at = utc_now()
                self._audit(session, row.user_id, "auth.token_revoked", "success")
            return True

    def disable_user(self, user_id: UUID) -> bool:
        with self._session_factory.begin() as session:
            user = session.get(UserRow, user_id)
            if user is None:
                return False
            user.active = False
            now = utc_now()
            for token in session.scalars(
                select(PersonalAccessTokenRow).where(
                    PersonalAccessTokenRow.user_id == user_id,
                    PersonalAccessTokenRow.revoked_at.is_(None),
                )
            ):
                token.revoked_at = now
            self._audit(session, user_id, "auth.user_disabled", "success")
            return True

    def is_user_active(self, user_id: UUID) -> bool:
        """Whether this user exists and has not been disabled. Unknown users are inactive."""

        with self._session_factory.begin() as session:
            return bool(session.scalar(select(UserRow.active).where(UserRow.id == user_id)))

    def verify_personal_token(self, token: str) -> Actor | None:
        """An MCP personal token's actor. A companion device credential is never one.

        The scopes are clipped to the ones a token can be issued with, so a name stored in the row
        that is unknown or no longer defined (a chat scope in an old row) is carried no further.
        """

        row = self._verify_token_row(token, TOKEN_PURPOSE_MCP)
        if row is None:
            return None
        mark_verified()
        return Actor(row.user_id, frozenset(row.scopes) & (TOKEN_SCOPES | OPT_IN_SCOPES))

    def verify_companion_token(self, token: str) -> CompanionCredential | None:
        """A companion device credential (ADR-005). A personal MCP token is never one.

        The scopes are clipped to the companion capabilities, so a row can never carry an
        application scope onto `/companion/v1/` even if one were written to it by hand.
        """

        row = self._verify_token_row(token, TOKEN_PURPOSE_COMPANION)
        if row is None or row.expires_at is None:
            return None
        scopes = frozenset(row.scopes) & COMPANION_SCOPES
        if not scopes:
            return None
        mark_verified()
        return CompanionCredential(device_id=row.id, user_id=row.user_id, scopes=scopes)

    def _verify_token_row(self, token: str, purpose: str) -> PersonalAccessTokenRow | None:
        now = utc_now()
        with self._session_factory.begin() as session:
            digest = self.digest(token)
            lookup = PersonalAccessTokenRow.token_digest == digest
            if purpose == TOKEN_PURPOSE_COMPANION:
                # A renewed device credential's predecessor still works until its window ends.
                lookup = or_(
                    lookup,
                    and_(
                        PersonalAccessTokenRow.previous_token_digest == digest,
                        PersonalAccessTokenRow.previous_valid_until > now,
                    ),
                )
            row = session.scalar(
                select(PersonalAccessTokenRow)
                .join(UserRow, UserRow.id == PersonalAccessTokenRow.user_id)
                .where(
                    lookup,
                    PersonalAccessTokenRow.purpose == purpose,
                    PersonalAccessTokenRow.revoked_at.is_(None),
                    UserRow.active.is_(True),
                )
            )
            if row is None or (row.expires_at is not None and row.expires_at <= now):
                return None
            if row.token_digest == digest and row.previous_token_digest is not None:
                # The first use of the renewed credential ends its predecessor's window.
                session.execute(
                    update(PersonalAccessTokenRow)
                    .where(
                        PersonalAccessTokenRow.id == row.id,
                        # Only the grace that was read is ended: a renewal that committed
                        # meanwhile has set a different previous digest, which must survive.
                        PersonalAccessTokenRow.previous_token_digest == row.previous_token_digest,
                    )
                    .values(previous_token_digest=None, previous_valid_until=None)
                    .execution_options(synchronize_session=False)
                )
            # Revocation, expiry and the active-user check above run on every call. Only the
            # bookkeeping write is thinned out: at most one `last_used_at` update a minute. The
            # condition is in the UPDATE itself, so two concurrent calls cannot both write.
            session.execute(
                update(PersonalAccessTokenRow)
                .where(
                    PersonalAccessTokenRow.id == row.id,
                    or_(
                        PersonalAccessTokenRow.last_used_at.is_(None),
                        PersonalAccessTokenRow.last_used_at <= now - LAST_USED_WRITE_INTERVAL,
                    ),
                )
                .values(last_used_at=now)
                .execution_options(synchronize_session=False)
            )
            session.expunge(row)
            return row

    @staticmethod
    def _audit(
        session: Session,
        actor_id: UUID | None,
        event: str,
        outcome: str,
        *,
        reason: str | None = None,
    ) -> None:
        session.add(
            AuditEventRow(
                id=new_uuid7(),
                actor_id=actor_id,
                event=event,
                outcome=outcome,
                reason=reason,
                correlation_id=None,
                target_type=None,
                target_id=None,
                occurred_at=utc_now(),
            )
        )
