"""Pairing and lifecycle of companion devices (ADR-005).

A companion device holds a personal-access-token row with `purpose = 'companion'`: the same keyed
digest, expiry, revocation and active-owner check as a personal MCP token, but accepted only by
`/companion/v1/` (`AuthService.verify_companion_token`) and refused by `/mcp/`.

Pairing is a bounded operator bootstrap. The operator command issues a pairing secret that
is short-lived (10 minutes), single-use and high-entropy (256 bits); only its keyed digest is
stored. The device exchanges it once for its own credential. The exchange claims the pairing row
with one conditional UPDATE, so two simultaneous exchanges of one secret yield exactly one device.

Nothing here logs or audits a secret, a token or a label: audit rows carry closed-vocabulary
events and reasons plus record ids. Only a real pairing leaves a trail (created, paired, or used up
by a disabled owner); an unknown, expired or used secret writes no row.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sidekick.companion.persistence import CompanionDeviceStore, DeviceRecord
from sidekick.shared.auth import COMPANION_SCOPES, AuthService
from sidekick.shared.errors import InvalidInputError
from sidekick.shared.errors.core import RateLimitedError, RefusedError, SidekickError
from sidekick.shared.types import TxSession, new_uuid7, utc_now

PAIRING_TTL = timedelta(minutes=10)
# A device credential lives 30 days unless the operator says otherwise, at most 90 (D-077). It is
# never perpetual: the device renews its own credential in the last `RENEWAL_WINDOW` before it
# expires (`renew`), and pairs again if it let the credential lapse.
DEFAULT_DEVICE_LIFETIME_DAYS = 30
RENEWAL_WINDOW = timedelta(days=7)
# After a renewal the credential it replaces keeps working this long, or until the new one is
# first used: a device that never saw the answer can retry.
RENEWAL_GRACE = timedelta(minutes=10)
MAX_RENEWALS_PER_DAY = 5
RENEWED_VIA_PREVIOUS_REASON = "via_previous_token"
GRANT_NO_CHANGE_REASON = "no_change"
RENEWAL_RATE_WINDOW = timedelta(hours=24)
MAX_DEVICE_LIFETIME_DAYS = 90
PAIRING_SECRET_PREFIX = "rspair_"  # noqa: S105  # public format prefix, not a credential
DEVICE_TOKEN_PREFIX = "rsc_"  # noqa: S105  # public format prefix, not a credential
MAX_LABEL_LENGTH = 120
# The longest pairing secret the exchange reads; longer input is refused before any digest.
MAX_PAIRING_SECRET_LENGTH = 128


@dataclass(frozen=True, slots=True)
class PairingTicket:
    """What the operator command prints once. The secret is never stored or shown again."""

    pairing_id: UUID
    secret: str
    label: str
    scopes: tuple[str, ...]
    expires_at: datetime
    device_lifetime_days: int


@dataclass(frozen=True, slots=True)
class CompanionDeviceView:
    id: UUID
    label: str
    scopes: tuple[str, ...]
    expires_at: datetime
    revoked_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime

    @property
    def renew_after(self) -> datetime:
        """From when the device may renew: `RENEWAL_WINDOW` before its credential expires."""

        return self.expires_at - RENEWAL_WINDOW


class RenewalNotDue(SidekickError):
    """The credential has more than `RENEWAL_WINDOW` left; `renew_after` says when to come back."""

    def __init__(self, renew_after: datetime) -> None:
        super().__init__("renewal_not_due")
        self.renew_after = renew_after


class RenewalRateLimited(RateLimitedError):
    """`MAX_RENEWALS_PER_DAY` renewals have already been made in the last 24 hours."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("rate_limited")
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True, slots=True)
class PairedDevice:
    """The exchange's answer: the device credential, returned exactly once."""

    token: str
    device: CompanionDeviceView


def _system_now() -> datetime:
    # Looked up at call time so a test can pin the clock of a whole app.
    return utc_now()


