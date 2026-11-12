"""Everything compose needs, derived from ``work.env``: the model server's port, path, upstream address,
Host header and TLS options for the gateway, the memory switch, the allowlist and the trust store.

``work.sh`` exports what :func:`derive` returns. Strict by default: a placeholder or a bad address is an error
with a message in the user's language. With ``lenient`` (``stop``) an unusable ``work.env`` is not an error,
because compose then only needs the names to parse.
"""

from __future__ import annotations

import contextlib
import os
import platform
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import BinaryIO, NamedTuple

from . import addresses, messages
from .workenv import env_value, memory_wanted

SYSTEM_CA_BUNDLE = Path("/etc/ssl/certs/ca-certificates.crt")
MACOS_KEYCHAINS = (
    "/Library/Keychains/System.keychain",
    "/System/Library/Keychains/SystemRootCertificates.keychain",
)
# Used when no model server is configured (memory off, or an unusable work.env while stopping): the gateway
# gets a listener that never connects.
PLACEHOLDERS = {
    "SIDEKICK_WORK_MODEL_PORT": "1",
    "SIDEKICK_WORK_MODEL_PATH": "/v1",
    "SIDEKICK_WORK_UPSTREAM_ADDR": "unset:1",
    "SIDEKICK_WORK_UPSTREAM_HOST_HEADER": "unset",
    "SIDEKICK_WORK_UPSTREAM_TLS": "",
    "SIDEKICK_WORK_MEMORY_MODEL": "unset",
}


class DeriveError(Exception):
    """work.env cannot be used; the message is the reason, already in the user's language."""


class Derived(NamedTuple):
    memory: bool
    exports: dict[str, str]
    allow: list[tuple[str, int]]

    def lines(self) -> list[str]:
        """What ``work.sh`` reads: ``MEMORY=0|1``, ``NAME=value`` to export, and ``allow <host> <port>``."""
        return [
            f"MEMORY={int(self.memory)}",
            *(f"{name}={value}" for name, value in self.exports.items()),
            *(f"allow {host} {port}" for host, port in self.allow),
        ]


def _export_keychain(handle: BinaryIO) -> None:
    """Write the macOS keychain certificates (PEM) to ``handle``; a failed export leaves it empty."""
    security = shutil.which("security")
    if security is None:
        return
    with contextlib.suppress(OSError):
        subprocess.run(  # noqa: S603 - fixed arguments, the tool found on PATH
            [security, "find-certificate", "-a", "-p", *MACOS_KEYCHAINS],
            stdout=handle,
            stderr=subprocess.DEVNULL,
            check=False,
        )


def ca_bundle(
    configured: str,
    gen_dir: Path,
    system_bundle: Path = SYSTEM_CA_BUNDLE,
    system_name: str = "",
) -> str:
    """The trust store the gateway uses for an https model server.

    Linux: the system bundle (a company CA installed on Ubuntu is in it). macOS has no such file: the keychain
    certificates are exported into a bundle in ``gen_dir``. Anywhere else the bundle is empty.
    """
    if configured:
        return configured
    if system_bundle.is_file():
        return str(system_bundle)
    gen_dir.mkdir(parents=True, exist_ok=True)
    bundle = gen_dir / "ca-bundle.pem"
    with bundle.open("wb") as handle:
        if (system_name or platform.system()) == "Darwin":
            _export_keychain(handle)
    gen_dir.chmod(0o755)
    bundle.chmod(0o644)
    return str(bundle)


def _placeholders(gen_dir: Path, configured_ca: str, **overrides: str) -> dict[str, str]:
    exports = {**PLACEHOLDERS, **overrides}
    exports["SIDEKICK_WORK_CA_BUNDLE"] = ca_bundle(configured_ca, gen_dir)
    return exports


