"""Validation of the addresses in work.env: the model server URL and the extra allowlist.

Messages are in Swedish or English (the language of ``work.sh``), the same wording as the shell's own table.
"""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

# The gateway's own internal MCP port: no address may use it.
GATEWAY_MCP_PORT = 8765

_TEXT = {
    "sv": {
        "parse": "adressen kan inte tolkas: {error}",
        "scheme": "adressen måste börja med http:// eller https:// och ha en värd",
        "credentials": "adressen får inte innehålla inloggning, query eller fragment",
        "path": "adressen måste ha en sökväg, till exempel /v1",
        "format": "'{entry}': skriv värdnamn:port, till exempel embed.foretag.lan:443",
        "ip": "'{entry}': IP-adresser går inte att tillåta, använd ett värdnamn",
        "used": "'{entry}': porten {port} används redan (modellservern, MCP eller en annan post)",
    },
    "en": {
        "parse": "the address cannot be parsed: {error}",
        "scheme": "the address must start with http:// or https:// and have a host",
        "credentials": "the address must not contain credentials, a query or a fragment",
        "path": "the address needs a path, for example /v1",
        "format": "'{entry}': write host:port, for example embed.company.lan:443",
        "ip": "'{entry}': IP addresses cannot be allowed, use a host name",
        "used": "'{entry}': port {port} is already used (the model server, MCP or another entry)",
    },
}


class AddressError(ValueError):
    """The address is unusable; the message is the reason, already in the user's language."""


class BaseUrl:
    """A model server URL split into the parts ``derive`` needs."""

    def __init__(self, scheme: str, host: str, port: int, path: str, is_ip: bool) -> None:
        self.scheme = scheme
        self.host = host
        self.port = port
        self.path = path
        self.is_ip = is_ip

    def lines(self) -> list[str]:
        """Scheme, host, port, path and is_ip ("1"/"0"), the order ``work.sh`` reads them in."""
        return [self.scheme, self.host, str(self.port), self.path, "1" if self.is_ip else "0"]


def parse_base_url(raw: str, lang: str = "sv") -> BaseUrl:
    """Split SIDEKICK_WORK_MODEL_BASE_URL; raises AddressError with the reason."""
    text = _TEXT[lang]
    try:
        parts = urlsplit(raw.strip())
        host = parts.hostname
        port = parts.port
    except ValueError as error:
        raise AddressError(text["parse"].format(error=error)) from error
    if parts.scheme not in ("http", "https") or not host:
        raise AddressError(text["scheme"])
    if parts.username or parts.password or parts.query or parts.fragment:
        raise AddressError(text["credentials"])
    path = parts.path.rstrip("/")
    if not path:
        raise AddressError(text["path"])
    try:
        ipaddress.ip_address(host)
        is_ip = True
    except ValueError:
        is_ip = False
    return BaseUrl(parts.scheme, host, port or (443 if parts.scheme == "https" else 80), path, is_ip)


def parse_allowlist(raw: str, model_port: int, lang: str = "sv") -> list[tuple[str, int]]:
    """Validate "host:port,host:port": host names only (they become names on the internal network, so the
    client keeps its own name and certificate check), ports distinct from each other and from the two the
    gateway already uses. Returns (host, port) pairs; raises AddressError with the reason."""
    text = _TEXT[lang]
    entries = [e.strip().lower() for e in raw.replace(" ", ",").split(",") if e.strip()]
    used = {GATEWAY_MCP_PORT, model_port}
    seen: list[tuple[str, int]] = []
    for entry in entries:
        match = re.fullmatch(r"([a-z0-9]([a-z0-9.-]*[a-z0-9])?):([0-9]{1,5})", entry)
        if not match or not 0 < int(match.group(3)) < 65536:
            raise AddressError(text["format"].format(entry=entry))
        if re.fullmatch(r"[0-9.]+", match.group(1)):
            raise AddressError(text["ip"].format(entry=entry))
        port = int(match.group(3))
        if port in used:
            raise AddressError(text["used"].format(entry=entry, port=port))
        used.add(port)
        seen.append((match.group(1), port))
    return seen
