"""Refuse image data and NUL characters in client-supplied text.

The host model reads a photo or screenshot itself and sends only text. A data URL or a long
base64 block in a text field would store image bytes as record text, so the value is refused
before any service runs. The error names the rule, never the rejected value.

PostgreSQL cannot store a NUL character (\\x00) in a text column and raises a DataError, which would
reach the client as an internal error. `contains_nul` is the one check; the MCP tool-call middleware
and the companion request readers apply it to everything a client sends, so every present and future
text field is covered without annotating each one.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from typing import cast

from pydantic import AfterValidator

NUL = "\x00"

IMAGE_DATA_REFUSED = "text field must not contain image data; read the image and send text only"
MIN_BASE64_BLOCK = 200

_DATA_IMAGE_URI = re.compile(r"data:image/", re.IGNORECASE)
# The lookbehind starts a match only at the beginning of a run, so the scan stays linear.
_BASE64_BLOCK = re.compile(rf"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/=]{{{MIN_BASE64_BLOCK},}}")


def reject_image_data(value: str | None) -> str | None:
    """Return the value unchanged, or raise ValueError when it looks like image data."""
    if value is None:
        return None
    if _DATA_IMAGE_URI.search(value) or any(
        _looks_encoded(match.group()) for match in _BASE64_BLOCK.finditer(value)
    ):
        raise ValueError(IMAGE_DATA_REFUSED)
    return value


def contains_nul(value: object) -> bool:
    """True when any string in the value, or any mapping key, holds a NUL character.

    Walks nested lists, tuples and mappings without recursion, so a deeply nested body cannot
    exhaust the stack. Other value types are ignored.
    """
    pending: list[object] = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            if NUL in item:
                return True
        elif isinstance(item, Mapping):
            mapping = cast(Mapping[object, object], item)
            pending.extend(mapping.keys())
            pending.extend(mapping.values())
        elif isinstance(item, (list, tuple)):
            sequence = cast(Sequence[object], item)
            pending.extend(sequence)
    return False


def _looks_encoded(block: str) -> bool:
    """Encoded bytes mix character classes; a repeated letter such as "xxxx" does not."""
    classes: tuple[Callable[[str], bool], ...] = (
        str.isupper,
        str.islower,
        str.isdigit,
        lambda char: char in "+/=",
    )
    return sum(any(test(char) for char in block) for test in classes) >= 2


# Put in an Annotated text field next to its Field constraints, e.g.
# `title: Annotated[str, Field(max_length=200), NoImageData]`.
NoImageData = AfterValidator(reject_image_data)

__all__ = [
    "IMAGE_DATA_REFUSED",
    "MIN_BASE64_BLOCK",
    "NUL",
    "NoImageData",
    "contains_nul",
    "reject_image_data",
]
