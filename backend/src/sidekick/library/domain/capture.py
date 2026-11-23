"""Building a source's body from the line ranges Claude chose to keep of a raw capture.

A capture from the app or the phone holds the pasted text unprocessed. Claude reads it as
numbered lines and answers with the ranges worth keeping, so the article text never travels back
as model output. Lines are numbered from 1; a range names its first and last line, both kept.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from sidekick.library.domain.errors import LibraryRefusedError

MAX_CAPTURE_CHARS = 200_000
MAX_BODY_CHARS = 60_000
MAX_RANGES = 200


@dataclass(frozen=True)
class LineRange:
    """Lines `first` to `last` of a capture, 1-based and both included."""

    first: int
    last: int

    def __post_init__(self) -> None:
        if type(self.first) is not int or type(self.last) is not int:
            raise LibraryRefusedError("range_invalid")
        if self.first < 1 or self.last < self.first:
            raise LibraryRefusedError("range_invalid")


def split_lines(text: str) -> tuple[str, ...]:
    """The numbered lines of a capture. CRLF and CR are line breaks; a final break ends a line."""

    unified = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = unified.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return tuple(lines)


def check_capture_text(text: str) -> str:
    """`text` when it may be stored as a capture, else a refusal (empty or over the cap)."""

    if not text.strip():
        raise LibraryRefusedError("capture_empty")
    if len(text) > MAX_CAPTURE_CHARS:
        raise LibraryRefusedError("capture_too_long")
    return text


def build_body(capture_text: str, ranges: Sequence[LineRange]) -> str:
    """The kept lines of `capture_text`, in text order, as raw text that is still to be neutralised.

    Ranges may be given in any order. A range outside the text, two ranges that share a line
    and more than `MAX_RANGES` ranges are refused, as is a result that is empty or longer than
    `MAX_BODY_CHARS`. Lines that follow each other are joined by a line break; a gap between two
    ranges becomes a blank line, so text that was apart does not run together.
    """

    if not ranges:
        raise LibraryRefusedError("range_missing")
    if len(ranges) > MAX_RANGES:
        raise LibraryRefusedError("range_count_invalid")
    lines = split_lines(capture_text)
    ordered = sorted(ranges, key=lambda line_range: line_range.first)
    for earlier, later in pairwise(ordered):
        if later.first <= earlier.last:
            raise LibraryRefusedError("range_overlap")
    if ordered[-1].last > len(lines):
        raise LibraryRefusedError("range_out_of_text")
    parts: list[str] = []
    previous_last = 0
    for line_range in ordered:
        if parts:
            parts.append("\n" if line_range.first == previous_last + 1 else "\n\n")
        parts.append("\n".join(lines[line_range.first - 1 : line_range.last]))
        previous_last = line_range.last
    body = "".join(parts)
    if not body.strip():
        raise LibraryRefusedError("body_empty")
    if len(body) > MAX_BODY_CHARS:
        raise LibraryRefusedError("body_too_long")
    return body
