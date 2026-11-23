"""The Markdown neutraliser against a hostile corpus, a reference renderer and fuzzing.

A text is judged inert when an independent CommonMark parser, with raw HTML switched on and its
own address filter off, finds nothing live in the output: no raw HTML, no image, no link that is
not http(s), no code block with a language and no Dataview inline query.
"""

import re

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from sidekick.library.domain.markdown_safety import (
    MAX_LINE_CHARS,
    MAX_NESTING,
    MarkdownKind,
    MarkdownRefusedError,
    neutralise,
)
from tests.support.markdown_render import (
    corpus_files,
    live_things,
    max_nesting,
    prose_of,
)

ZERO_WIDTH = "\u200b"
BIDI = "\u202e"

GENERATED = {
    "hidden_characters": (
        f"<scr{ZERO_WIDTH}ipt>alert(1)</scr{ZERO_WIDTH}ipt>\n\n"
        f"[js](java{ZERO_WIDTH}script:alert(1))\n\n"
        f"{BIDI}txet desrever\u200e and \ufeffbom and \u2060joiner\n\n"
        f"``{ZERO_WIDTH}`dataviewjs\nx\n```\n\n"
        f"`{ZERO_WIDTH}= this.file.name`\n"
    ),
    "line_breaks": (
        "line separator\u2028<script>alert(2)</script>\u2029paragraph\n"
        "carriage return only\r<script>alert(3)</script>\r\n"
        "nul\x00byte <scri\x00pt>alert(4)</scri\x00pt>\n"
        "form feed\x0c<script>alert(5)</script>\n"
        "next line\x85<script>alert(6)</script>\n"
    ),
    "quote_bomb": ">" * 10_000 + " <script>alert(1)</script>",
    "spaced_quote_bomb": "> " * 5_000 + "text",
    "list_bomb": "- " * 5_000 + "<script>alert(1)</script>",
    "mixed_bomb": "> - 1. " * 2_000 + "text",
    "indent_bomb": " " * 5_000 + "- item\n" + "\t" * 2_000 + "- item",
    "bracket_bomb": "[" * 3_000 + "x" + "](javascript:alert(1))" * 100,
    "backtick_bomb": ("`=x` " * 1_000 + "\n") * 3 + "`" * 3_000,
    "empty": "",
    "only_front_matter": "---\na: b\n---\n",
    "only_fence": "```dataviewjs",
}


def corpus() -> dict[str, str]:
    files = {path.name: path.read_text(encoding="utf-8") for path in corpus_files()}
    return {**files, **GENERATED}


CORPUS = corpus()
KINDS = list(MarkdownKind)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("name", sorted(CORPUS))
def test_the_whole_corpus_renders_inert_and_is_a_fixed_point(name: str, kind: MarkdownKind) -> None:
    output = neutralise(CORPUS[name], kind=kind)

    assert live_things(output) == []
    assert "<" not in prose_of(output)
    assert "<%" not in output
    assert neutralise(output, kind=kind) == output


def test_the_corpus_is_present_and_hostile_without_the_neutraliser() -> None:
    """The reference renderer must see the live parts, or the inert check above proves nothing."""

    assert len(corpus_files()) >= 7
    for name in ("01_script.md", "02_links.md", "03_images_and_embeds.md", "04_code_blocks.md"):
        assert len(live_things(CORPUS[name])) >= 3, name
    assert live_things(CORPUS["06_obsidian.md"])
    assert live_things(CORPUS["05_fence_confusion.md"])


@pytest.mark.parametrize("kind", KINDS)
def test_nesting_is_flattened_to_the_limit(kind: MarkdownKind) -> None:
    for name in ("quote_bomb", "spaced_quote_bomb", "list_bomb", "mixed_bomb"):
        output = neutralise(CORPUS[name], kind=kind)
        assert max_nesting(output) <= MAX_NESTING, name


