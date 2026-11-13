"""The checks of ``tools/drill.sh``: the extra reserved ports, the image pair, the free port, the digest of a push
and the versions of a release. drill.sh runs the commands and acts on their exit status and output.

Standard library only; it runs with the host's ``python3 -I``. The default reserved ports, the project name rule and
everything that decides what the cleanup may remove stay in drill.sh, where a test reads them as text.

Exit status: 0 success, 1 nothing found (a digest, a free port), 2 the input was refused (the reason is on stderr).
"""

from __future__ import annotations

import argparse
import random
import re
import socket
import sys
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
    refusal = Refused(
        "SIDEKICK_RESERVED_PORTS must be comma-separated TCP ports (1-65535)"
    )
    if not EXTRA_PORTS_ALLOWED.fullmatch(value):
        raise refusal
    ports = []
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
        raise Refused(
            "drill: images must be pinned by digest (REGISTRY/REPO@sha256:<64 hex>); update.sh refuses a tag"
        )
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


def release_versions(pyproject: Path) -> tuple[str, str]:
    """The version of the source and the next patch version, from ``pyproject.toml``."""
    import tomllib

    with pyproject.open("rb") as handle:
        major, minor, patch = tomllib.load(handle)["project"]["version"].split(".")
    return f"{major}.{minor}.{patch}", f"{major}.{minor}.{int(patch) + 1}"


def _ports(text: str) -> list[int]:
    return [int(item) for item in text.replace(",", " ").split()]


def _cmd_reserved_ports(args: argparse.Namespace) -> int:
    for port in extra_reserved_ports(args.value):
        print(port)
    return 0


def _cmd_image_pair(args: argparse.Namespace) -> int:
    check_image_pair(args.from_image, args.to_image)
    return 0


def _cmd_pick_port(args: argparse.Namespace) -> int:
    port = pick_port(_ports(args.reserved), _ports(args.used))
    if port is None:
        print("drill: no free port found", file=sys.stderr)
        return 1
    print(port)
    return 0


def _cmd_pushed_digest(_args: argparse.Namespace) -> int:
    digest = pushed_digest(sys.stdin.read())
    if digest is None:
        return 1
    print(digest)
    return 0


def _cmd_release_versions(args: argparse.Namespace) -> int:
    print(" ".join(release_versions(args.pyproject)))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="drill_policy", description="The checks of tools/drill.sh."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    sub = commands.add_parser(
        "reserved-ports", help="print the normalised extra reserved ports, one per line"
    )
    sub.set_defaults(handler=_cmd_reserved_ports)
    sub.add_argument("value")

    sub = commands.add_parser(
        "image-pair", help="exit 2 with the reason unless the two images may be drilled"
    )
    sub.set_defaults(handler=_cmd_image_pair)
    sub.add_argument("--from", dest="from_image", default="")
    sub.add_argument("--to", dest="to_image", default="")

    sub = commands.add_parser(
        "pick-port", help="print a random free port; exit 1 when none was found"
    )
    sub.set_defaults(handler=_cmd_pick_port)
    sub.add_argument("--reserved", default="", help="space or comma separated")
    sub.add_argument("--used", default="", help="space or comma separated")

    sub = commands.add_parser(
        "pushed-digest", help="print the digest of the docker push output on stdin"
    )
    sub.set_defaults(handler=_cmd_pushed_digest)

    sub = commands.add_parser(
        "release-versions",
        help="print 'version next-patch-version' of a pyproject.toml",
    )
    sub.set_defaults(handler=_cmd_release_versions)
    sub.add_argument("pyproject", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except Refused as refusal:
        print(refusal, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
