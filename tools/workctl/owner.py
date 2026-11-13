"""The identity of the user Claude Desktop acts as: only a well-formed UUID is ever used, because it goes into an SQL
statement and into the secrets directory."""

from __future__ import annotations

import re

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)


def is_uuid(value: str) -> bool:
    return UUID.fullmatch(value) is not None
