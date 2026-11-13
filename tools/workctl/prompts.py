"""The two answer rules of the interactive guide: what counts as a yes, and a choice from a numbered list."""

from __future__ import annotations

import re
from collections.abc import Sequence

YES_ANSWERS = frozenset({"j", "J", "y", "Y", "ja", "JA", "yes", "YES", "Yes"})
NUMBER = re.compile(r"[0-9]+")


def is_yes(answer: str) -> bool:
    return answer in YES_ANSWERS


def pick_choice(answer: str, choices: Sequence[str]) -> str:
    """The choice a number between 1 and ``len(choices)`` names; anything else is a typed value, taken as it is."""
    if NUMBER.fullmatch(answer) and 1 <= int(answer) <= len(choices):
        return choices[int(answer) - 1]
    return answer
