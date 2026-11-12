"""Egress probe of ``work.sh status``. It runs INSIDE a container, not on the host: ``work.sh`` passes the file's
text to ``python -c`` in the api and hindsight containers, so it uses the standard library only and works on any
Python 3.9 or newer.

Each line says whether a way out is open: the public internet by name and by address, a lookup of a name that
certainly exists (an answer means DNS is a way out) and, when asked, the model server directly (only the gateway
may talk to it). The words for "reached" and "blocked" are passed in, so the host's language decides the output.

Arguments: direct host (empty = skip), its port, the word for reached, the word for blocked, the label of the
direct line.
"""

from __future__ import annotations

import socket
import sys
from collections.abc import Callable, Sequence
from typing import Any

TIMEOUT_SECONDS = 4


def reach(
    host: str, port: object, reached: str, blocked: str, connect: Callable[..., Any] = socket.create_connection
) -> str:
    try:
        connect((host, int(str(port))), timeout=TIMEOUT_SECONDS).close()
        return reached
    except OSError:
        return blocked


def probe(
    direct_host: str,
    direct_port: object,
    reached: str,
    blocked: str,
    direct_label: str,
    connect: Callable[..., Any] = socket.create_connection,
    lookup: Callable[..., Any] = socket.getaddrinfo,
) -> list[str]:
    lines = [
        f"example.com:443 {reach('example.com', 443, reached, blocked, connect)}",
        f"1.1.1.1:443 {reach('1.1.1.1', 443, reached, blocked, connect)}",
    ]
    try:
        lookup("example.com", 443)
        lines.append(f"DNS lookup of example.com {reached}")
    except OSError as error:
        lines.append(f"DNS lookup of example.com {blocked} ({error.errno})")
    if direct_host:
        lines.append(f"{direct_label} {reach(direct_host, direct_port, reached, blocked, connect)}")
    return lines


def main(argv: Sequence[str]) -> None:
    host, port, reached, blocked, label = argv[1:6]
    print("\n".join(probe(host, port, reached, blocked, label)))


if __name__ == "__main__":
    main(sys.argv)
