"""The checks of ``tools/drill.sh``: the extra reserved ports, the image pair, the free port, the digest of a push
and the versions of a release. drill.sh runs the ``drill-*`` commands of workctl and acts on their exit status and
output. The default reserved ports, the project name rule and everything that decides what the cleanup may remove
stay in drill.sh, where a test reads them as text.

``release_versions`` reads ``pyproject.toml`` with ``tomllib`` (Python 3.11+), which the drill host has.
"""

from __future__ import annotations

import random
import re
import socket
from collections.abc import Callable, Sequence
from pathlib import Path

LOW_PORT, HIGH_PORT = 1, 65535
PICK_RANGE = (20000, 39999)
PICK_ATTEMPTS = 50
IMAGE = re.compile(r"[a-z0-9][a-z0-9._:/-]*@sha256:[0-9a-f]{64}")
EXTRA_PORTS_ALLOWED = re.compile(r"[0-9, ]*")
PUSHED_DIGEST = re.compile(r".*digest: (sha256:[0-9a-f]{64})")


class Refused(Exception):
    """The input is refused; the message is the reason, as drill.sh prints it."""


def extra_reserved_ports(value: str) -> list[int]:
    """The ports of a comma separated ``SIDEKICK_RESERVED_PORTS``: digits, commas and blanks only (a newline is not
    a blank here), each between 1 and 65535, normalised to decimal. Empty items are skipped."""
    refusal = Refused("SIDEKICK_RESERVED_PORTS must be comma-separated TCP ports (1-65535)")
    if not EXTRA_PORTS_ALLOWED.fullmatch(value):
        raise refusal
    ports: list[int] = []
    for item in value.split(","):
        item = item.replace(" ", "")
        if not item:
            continue
        port = int(item)
        if not LOW_PORT <= port <= HIGH_PORT:
            raise refusal
        ports.append(port)
    return ports


def check_image_pair(from_image: str, to_image: str) -> None:
    """The two images of a real run: both given, pinned by digest, and different."""
    if not from_image or not to_image:
        raise Refused(
            "drill: --from-image and --to-image (or DRILL_FROM_IMAGE and DRILL_TO_IMAGE) are required, "
            "or --local-images"
        )
    if not IMAGE.fullmatch(from_image) or not IMAGE.fullmatch(to_image):
        raise Refused("drill: images must be pinned by digest (REGISTRY/REPO@sha256:<64 hex>); update.sh refuses a tag")
    if from_image == to_image:
        raise Refused("drill: --from-image and --to-image must differ")


def listening(port: int) -> bool:
    """Whether something accepts connections on 127.0.0.1:``port``."""
    with socket.socket() as probe:
        probe.settimeout(1)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def pick_port(
    reserved: Sequence[int],
    used: Sequence[int],
    is_listening: Callable[[int], bool] = listening,
) -> int | None:
    """A random port that is not reserved, not picked before and not listening, or ``None`` after 50 tries."""
    for _ in range(PICK_ATTEMPTS):
        port = random.randint(*PICK_RANGE)  # noqa: S311 - a port to publish on, not a secret
        if port not in reserved and port not in used and not is_listening(port):
            return port
    return None


def pushed_digest(output: str) -> str | None:
    """The digest ``docker push`` reported last, or ``None``."""
    found = None
    for line in output.splitlines():
        match = PUSHED_DIGEST.match(line)
        if match:
            found = match.group(1)
    return found


def parse_ports(text: str) -> list[int]:
    """The ports of a space or comma separated list."""
    return [int(item) for item in text.replace(",", " ").split()]


def release_versions(pyproject: Path) -> tuple[str, str]:
    """The version of the source and the next patch version, from ``pyproject.toml``."""
    import tomllib

    with pyproject.open("rb") as handle:
        major, minor, patch = tomllib.load(handle)["project"]["version"].split(".")
    return f"{major}.{minor}.{patch}", f"{major}.{minor}.{int(patch) + 1}"
