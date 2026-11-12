#!/usr/bin/env python3
"""Refuse a release while the licensor's license public key is still the placeholder (D-081).

`DEFAULT_LICENSE_PUBLIC_KEY` in backend/src/sidekick/license/public_key.py decides which license
keys a build accepts. With the placeholder every key is "unlicensed", which is wrong for a
published release image. The release workflow runs
this check before it builds anything; nothing else does.

Usage:
    tools/check-license-public-key.py [--file PATH]

The value must be a string literal that is base64 of a raw 32-byte Ed25519 public key, must not
carry the private-key marker, and must decode to a valid Ed25519 point (RFC 8032 section 5.1.3:
canonical y, and x^2 has a square root; the neutral and small-order points are refused too).
What this cannot do: about half of all random 32-byte values are valid points, so a bare private
seed can still pass. Preventing that is the job of the licensor's own key tooling (private, and not
part of this repository); this check only catches the marker and malformed values.
The check reads the file as source (ast) and never imports it, so it needs no backend environment.

Exit code 0 = a real key is set, 1 = placeholder or not a valid key, 2 = the file cannot be read.
Uses only the standard library; no database, no network.
"""

from __future__ import annotations

import argparse
import ast
import base64
import binascii
import sys
from pathlib import Path

DEFAULT_FILE = (
    Path(__file__).resolve().parents[1] / "backend/src/sidekick/license/public_key.py"
)
NAME = "DEFAULT_LICENSE_PUBLIC_KEY"
KEY_BYTES = 32
PRIVATE_KEY_MARKER = "ROADLAKE-LICENSE-PRIVATE-KEY-1:"
_P = 2**255 - 19
_D = -121665 * pow(121666, -1, _P) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)


def configured_value(source: str) -> str | None:
    """The string literal assigned to `DEFAULT_LICENSE_PUBLIC_KEY`, or None when it is anything
    else (such as the name `PLACEHOLDER_PUBLIC_KEY`)."""

    for node in ast.parse(source).body:
        if isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        else:
            continue
        if isinstance(target, ast.Name) and target.id == NAME:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                return value.value
            return None
    return None


def is_valid_point(raw: bytes) -> bool:
    """True when `raw` decodes to an Ed25519 point of order above 1 (RFC 8032 decoding)."""

    number = int.from_bytes(raw, "little")
    sign, y = number >> 255, number & (2**255 - 1)
    if y >= _P:
        return False
    numerator, denominator = (y * y - 1) % _P, (_D * y * y + 1) % _P
    x2 = numerator * pow(denominator, -1, _P) % _P
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P:
        return False
    if x == 0 and sign:
        return False
    if sign != x & 1:
        x = -x % _P
    # Small-order points (order 1, 2, 4, 8) are never a real licensor key: multiply by 8 and
    # check that the result is not the neutral element.
    point = (x, y, 1, x * y % _P)
    for _ in range(3):
        point = _double(point)
    return point[0] % _P != 0 or (point[1] - point[2]) % _P != 0


def _double(point: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Doubling in extended coordinates for a = -1 (dbl-2008-hwcd)."""

    x, y, z, _ = point
    a, b, c = x * x % _P, y * y % _P, 2 * z * z % _P
    e = ((x + y) ** 2 - a - b) % _P
    g = (b - a) % _P
    f = (g - c) % _P
    h = (-a - b) % _P
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def problem(source: str) -> str | None:
    """Why the source does not carry a usable public key, or None when it does."""

    value = configured_value(source)
    if value is None:
        return f"{NAME} is not set to a public key (still the placeholder)"
    if PRIVATE_KEY_MARKER in value or "PRIVATE" in value.upper():
        return f"{NAME} carries a private-key marker; a private key must never be committed"
    try:
        raw = base64.b64decode(value.strip(), validate=True)
    except (binascii.Error, ValueError):
        return f"{NAME} is not valid base64"
    if len(raw) != KEY_BYTES:
        return (
            f"{NAME} is {len(raw)} bytes, not a raw {KEY_BYTES}-byte Ed25519 public key"
        )
    if not is_valid_point(raw):
        return f"{NAME} is not a valid Ed25519 public key (not a curve point of usable order)"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE)
    args = parser.parse_args(argv)
    try:
        source = args.file.read_text(encoding="utf-8")
    except OSError as error:
        print(f"cannot read {args.file}: {error}", file=sys.stderr)
        return 2
    reason = problem(source)
    if reason is not None:
        print(
            f"{reason}. A release image must carry the licensor's public key: "
            "set `DEFAULT_LICENSE_PUBLIC_KEY` in backend/src/sidekick/license/public_key.py and commit the result.",
            file=sys.stderr,
        )
        return 1
    print(f"{NAME} is set to a 32-byte public key")
    return 0


if __name__ == "__main__":
    sys.exit(main())