def _parsed_allowlist(env_file: Path, model_port: int, lang: str, lenient: bool) -> list[tuple[str, int]]:
    try:
        return addresses.parse_allowlist(env_value(env_file, "SIDEKICK_WORK_ALLOW"), model_port, lang)
    except addresses.AddressError as error:
        if lenient:
            return []
        raise DeriveError(f"SIDEKICK_WORK_ALLOW: {error}") from error


def _upstream(url: addresses.BaseUrl, resolve_ip: str) -> dict[str, str]:
    """The gateway's upstream address, the Host header and the TLS options the model server's URL calls for."""
    addr = resolve_ip or url.host
    if ":" in addr:
        addr = f"[{addr}]"
    host_header = f"[{url.host}]" if ":" in url.host else url.host
    if url.port != (443 if url.scheme == "https" else 80):
        host_header = f"{host_header}:{url.port}"
    tls = ""
    if url.scheme == "https":
        tls = f"ssl verify required ca-file /etc/ssl/work-ca.pem verifyhost {url.host}"
        if not url.is_ip:
            tls += f" sni str({url.host})"
    return {
        "SIDEKICK_WORK_MODEL_PORT": str(url.port),
        "SIDEKICK_WORK_MODEL_PATH": url.path,
        "SIDEKICK_WORK_UPSTREAM_ADDR": f"{addr}:{url.port}",
        "SIDEKICK_WORK_UPSTREAM_HOST_HEADER": host_header,
        "SIDEKICK_WORK_UPSTREAM_TLS": tls,
    }


def derive(
    env_file: Path,
    gen_dir: Path,
    lang: str,
    lenient: bool = False,
    environ: Mapping[str, str] = os.environ,
) -> Derived:
    """Raises :class:`DeriveError` when the values are unusable and ``lenient`` is off."""
    configured_ca = env_value(env_file, "SIDEKICK_WORK_CA_BUNDLE")
    if not memory_wanted(env_file):
        # No model server: the gateway keeps only the MCP port, Hindsight and the memory worker are not started
        # (compose profile) and Sidekick's memory is off.
        allow = _parsed_allowlist(env_file, 0, lang, lenient)
        exports = _placeholders(gen_dir, configured_ca, SIDEKICK_WORK_MEMORY_ENABLED="false")
        return Derived(False, exports, allow)
    base = env_value(env_file, "SIDEKICK_WORK_MODEL_BASE_URL")
    if not base or "<" in base:
        if lenient:
            return Derived(True, _placeholders(gen_dir, configured_ca, SIDEKICK_WORK_MEMORY_ENABLED="true"), [])
        raise DeriveError(messages.text(lang, "url_unset") + "\n" + messages.text(lang, "url_unset_hint"))
    try:
        url = addresses.parse_base_url(base, lang)
    except addresses.AddressError as error:
        if lenient:
            return Derived(True, _placeholders(gen_dir, configured_ca, SIDEKICK_WORK_MEMORY_ENABLED="true"), [])
        raise DeriveError(f"SIDEKICK_WORK_MODEL_BASE_URL: {error}") from error
    if url.port == addresses.GATEWAY_MCP_PORT:
        raise DeriveError(messages.text(lang, "port_clash"))
    allow = _parsed_allowlist(env_file, url.port, lang, lenient)
    # work.env is also compose's --env-file; these exports win over it, which is the point.
    memory_model = environ.get("SIDEKICK_WORK_MEMORY_MODEL") or env_value(env_file, "SIDEKICK_WORK_MEMORY_MODEL")
    if not lenient and (not memory_model or "<" in memory_model):
        raise DeriveError(messages.text(lang, "mem_unset"))
    exports = {
        **_upstream(url, env_value(env_file, "SIDEKICK_WORK_MODEL_RESOLVE_IP")),
        "SIDEKICK_WORK_MEMORY_ENABLED": "true",
        "SIDEKICK_WORK_MEMORY_MODEL": memory_model,
        "SIDEKICK_WORK_CA_BUNDLE": ca_bundle(configured_ca, gen_dir),
    }
    return Derived(True, exports, allow)
