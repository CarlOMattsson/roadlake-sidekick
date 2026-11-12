"""One rule for reaching a private service Sidekick does not own.

This exists because there were two. `Settings` validated the Hindsight base URL with an
explicit loopback exemption, and the memory adapter validated it again with a near-identical
copy that had no such exemption. The result was a destination configuration accepted and the
adapter then refused: `http://127.0.0.1:18888` passed startup validation and raised inside the
provider constructor.

Two statements of one rule is what caused that, so there is now one statement, checked in
both places. The loopback exemption is a parameter rather than a second function, because the
only mode that may reach loopback is local development, where the local stack publishes
the service on loopback.
"""

from __future__ import annotations

from ipaddress import IPv6Address, ip_address
from urllib.parse import urlsplit

#: Hosts that are private by name rather than by address: the Compose service name Sidekick's
#: own deployment uses, and the two suffixes reserved for local networks.
PRIVATE_SERVICE_HOST = "hindsight"
PRIVATE_HOST_SUFFIXES = (".internal", ".local")


def private_host(host: str, *, allow_loopback: bool = False) -> bool:
    """Whether a host is an approved private destination for a Sidekick-owned service."""

    normalized = host.casefold().rstrip(".")
    if not normalized:
        return False
    try:
        address = ip_address(normalized)
    except ValueError:
        return normalized == PRIVATE_SERVICE_HOST or normalized.endswith(PRIVATE_HOST_SUFFIXES)
    if isinstance(address, IPv6Address) and address.ipv4_mapped is not None:
        # ::ffff:a.b.c.d reaches the same IPv4 host, so it is judged as that host.
        address = address.ipv4_mapped
    if address.is_link_local:
        # 169.254.0.0/16 and fe80::/10 carry the cloud metadata service: never a private host.
        return False
    if address.is_loopback or address.is_unspecified:
        # 0.0.0.0 and :: reach the local host, so they are loopback-class, not private.
        return allow_loopback
    return address.is_private


def validate_private_base_url(
    value: str, *, label: str = "Hindsight", allow_loopback: bool = False
) -> str:
    """Validate a private service base URL and return it without a trailing slash.

    `allow_loopback` is granted only by development mode, whose local stack publishes the
    service on loopback. Every other rule is unchanged from the two copies this replaced,
    including the refusal of a path, so a caller cannot smuggle a different endpoint into the
    base.
    """

    parsed = urlsplit(value)
    host = parsed.hostname
    if parsed.scheme not in {"http", "https"} or not host:
        raise ValueError(f"{label} base URL must use HTTP(S) with a host")
    if parsed.username or parsed.password or parsed.path not in {"", "/"}:
        raise ValueError(f"{label} base URL cannot contain credentials or a path")
    if parsed.query or parsed.fragment:
        raise ValueError(f"{label} base URL cannot contain query or fragment data")
    if not private_host(host, allow_loopback=allow_loopback):
        raise ValueError(f"{label} base URL must target an approved private host")
    return value.rstrip("/")
