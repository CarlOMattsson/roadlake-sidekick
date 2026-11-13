"""The message table of ``work.sh``: every text the script prints, in Swedish and English.

The texts live in ``messages.json`` (one key per line: ``{"key": {"sv": "...", "en": "..."}}``). A key that
has no text in the asked language is printed as the key itself, which is how ``work.sh`` always treated a
missing entry. The texts are ``printf`` formats (``%s`` and a few ``\\n`` escapes): ``work.sh`` fills them in
with ``sayf`` / ``errf``; code in this package fills them with :func:`fill`.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path

_TABLE_FILE = Path(__file__).with_name("messages.json")


@functools.lru_cache(maxsize=1)
def _table() -> dict[str, dict[str, str]]:
    loaded: dict[str, dict[str, str]] = json.loads(_TABLE_FILE.read_text(encoding="utf-8"))
    return loaded


def text(lang: str, key: str) -> str:
    """The text of ``key`` in ``lang``, or ``key`` itself when there is none."""
    return _table().get(key, {}).get(lang, key)


def fill(lang: str, key: str, *values: object) -> str:
    """``text`` with its ``%s`` filled in; the texts used this way have no other ``printf`` directive."""
    return text(lang, key) % values


def render(lang: str, key: str, *values: object) -> str:
    """``fill`` for the texts with ``\\n`` escapes: ``printf`` expanded those in the format (not in the values)."""
    return text(lang, key).replace("\\n", "\n") % values
