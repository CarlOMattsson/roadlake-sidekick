"""A reference CommonMark parser for asking whether a text still renders anything live.

The neutraliser is judged by what an independent renderer makes of its output, not by its own
rules: raw HTML, an image, a link that is not http(s), a code block that names a language or a
code span that looks like a Dataview query all count as live.
"""

import re
from collections.abc import Iterator
from pathlib import Path

from markdown_it import MarkdownIt
from markdown_it.token import Token

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "markdown"
SAFE_ADDRESS = re.compile(r"https?://", re.IGNORECASE)
CONTAINERS = {"blockquote": "blockquote", "bullet_list": "list", "ordered_list": "list"}
_FENCED_BLOCK = re.compile(r"(?ms)^(`{3,})text\n.*?^\1$")


def parser() -> MarkdownIt:
    """CommonMark with raw HTML switched on (so it would show up) and no address filter."""

    md = MarkdownIt("commonmark", {"html": True}).enable(["table", "strikethrough"])
    md.validateLink = lambda _url: True
    return md


def _walk(tokens: list[Token]) -> Iterator[Token]:
    for token in tokens:
        yield token
        if token.children:
            yield from _walk(token.children)


def live_things(markdown: str) -> list[str]:
    """What `markdown` would make live in a renderer; empty when it is inert."""

    env: dict[str, object] = {}
    tokens = parser().parse(markdown, env)
    found: list[str] = []
    for token in _walk(tokens):
        found.extend(_live_in(token))
    references = env.get("references")
    if isinstance(references, dict):
        found.extend(
            f"reference {label!r}: {value.get('href')}"
            for label, value in references.items()
            if not SAFE_ADDRESS.match(str(value.get("href", "")))
        )
    return found


def _live_in(token: Token) -> list[str]:
    if token.type in {"html_block", "html_inline", "image"}:
        return [f"{token.type}: {token.content[:60]!r}"]
    if token.type == "link_open":
        href = str(token.attrGet("href") or "")
        return [] if SAFE_ADDRESS.match(href) else [f"link: {href[:60]!r}"]
    if token.type == "fence" and token.info != "text":
        return [f"fence info: {token.info!r}"]
    if token.type == "code_inline" and re.match(r"\s*\$?=", token.content):
        return [f"inline query: {token.content[:60]!r}"]
    return []


def max_nesting(markdown: str) -> int:
    """The deepest nesting of quotes and lists that the parser builds."""

    depth = deepest = 0
    for token in parser().parse(markdown, {}):
        kind = token.type.rsplit("_", 1)[0]
        if token.type.endswith("_open") and kind in CONTAINERS:
            depth += 1
            deepest = max(deepest, depth)
        elif token.type.endswith("_close") and kind in CONTAINERS:
            depth -= 1
    return deepest


def prose_of(output: str) -> str:
    """`output` without the canonical code blocks the neutraliser writes."""

    return _FENCED_BLOCK.sub("", output)


def corpus_files() -> list[Path]:
    return sorted(CORPUS.glob("*.md"))
