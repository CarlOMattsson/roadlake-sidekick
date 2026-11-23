"""Making untrusted Markdown inert before it is stored, mirrored to a folder or shown.

A saved web page can carry a script, a Dataview query, a Templater tag, a remote image or a
`javascript:` link. `neutralise` turns such a text into Markdown that renders as plain content in
any CommonMark renderer and in Obsidian, so no later renderer has to be trusted to escape it.
When the text cannot be made safe it is refused, never guessed at.

The output is built, not filtered, so it does not depend on how the input would have been parsed:

* A fenced code block is recognised by a fence line that starts a line, with spaces or tabs
  before it at most. It is written again as a canonical block: a fence at column 0 whose info
  string is `text` (this removes `dataviewjs`, `dataview`, `button`, `run-*` and every other
  executable language), the lines kept as they were, and a closing fence that no line of the
  block can close early. An unclosed block is closed at the end.
* Every other line is prose. In prose nothing can start a block of raw HTML, an image or an
  embed, a link has to point at an absolute http(s) address, and a fence-like line is escaped so
  that no parser reads it as a fence. A fence behind a quote or list marker therefore becomes
  text; that is a loss of formatting, chosen over a guess about where the block ends.

What the rules do:

1. Text is normalised: NFC, no invisible or bidirectional characters, line breaks as newlines.
2. A leading front matter block is removed. Sidekick writes the only front matter.
3. Fenced code blocks are written again as above.
4. In prose, `<` becomes `&lt;` everywhere, also inside inline code, because a code span that
   this module sees may be split into table cells by the renderer; `![` becomes `!\\[` (no
   image, no `![[embed]]`); `[[` becomes `\\[\\[` in a source and stays in a page; every `$` (math)
   is escaped and `%%` (an Obsidian comment, which hides text from the reader) is broken up;
   and an `=` after any backtick run gets a backslash in front, so no code span starts with `=`
   or `$=` (a Dataview inline query). A space in front would not do: Dataview trims first.
   Which run opens a span depends on block structure that is not followed here, so every run
   counts; one that only closes a span shows no change.
5. A link or a link reference definition is kept only when its address starts with `http://` or
   `https://`. Anything else (`javascript:`, `data:`, `file:`, `obsidian:`, a relative address,
   an address written with an entity) has the closing bracket escaped so it shows as text.
6. A line longer than `MAX_LINE_CHARS` is refused. A line keeps at most `MAX_NESTING` quote
   and list markers (more are dropped) and at most `MAX_INDENT_COLUMNS` columns of indentation.
   Indentation nests lists too, two columns a level, so a document nests at most
   `MAX_NESTING + MAX_INDENT_COLUMNS // 2` (24) deep, and a test holds it to that.
7. In a code block `<%` is written `< %`: Templater reads its tags in code as well, and
   nothing else in a block needs the two characters together.

Residual risk, still to be checked against Obsidian itself: bare `obsidian://` text in prose is
left alone, and Obsidian's handling of a backslash before a bracket follows its documentation.
"""

import re
from enum import StrEnum

from sidekick.library.domain.errors import LibraryRefusedError
from sidekick.work.domain.ai_spec import clean_text

MAX_LINE_CHARS = 10_000
MAX_NESTING = 8
MAX_INDENT_COLUMNS = 32
FENCE_INFO = "text"
"""The only info string that survives on a fenced code block."""


class MarkdownKind(StrEnum):
    """Where the text will live. A wiki page may link to other pages with `[[Title]]`."""

    SOURCE = "source"
    PAGE = "page"


class MarkdownRefusedError(LibraryRefusedError):
    """A text that cannot be made safe: `refusal` is `line_too_long` or `too_long`."""

    code = "markdown_refused"
    safe_title = "The text cannot be stored as Markdown"


_LINE_BREAKS = ("\r\n", "\r", chr(0x2028), chr(0x2029), "\x0b", "\x0c", "\x85")
_FRONT_MATTER_FENCE = "---"
_FRONT_MATTER_END = frozenset({"---", "..."})
_FENCE_OPEN = re.compile(r"^[ \t]*(`{3,}|~{3,})(.*)$")
_FENCE_CLOSE = re.compile(r"^[ \t]*(`{3,}|~{3,})[ \t]*$")
_BLOCK_PREFIX = r"(?:[ \t]|>|[-*+](?=[ \t])|\d{1,9}[.)](?=[ \t]))"
_MARKER = re.compile(r"[ \t]*(?:>|[-*+](?=[ \t])|\d{1,9}[.)](?=[ \t]))")
_FENCE_LIKE = re.compile(rf"^({_BLOCK_PREFIX}*)(`{{3,}}|~{{3,}})")
_UNESCAPED_BRACKET = re.compile(r"(?<!\\)((?:\\\\)*)\](?=[(:])")
_SAFE_ADDRESS = re.compile(r"https?://", re.IGNORECASE)
_DOLLAR = re.compile(r"(?<!\\)((?:\\\\)*)\$")
_DOUBLE_PERCENT = re.compile(r"%(?=%)")
_ADJACENT_OPEN_BRACKET = re.compile(r"\[(?=\[)|(?<=\[)\[")
_INLINE_QUERY = re.compile(r"(`+[\s>]*)=")


