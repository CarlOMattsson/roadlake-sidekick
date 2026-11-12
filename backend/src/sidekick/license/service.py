"""The instance's license: where the key is stored, what state it is in today, and who may set it.

One row for the whole installation (`sidekick.instance_license`, 0.1.0 baseline). Setting a key
verifies it first and stores only a key that verifies (`licensed` or `expired`), so a typo never
replaces a good key. The state is evaluated on every read against the larger of the clock and the
highest date the instance has seen, so turning the clock back revives nothing. One wrong jump
forward would otherwise lock a valid key out for good, so a date more than `MAX_FORWARD_JUMP` past
the highest seen is not remembered (the operator's `reset-clock` sets it to today).

Authorization. A key is an instance setting and Sidekick has no administrator role, so the person
who may set it through a user channel (MCP, the companion app) is the installation's only active
user. With more than one user the request is refused and the operator uses the command line
(`python -m sidekick.license.cli`), which is the operator's own access to the host.

Logs and audit carry closed vocabulary only: the event, the state, a reason and the correlation
id. Never the key, the signature, the licensee or the key id. A refused attempt (a key that does not
verify, a user who is not the owner) is audited once per actor and reason within `AUDIT_DEDUPE`, so
repeated attempts cannot flood the audit trail.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from sidekick.license.key import (
    UNLICENSED,
    Evaluation,
    KeyRejected,
    LicenseView,
    RejectReason,
    evaluate,
    normalize,
    parse_public_key,
    verify_key,
)
from sidekick.license.persistence import LicenseStore, StoreUnavailable
from sidekick.license.public_key import DEFAULT_LICENSE_PUBLIC_KEY, PLACEHOLDER_PUBLIC_KEY
from sidekick.shared.errors import PermissionDeniedError
from sidekick.shared.observability import safe_log_fields
from sidekick.shared.types import TxSession, utc_now

LOGGER = logging.getLogger("sidekick.license")
MAX_FORWARD_JUMP = timedelta(days=400)
AUDIT_DEDUPE = timedelta(seconds=60)


@dataclass(frozen=True, slots=True)
class SetOutcome:
    """The result of entering a key: whether it was accepted and the display state afterwards.
    A rejected key changes nothing, so `view` is then the state of the key already stored."""

    accepted: bool
    view: LicenseView


class LicenseService:
    def __init__(
        self,
        store: LicenseStore,
        public_key: str | None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        """`public_key` None means the repository default, `DEFAULT_LICENSE_PUBLIC_KEY`."""
        if public_key is None:
            public_key = DEFAULT_LICENSE_PUBLIC_KEY
        self._store = store
        self._public_key: Ed25519PublicKey | None = parse_public_key(public_key)
        self._clock = clock
        self._last_logged: tuple[str, RejectReason | None] | None = None
        self._rollback_logged = False
        self._jump_logged = False
        if self._public_key is None:
            _log(
                "license_public_key_unusable",
                license_reason="placeholder"
                if public_key.strip() == PLACEHOLDER_PUBLIC_KEY
                else "invalid",
            )

    def view(self) -> LicenseView:
        """The display state today. Raises on a database failure; `display` does not."""

        today, key = self._store.transaction(self._observe)
        evaluation = evaluate(key, self._public_key, today)
        self._log_evaluation(evaluation)
        return evaluation.view

    def display(self) -> LicenseView:
        """The state for a page or a bootstrap answer, which must never fail because of the
        license: when the database cannot answer, the safe reading is `unlicensed`."""

        try:
            return self.view()
        except StoreUnavailable:
            _log("license_unavailable", license_reason="database")
            return UNLICENSED

    def set_by_owner(
        self, user_id: UUID, raw_key: str, *, correlation_id: str | None = None
    ) -> SetOutcome:
        """`set_key` for a user channel: refused with `PermissionDeniedError` unless `user_id` is
        the installation's only active user."""

        owners = self._store.transaction(lambda session: self._store.active_user_ids(session, 2))
        if owners != [user_id]:
            self._store.transaction(
                lambda session: self._audit_denied(session, user_id, "not_owner", correlation_id)
            )
            _log(
                "license_rejected",
                license_reason="not_owner",
                correlation_id=correlation_id,
                outcome="denied",
            )
            raise PermissionDeniedError("the license key can be set by the instance's only owner")
        return self.set_key(raw_key, actor_id=user_id, correlation_id=correlation_id)

    def set_key(
        self, raw_key: str, *, actor_id: UUID | None = None, correlation_id: str | None = None
    ) -> SetOutcome:
        """Store the key when it verifies against the instance's public key (expired or not).

        Entering the key already stored changes and audits nothing. A key that does not verify is
        audited as denied with its closed reason and leaves the stored key alone.
        """

        now = self._clock()

        def execute(session: TxSession) -> SetOutcome:
            today, stored = self._observe(session)
            try:
                if self._public_key is None:
                    raise KeyRejected("no_public_key")
                text = normalize(raw_key)
                verify_key(text, self._public_key)
            except KeyRejected as rejected:
                self._audit_denied(session, actor_id, rejected.rejection, correlation_id)
                _log(
                    "license_rejected",
                    license_reason=rejected.rejection,
                    correlation_id=correlation_id,
                    outcome="denied",
                )
                return SetOutcome(False, evaluate(stored, self._public_key, today).view)
            if text != stored:
                self._store.write_key(session, text, now)
                self._store.append_audit(
                    session, actor_id, "license.set", "success", None, correlation_id
                )
            return SetOutcome(True, evaluate(text, self._public_key, today).view)

        outcome = self._store.transaction(execute)
        if outcome.accepted:
            _log(
                "license_set",
                license_state=outcome.view.state,
                correlation_id=correlation_id,
                outcome="success",
            )
        return outcome

    def clear(self, *, correlation_id: str | None = None) -> bool:
        """Remove the stored key (the operator's command). `False` when there was none."""

        now = self._clock()

        def execute(session: TxSession) -> bool:
            _today, stored = self._observe(session)
            if stored is None:
                return False
            self._store.write_key(session, None, now)
            self._store.append_audit(
                session, None, "license.cleared", "success", None, correlation_id
            )
            return True

        if not self._store.transaction(execute):
            return False
        _log("license_cleared", correlation_id=correlation_id, outcome="success")
        return True

    def reset_clock(self, *, correlation_id: str | None = None) -> None:
        """Set the highest date seen to today's (the operator's command), for an instance whose
        clock once ran far ahead or whose stored date is wrong. Audited."""

        now = self._clock()

        def execute(session: TxSession) -> None:
            self._store.remember_seen(session, now.astimezone(UTC).date(), now, force=True)
            self._store.append_audit(
                session, None, "license.clock_reset", "success", None, correlation_id
            )

        self._store.transaction(execute)
        self._rollback_logged = self._jump_logged = False
        _log("license_clock_reset", correlation_id=correlation_id, outcome="success")

    def _observe(self, session: TxSession) -> tuple[date, str | None]:
        """Today as the expiry check counts it, and the stored key. Raises the highest date seen
        when the clock is behind it; writes only when a later date has been reached (once a day).
        A date far past the highest seen is used for today's check but not remembered."""

        now = self._clock()
        clock_day = now.astimezone(UTC).date()
        row = self._store.read(session)
        stored = row.key if row is not None else None
        seen = row.max_seen_on if row is not None else None
        if seen is not None and clock_day < seen:
            if not self._rollback_logged:
                self._rollback_logged = True
                _log("license_clock_behind", license_reason="clock_rollback")
            return seen, stored
        if seen is not None and clock_day - seen > MAX_FORWARD_JUMP:
            if not self._jump_logged:
                self._jump_logged = True
                _log("license_clock_ahead", license_reason="clock_jump_ignored")
            return clock_day, stored
        if seen is None or clock_day > seen:
            self._store.remember_seen(session, clock_day, now, force=False)
        return clock_day, stored

    def _audit_denied(
        self, session: TxSession, actor_id: UUID | None, reason: str, correlation_id: str | None
    ) -> None:
        """Audit a refused `license.set`, unless the same actor was refused for the same reason
        within `AUDIT_DEDUPE` (a retrying client, a guessing one)."""

        if not self._store.denied_since(session, actor_id, reason, utc_now() - AUDIT_DEDUPE):
            self._store.append_audit(
                session, actor_id, "license.set", "denied", reason, correlation_id
            )

    def _log_evaluation(self, evaluation: Evaluation) -> None:
        """Log an `invalid` key (or an unusable public key) once per change, with its reason."""

        marker = (evaluation.view.state, evaluation.reason)
        if evaluation.reason is None or marker == self._last_logged:
            return
        self._last_logged = marker
        _log(
            "license_not_verified",
            license_state=evaluation.view.state,
            license_reason=evaluation.reason,
        )


def _log(message: str, **fields: object) -> None:
    LOGGER.info(message, extra=safe_log_fields(fields))