class CompanionDeviceService:
    def __init__(
        self,
        store: CompanionDeviceStore,
        auth: AuthService,
        clock: Callable[[], datetime] = _system_now,
    ) -> None:
        self._store = store
        self._auth = auth
        self._clock = clock

    def create_pairing(
        self,
        user_id: UUID,
        label: str,
        *,
        scopes: Iterable[str] = COMPANION_SCOPES,
        device_lifetime_days: int = DEFAULT_DEVICE_LIFETIME_DAYS,
        ttl: timedelta = PAIRING_TTL,
    ) -> PairingTicket:
        clean_label = _clean_label(label)
        chosen = frozenset(scopes)
        if not chosen or not chosen <= COMPANION_SCOPES:
            raise InvalidInputError(
                "companion scopes must be a non-empty subset of the device scopes"
            )
        if not 1 <= device_lifetime_days <= MAX_DEVICE_LIFETIME_DAYS:
            raise InvalidInputError(f"device lifetime must be 1 to {MAX_DEVICE_LIFETIME_DAYS} days")
        if not timedelta(0) < ttl <= PAIRING_TTL:
            raise InvalidInputError("pairing lifetime must be positive and at most 10 minutes")
        secret = f"{PAIRING_SECRET_PREFIX}{secrets.token_urlsafe(32)}"
        now = self._clock()
        pairing_id = new_uuid7()

        def create(session: TxSession) -> None:
            if not self._store.user_is_active(session, user_id):
                raise RefusedError("active user not found")
            self._store.add_pairing(
                session,
                pairing_id=pairing_id,
                user_id=user_id,
                label=clean_label,
                scopes=chosen,
                secret_digest=self._auth.digest(secret),
                device_lifetime_days=device_lifetime_days,
                expires_at=now + ttl,
                now=now,
            )
            self._audit(
                session, user_id, "companion.pairing_created", "success", ("pairing", pairing_id)
            )

        self._store.transaction(create)
        return PairingTicket(
            pairing_id=pairing_id,
            secret=secret,
            label=clean_label,
            scopes=tuple(sorted(chosen)),
            expires_at=now + ttl,
            device_lifetime_days=device_lifetime_days,
        )

    def exchange(self, secret: str, *, correlation_id: str | None = None) -> PairedDevice | None:
        """Turn one live, unused pairing secret into a device credential; `None` otherwise.

        Unknown, expired, already used and malformed secrets all answer `None`, so a caller
        learns nothing about which pairings exist. A pairing whose owner was disabled in the
        meantime is used up without creating a device.
        """

        if not secret or len(secret) > MAX_PAIRING_SECRET_LENGTH:
            return None
        now = self._clock()

        def claim(session: TxSession) -> PairedDevice | None:
            pairing = self._store.claim_pairing(session, self._auth.digest(secret), now)
            if pairing is None:
                # No audit row: audit is append-only, and anyone who knows the URL could fill it.
                # The route counts the refusal instead (a content-free metric).
                return None
            if not self._store.user_is_active(session, pairing.user_id):
                self._audit(
                    session,
                    pairing.user_id,
                    "companion.pairing_exchanged",
                    "denied",
                    ("pairing", pairing.id),
                    reason="user_inactive",
                    correlation_id=correlation_id,
                )
                return None
            token = f"{DEVICE_TOKEN_PREFIX}{secrets.token_urlsafe(40)}"
            device = self._store.add_device(
                session,
                user_id=pairing.user_id,
                label=pairing.label,
                token_digest=self._auth.digest(token),
                scopes=sorted(frozenset(pairing.scopes) & COMPANION_SCOPES),
                expires_at=now + timedelta(days=pairing.device_lifetime_days),
                now=now,
            )
            self._store.link_pairing_to_device(session, pairing.id, device.id)
            self._audit(
                session,
                pairing.user_id,
                "companion.device_paired",
                "success",
                ("device", device.id),
                correlation_id=correlation_id,
            )
            return PairedDevice(token=token, device=_view(device))

        return self._store.transaction(claim)

    def list_devices(self, user_id: UUID) -> list[CompanionDeviceView]:
        return self._store.read(
            lambda session: [_view(row) for row in self._store.list_devices(session, user_id)]
        )

    def get_device(self, user_id: UUID, device_id: UUID) -> CompanionDeviceView | None:
        def get(session: TxSession) -> CompanionDeviceView | None:
            row = self._store.device(session, user_id, device_id)
            return None if row is None else _view(row)

        return self._store.read(get)

    def renew(
        self,
        user_id: UUID,
        device_id: UUID,
        presented_token: str,
        *,
        correlation_id: str | None = None,
    ) -> PairedDevice | None:
        """Give a device a fresh credential in place of the one it presented; `None` if that
        credential is not valid (unknown, expired, revoked, replaced or the owner disabled).

        The device row stays (same id, scopes and push subscription); it gets a new digest and an
        expiry of the pairing's lifetime from now. The row is locked, so two renewals at once are
        served one after the other and only the last token issued is valid. The presented token
        is checked again under that lock.

        The current credential may renew only in the last `RENEWAL_WINDOW` (`RenewalNotDue`
        otherwise). The credential just replaced may renew again during its grace window without
        that check (the answer to the first renewal may have been lost); that issues a further
        token, and the one the device never saw stops working. At most `MAX_RENEWALS_PER_DAY`
        succeed in 24 hours (`RenewalRateLimited`). The replaced credential stays valid for
        `RENEWAL_GRACE` or until the new one is first used.

        Renewing through the replaced credential is a deliberate trade-off: it lets a device redo
        a call whose answer was lost, but it could also be a stolen old token. The audit row then
        carries `reason="via_previous_token"` (never a token or digest). The exposure is bounded:
        the old token works for at most 10 minutes (`RENEWAL_GRACE`) and at most
        `MAX_RENEWALS_PER_DAY` (5) renewals succeed per 24 hours. As long as the pairing's
        `lifetime_days <= 7` the device is always renewable, since the renewal window then
        covers its whole lifetime.
        """

        now = self._clock()
        presented = self._auth.digest(presented_token)

        def renew(session: TxSession) -> PairedDevice | None:
            row = self._store.device(session, user_id, device_id, lock=True)
            if row is None or row.revoked_at is not None:
                return None
            if row.expires_at is None or row.expires_at <= now:
                return None
            if not self._store.user_is_active(session, user_id):
                return None
            replaced = (
                row.previous_token_digest == presented
                and row.previous_valid_until is not None
                and row.previous_valid_until > now
            )
            if row.token_digest != presented and not replaced:
                return None
            if not replaced and row.expires_at - now > RENEWAL_WINDOW:
                raise RenewalNotDue(row.expires_at - RENEWAL_WINDOW)
            recent = self._store.renewal_times_since(session, device_id, now - RENEWAL_RATE_WINDOW)
            if len(recent) >= MAX_RENEWALS_PER_DAY:
                free_at = recent[len(recent) - MAX_RENEWALS_PER_DAY] + RENEWAL_RATE_WINDOW
                raise RenewalRateLimited(max(1, int((free_at - now).total_seconds()) + 1))
            lifetime_days = self._store.pairing_lifetime_days(session, device_id)
            token = f"{DEVICE_TOKEN_PREFIX}{secrets.token_urlsafe(40)}"
            renewed = self._store.rotate_credential(
                session,
                device_id,
                token_digest=self._auth.digest(token),
                expires_at=now + timedelta(days=lifetime_days or DEFAULT_DEVICE_LIFETIME_DAYS),
                keep_previous_until=None if replaced else now + RENEWAL_GRACE,
            )
            self._audit(
                session,
                user_id,
                "companion.device_renewed",
                "success",
                ("device", device_id),
                reason=RENEWED_VIA_PREVIOUS_REASON if replaced else None,
                correlation_id=correlation_id,
                occurred_at=now,
            )
            return PairedDevice(token=token, device=_view(renewed))

        return self._store.transaction(renew)

    def grant_scopes(
        self, user_id: UUID, device_id: UUID, scopes: Iterable[str]
    ) -> CompanionDeviceView | None:
        """Add device capabilities to an already paired device (the operator's `grant`), so a new
        room does not need a new pairing. Only adds: a capability is removed by revoking the device.
        `None` for an unknown or revoked device; the device keeps its credential, expiry and push
        subscription."""

        chosen = frozenset(scopes)
        if not chosen or not chosen <= COMPANION_SCOPES:
            raise InvalidInputError(
                "companion scopes must be a non-empty subset of the device scopes"
            )

        def grant(session: TxSession) -> CompanionDeviceView | None:
            row = self._store.device(session, user_id, device_id, lock=True)
            if row is None or row.revoked_at is not None:
                return None
            added = sorted(chosen - frozenset(row.scopes))
            granted = self._store.set_scopes(session, device_id, frozenset(row.scopes) | chosen)
            # The audit table has no metadata column, so each scope that was really added gets its
            # own row (reason = the scope name, a fixed vocabulary, never text); a grant that
            # changes nothing leaves one row with reason "no_change".
            now = self._clock()
            for scope in added or [GRANT_NO_CHANGE_REASON]:
                self._audit(
                    session,
                    user_id,
                    "companion.device_scopes_granted",
                    "success",
                    ("device", device_id),
                    reason=scope,
                    occurred_at=now,
                )
            return _view(granted)

        return self._store.transaction(grant)

    def revoke_device(
        self,
        user_id: UUID,
        device_id: UUID,
        *,
        by_device: bool = False,
        correlation_id: str | None = None,
    ) -> bool:
        """Revoke one of this owner's devices. Idempotent; `False` only for an unknown device."""

        def revoke(session: TxSession) -> bool:
            row = self._store.device(session, user_id, device_id)
            if row is None:
                return False
            # The device's push subscription goes with it (D-078: push through UnifiedPush), also
            # when the credential was
            # already revoked: revoking again is idempotent and never leaves a live endpoint.
            self._store.revoke_push_subscription(session, user_id, device_id, self._clock())
            if row.revoked_at is None:
                self._store.mark_revoked(session, device_id, self._clock())
                self._audit(
                    session,
                    user_id,
                    "companion.device_unpaired" if by_device else "companion.device_revoked",
                    "success",
                    ("device", device_id),
                    correlation_id=correlation_id,
                )
            return True

        return self._store.transaction(revoke)

    def _audit(
        self,
        session: TxSession,
        actor_id: UUID | None,
        event: str,
        outcome: str,
        target: tuple[str, UUID] | None,
        *,
        reason: str | None = None,
        correlation_id: str | None = None,
        occurred_at: datetime | None = None,
    ) -> None:
        self._store.append_audit(
            session,
            actor_id,
            event,
            outcome,
            target,
            reason=reason,
            correlation_id=correlation_id,
            occurred_at=occurred_at if occurred_at is not None else utc_now(),
        )


def _clean_label(label: str) -> str:
    text = label.strip()
    if not text or len(text) > MAX_LABEL_LENGTH:
        raise InvalidInputError(f"device label must be 1 to {MAX_LABEL_LENGTH} characters")
    if any(not character.isprintable() for character in text):
        raise InvalidInputError("device label must not contain control characters")
    return text


def _view(row: DeviceRecord) -> CompanionDeviceView:
    if row.expires_at is None:  # a companion row always expires (database check)
        raise RuntimeError("companion device row without an expiry")
    return CompanionDeviceView(
        id=row.id,
        label=row.label,
        scopes=tuple(sorted(row.scopes)),
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        last_used_at=row.last_used_at,
        created_at=row.created_at,
    )