def test_a_line_that_is_too_long_is_refused_not_cut() -> None:
    with pytest.raises(MarkdownRefusedError) as refused:
        neutralise("word " * (MAX_LINE_CHARS // 4))
    assert refused.value.refusal == "line_too_long"
    assert "word" not in str(refused.value)


def test_escaping_that_makes_a_line_too_long_is_refused() -> None:
    with pytest.raises(MarkdownRefusedError):
        neutralise("<" * (MAX_LINE_CHARS // 2))


def test_a_long_line_inside_a_code_block_is_refused_too() -> None:
    with pytest.raises(MarkdownRefusedError):
        neutralise("```\n" + "x" * (MAX_LINE_CHARS + 1) + "\n```")


def test_the_result_is_bounded_by_max_chars() -> None:
    assert neutralise("a" * 100, max_chars=100) == "a" * 100
    with pytest.raises(MarkdownRefusedError) as refused:
        neutralise("a" * 100, max_chars=99)
    assert refused.value.refusal == "too_long"
    with pytest.raises(MarkdownRefusedError):
        neutralise("<" * 30, max_chars=100)


class TestFencedCode:
    def test_every_info_string_becomes_text_and_the_content_is_kept(self) -> None:
        source = (
            '```dataviewjs\ndv.paragraph("<b>")\n```\n\n~~~run-js\nalert(1)\n~~~\n\n```\nbare\n```'
        )

        output = neutralise(source)

        assert output == (
            '```text\ndv.paragraph("<b>")\n```\n\n```text\nalert(1)\n```\n\n```text\nbare\n```'
        )

    def test_an_unclosed_block_is_closed_at_the_end(self) -> None:
        output = neutralise("```dataviewjs\n<script>alert(1)</script>\nmore")

        assert output == "```text\n<script>alert(1)</script>\nmore\n```"
        assert live_things(output) == []

    def test_a_longer_fence_is_used_when_the_content_has_fence_lines(self) -> None:
        output = neutralise("~~~\n```dataviewjs\nx\n```\n<script>alert(1)</script>\n~~~")

        assert output.startswith("````text\n```dataviewjs\n")
        assert output.endswith("\n````")
        assert live_things(output) == []

    def test_a_fence_line_in_a_quote_or_list_is_text_not_a_block(self) -> None:
        output = neutralise("> ```dataviewjs\n> x\n> ```\n\n- ```run-js\n  y\n  ```")

        assert "\\```dataviewjs" in output
        assert "\\```run-js" in output
        assert live_things(output) == []

    def test_a_backtick_fence_with_a_backtick_in_its_info_is_not_a_block(self) -> None:
        output = neutralise("```dataviewjs `x`\n<script>alert(1)</script>")

        assert output == "\\```dataviewjs `x`\n&lt;script>alert(1)&lt;/script>"

    def test_indented_code_stays_code_and_is_escaped(self) -> None:
        output = neutralise("text\n\n    <script>alert(1)</script>")

        assert output == "text\n\n    &lt;script>alert(1)&lt;/script>"


class TestProse:
    def test_html_is_escaped_in_every_form(self) -> None:
        output = neutralise("<script>x</script> <!-- c --> <% tp %> <https://a.example> a < b")

        assert output == (
            "&lt;script>x&lt;/script> &lt;!-- c --> &lt;% tp %> &lt;https://a.example> a &lt; b"
        )

    def test_images_and_embeds_lose_their_bang(self) -> None:
        output = neutralise("![a](https://t.example/p.gif) ![[note]] ![ref][r]")

        assert "![" not in output
        assert output == "!\\[a](https://t.example/p.gif) !\\[\\[note]] !\\[ref][r]"

    def test_http_and_https_links_are_kept(self) -> None:
        text = "[a](https://example.com/x?y=1) [b](http://example.com) [c](HTTPS://EXAMPLE.COM)"

        assert neutralise(text) == text
        assert neutralise("[a]: https://example.com/ok") == "[a]: https://example.com/ok"

    @pytest.mark.parametrize(
        "address",
        [
            "javascript:alert(1)",
            "JaVaScRiPt:alert(1)",
            "&#106;avascript:alert(1)",
            "data:text/html,x",
            "file:///etc/passwd",
            "obsidian://open?vault=a",
            "vbscript:x",
            "//evil.example/x",
            "../secret.md",
            "#top",
            "/admin",
            "mailto:a@example.com",
            "<javascript:alert(1)>",
            "",
        ],
    )
    def test_any_other_address_is_shown_as_text(self, address: str) -> None:
        for text in (f"[x]({address})", f"[x][r]\n\n[r]: {address}"):
            output = neutralise(text)
            assert live_things(output) == [], text
            assert "\\]" in output

    def test_a_definition_on_the_next_line_or_with_a_split_label_is_refused(self) -> None:
        output = neutralise("[a][b]\n\n[b]:\njavascript:alert(1)\n\n[c\nd]: javascript:alert(2)")

        assert live_things(output) == []

    def test_wiki_links_are_text_in_a_source_and_links_in_a_page(self) -> None:
        text = "[[Page]] and [[a]][[b]] and [[[c]]]"

        assert "[[" not in neutralise(text, kind=MarkdownKind.SOURCE)
        assert neutralise(text, kind=MarkdownKind.PAGE) == text

    def test_an_embed_is_text_in_a_page_too(self) -> None:
        output = neutralise("![[secret]] and ![[[x]]]", kind=MarkdownKind.PAGE)

        assert "![" not in output

    def test_an_equals_sign_after_a_backtick_run_is_escaped_so_no_span_starts_with_it(self) -> None:
        output = neutralise("`= this.file.name` and `$= dv.x()` and ` = padded ` and ``=x``")

        assert live_things(output) == []
        assert "`\\= this.file.name`" in output
        assert "``\\=x``" in output

    def test_a_closing_backtick_before_an_equals_sign_shows_no_change(self) -> None:
        output = neutralise("set `x` = 5 and `a = b` and 1 `+` 1 = 2")

        assert output == "set `x` \\= 5 and `a = b` and 1 `+` 1 = 2"

    def test_a_span_in_a_table_cell_is_marked_whatever_the_pairing(self) -> None:
        output = neutralise("| a `| b | `=x` |\n| - | - | - |\n")

        assert live_things(output) == []

    def test_math_and_comments_are_broken_up(self) -> None:
        output = neutralise(r"$$ \href{javascript:alert(1)}{x} $$ and $x$ and %%hidden%%")

        assert "$" not in re.sub(r"\\\$", "", output)
        assert "%%" not in output

    def test_hidden_characters_cannot_hide_markup(self) -> None:
        output = neutralise(GENERATED["hidden_characters"])

        assert "&lt;script>alert(1)&lt;/script>" in output
        assert "\\](javascript:alert(1))" in output
        assert "[js\\](javascript" in output
        assert not {ZERO_WIDTH, BIDI, "\ufeff", "\u2060", "\x00"} & set(output)

    def test_every_kind_of_line_break_becomes_a_newline(self) -> None:
        output = neutralise(GENERATED["line_breaks"])

        assert "\r" not in output
        assert output.count("&lt;script>") == 5
        assert output.count("\n") >= 5

    def test_a_fence_like_line_after_prose_markers_is_defused(self) -> None:
        output = neutralise("1. ```run-js\n2. ~~~dataviewjs")

        assert output == "1. \\```run-js\n2. \\~~~dataviewjs"


class TestFrontMatter:
    def test_a_leading_block_is_removed_also_when_repeated(self) -> None:
        output = neutralise(CORPUS["07_front_matter.md"])

        assert output.startswith("The body starts here.")
        assert "sidekick_" not in output
        assert "nested" not in output

    def test_a_later_block_is_ordinary_text(self) -> None:
        output = neutralise("Intro\n\n---\nkey: value\n---\n")

        assert "key: value" in output

    def test_blank_lines_before_the_block_do_not_hide_it(self) -> None:
        assert neutralise("\n \n---\nsidekick_sha: x\n---\nbody") == "body"

    def test_an_unclosed_opener_is_a_thematic_break(self) -> None:
        assert neutralise("---\nbody") == "---\nbody"


class TestOutputShape:
    def test_plain_text_is_unchanged(self) -> None:
        text = "# Title\n\nSome *emphasis*, a [link](https://example.com) and a list:\n\n- a\n- b"

        assert neutralise(text) == text

    def test_the_text_is_normalised_to_nfc(self) -> None:
        assert neutralise("e\u0301") == "\u00e9"

    def test_nothing_is_lost_from_a_swedish_text(self) -> None:
        text = "Dräneringsrör, åäö ÅÄÖ, och 5 % av 10 kr."

        assert neutralise(text) == text


FRAGMENTS = [
    "<script>", "</script>", "<", ">", "&lt;", "<!--", "<%", "%>", "```", "~~~", "````",
    "dataviewjs", "text", "js", "\n", "\n\n", "\r\n", " ", "  ", "    ", "\t", "> ", "- ", "1. ",
    "`", "``", "=", "$", "$=", "$$", "[", "]", "(", ")", "![", "[[", "]]", "![[", "%%", "|",
    "javascript:", "https://a.example/", "http://", "obsidian://", "data:", "---", "...",
    "\\", "\\\\", "x", "word", "\u200b", "\u202e", "\u2028", "\r", "\x00", "# ", "[a]: ",
]  # fmt: skip

nasty_text = st.one_of(
    st.lists(st.sampled_from(FRAGMENTS), max_size=80).map("".join),
    st.text(max_size=300),
)
property_settings = settings(
    max_examples=400, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)


@pytest.mark.parametrize("kind", KINDS)
@property_settings
@given(text=nasty_text)
def test_neutralise_is_idempotent_and_inert_for_any_text(text: str, kind: MarkdownKind) -> None:
    try:
        output = neutralise(text, kind=kind)
    except MarkdownRefusedError:
        return

    assert neutralise(output, kind=kind) == output
    assert live_things(output) == [], output
    assert "<" not in prose_of(output)
    assert all(len(line) <= MAX_LINE_CHARS for line in output.split("\n"))


@property_settings
@given(text=nasty_text)
def test_a_page_is_as_inert_as_a_source_but_keeps_its_wiki_links(text: str) -> None:
    try:
        page = neutralise(text, kind=MarkdownKind.PAGE)
    except MarkdownRefusedError:
        return

    assert live_things(page) == []
    assert "![" not in prose_of(page)


def test_the_property_strategy_reaches_the_dangerous_shapes() -> None:
    """A strategy that never builds a fence or a link would make the properties empty."""

    assert {"```", "[a]: ", "$=", "![[", "javascript:"} <= set(FRAGMENTS)