def neutralise(
    text: str, *, kind: MarkdownKind = MarkdownKind.SOURCE, max_chars: int | None = None
) -> str:
    """`text` as inert Markdown, or `MarkdownRefusedError` when that is not possible.

    `neutralise(neutralise(x)) == neutralise(x)` for every text. `max_chars` bounds the result
    (a refusal `too_long`), because escaping makes a text longer than it was.
    """

    lines = _drop_front_matter(_normalise(text).rstrip("\n").split("\n"))
    output: list[str] = []
    prose: list[str] = []
    code: list[str] | None = None
    opener = ""
    for line in lines:
        if code is not None:
            if _closes(line, opener):
                output.extend(_emit_code(code))
                code = None
            else:
                code.append(line)
            continue
        found = _fence_opener(line)
        if found is None:
            prose.append(line)
            continue
        output.extend(_neutralise_prose(prose, kind))
        prose, code, opener = [], [], found
    if code is not None:
        output.extend(_emit_code(code))
    output.extend(_neutralise_prose(prose, kind))
    return _checked("\n".join(output).strip("\n"), max_chars)


def _checked(result: str, max_chars: int | None) -> str:
    if max_chars is not None and len(result) > max_chars:
        raise MarkdownRefusedError("too_long")
    if any(len(line) > MAX_LINE_CHARS for line in result.split("\n")):
        raise MarkdownRefusedError("line_too_long")
    return result


def _normalise(text: str) -> str:
    unified = text
    for line_break in _LINE_BREAKS:
        unified = unified.replace(line_break, "\n")
    return clean_text(unified, multiline=True)


def _drop_leading_blank(lines: list[str]) -> list[str]:
    start = 0
    while start < len(lines) and not lines[start].strip():
        start += 1
    return lines[start:]


def _drop_front_matter(lines: list[str]) -> list[str]:
    while True:
        lines = _drop_leading_blank(lines)
        if not lines or lines[0].rstrip() != _FRONT_MATTER_FENCE:
            return lines
        end = next(
            (index for index in range(1, len(lines)) if lines[index].rstrip() in _FRONT_MATTER_END),
            None,
        )
        if end is None:
            return lines
        lines = lines[end + 1 :]


# --- fenced code ------------------------------------------------------------------------------


def _fence_opener(line: str) -> str | None:
    """The fence run (for example "```") when `line` opens a fenced code block, else None."""

    found = _FENCE_OPEN.match(line)
    if found is None:
        return None
    run, info = found.groups()
    if run[0] == "`" and "`" in info:
        return None
    return run


def _closes(line: str, opener: str) -> bool:
    found = _FENCE_CLOSE.match(line)
    if found is None:
        return False
    run = found.group(1)
    return run[0] == opener[0] and len(run) >= len(opener)


def _leading_backticks(line: str) -> int:
    stripped = line.lstrip(" \t")
    return len(stripped) - len(stripped.lstrip("`"))


def _emit_code(content: list[str]) -> list[str]:
    """A canonical block: no line of `content` can close a fence longer than all of their runs."""

    width = max(3, 1 + max((_leading_backticks(line) for line in content), default=0))
    fence = "`" * width
    return [fence + FENCE_INFO, *(line.replace("<%", "< %") for line in content), fence]


# --- prose ------------------------------------------------------------------------------------


def _neutralise_prose(lines: list[str], kind: MarkdownKind) -> list[str]:
    if not lines:
        return []
    cleaned = [_defuse_fence(_flatten(line)) for line in lines]
    chunk = _refuse_unsafe_addresses("\n".join(cleaned))
    if kind is MarkdownKind.SOURCE:
        chunk = _ADJACENT_OPEN_BRACKET.sub(r"\\[", chunk)
    chunk = chunk.replace("![[", "!\\[\\[").replace("![", "!\\[")
    chunk = chunk.replace("<", "&lt;")
    chunk = _DOLLAR.sub(r"\1\\$", chunk)
    chunk = _DOUBLE_PERCENT.sub("% ", chunk)
    return _break_inline_queries(chunk).split("\n")


def _flatten(line: str) -> str:
    """At most `MAX_NESTING` quote and list markers, and indentation of at most 32 columns."""

    kept: list[str] = []
    position = 0
    count = 0
    while (found := _MARKER.match(line, position)) is not None:
        if count < MAX_NESTING:
            kept.append(found.group())
        count += 1
        position = found.end()
    if count > MAX_NESTING:
        line = "".join(kept) + line[position:]
    return _cap_indent(line)


def _cap_indent(line: str) -> str:
    body = line.lstrip(" \t")
    indent = line[: len(line) - len(body)]
    columns = sum(4 if character == "\t" else 1 for character in indent)
    return " " * MAX_INDENT_COLUMNS + body if columns > MAX_INDENT_COLUMNS else line


def _defuse_fence(line: str) -> str:
    """Escape a fence run that no block recogniser of ours owns, so no parser reads it as one."""

    return _FENCE_LIKE.sub(lambda found: found.group(1) + "\\" + found.group(2), line)


def _refuse_unsafe_addresses(chunk: str) -> str:
    """Escape every `]` that opens a link address or a definition unless that is http(s)."""

    def replace(found: re.Match[str]) -> str:
        following = chunk[found.end() + 1 :].lstrip()
        if _SAFE_ADDRESS.match(following):
            return found.group(0)
        return found.group(1) + "\\]"

    return _UNESCAPED_BRACKET.sub(replace, chunk)


def _break_inline_queries(chunk: str) -> str:
    """Escape an `=` that follows a backtick run, so no code span can start with it.

    A Dataview inline query is a code span that starts with `=` (or `$=`, whose `$` is already
    escaped). Which backtick run opens a span depends on block structure that this module does
    not follow (a list item or a table cell can end a span's paragraph), so every run counts.
    Outside code the backslash is an escape and shows nothing, so a run that only closes a span
    costs nothing; inside a span the text starts with a backslash and is no query.
    """

    return _INLINE_QUERY.sub(r"\1\\=", chunk)
