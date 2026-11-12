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
from typing import Protocol
from urllib.parse import urlsplit
from uuid import UUID

from sidekick.shared.config import Settings
from sidekick.shared.errors.core import NotFoundError, ValidationError
from sidekick.shared.types import utc_now

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


class PushSubscriptionStore(Protocol):
    def subscribe(
        self,
        user_id: UUID,
        device_id: UUID,
        endpoint: str,
        host: str,
        now: datetime,
        correlation_id: str | None,
    ) -> bool:
        """Register (or replace) the device's endpoint and audit it. False without a pairing."""
        ...

    def unsubscribe(
        self, user_id: UUID, device_id: UUID, now: datetime, correlation_id: str | None
    ) -> bool: ...

    def active_endpoint_host(self, user_id: UUID, device_id: UUID) -> str | None: ...


class PushSubscriptionService:
    def __init__(
        self,
        store: PushSubscriptionStore,
        allowed_hosts: Callable[[], Collection[str]],
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        # The hosts are looked up when an endpoint is registered, so a process that builds the
        # service but never serves a registration (the automation worker) reads no push setting.
        self._store = store
        self._allowed_hosts = allowed_hosts
        self._clock = clock

    @classmethod
    def from_settings(
        cls, store: PushSubscriptionStore, settings: Settings
    ) -> PushSubscriptionService:
        return cls(store, lambda: settings.push_allowed_host_set)

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

        host = validate_endpoint(endpoint, self._allowed_hosts())
        if not self._store.subscribe(
            user_id, device_id, endpoint, host, self._clock(), correlation_id
        ):
            raise PairingNotFound
        return host

    def unsubscribe(
        self, user_id: UUID, device_id: UUID, *, correlation_id: str | None = None
    ) -> bool:
        """Revoke the device's active subscription. Idempotent; `False` when there was none."""

        return self._store.unsubscribe(user_id, device_id, self._clock(), correlation_id)

    def active_endpoint_host(self, user_id: UUID, device_id: UUID) -> str | None:
        """The host of the device's active subscription, for tests and status; never the URL."""

        return self._store.active_endpoint_host(user_id, device_id)
