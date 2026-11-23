"""Cases that slipped past the neutraliser once, and a fixed-seed fuzz over the span-forming tokens.

The fuzz does not depend on hypothesis: the seed is fixed, so a failure reproduces from the
printed text alone, and the run stays within a few seconds.
"""

import random

import pytest

from sidekick.library.domain.markdown_safety import (
    MAX_INDENT_COLUMNS,
    MAX_NESTING,
    MarkdownKind,
    MarkdownRefusedError,
    neutralise,
)
from tests.support.markdown_render import live_things, max_nesting, prose_of

SEED = 20261122
EXAMPLES = 20_000
TOKENS = [
    "`", "`", "``", "```", "\\", "\\", "=", "=", "$=", "$", "|", "\n", "\n", " ", "x", ">", "- ",
    "<%", "[", "](", "]",
]  # fmt: skip


@pytest.mark.parametrize(
    "text",
    [
        "`=this.file\\`",
        "``=\\`",
        "`$=dv.x()\\`",
        "`\\`=x`",
        "``a`` `=b\\`",
        "\\``=x`",
        "`=x\\\\`",
        "a\\`b `=c\\``",
        "| a | `=x\\` |\n| - | - |",
    ],
)
def test_a_backslash_inside_a_code_span_does_not_hide_an_inline_query(text: str) -> None:
    output = neutralise(text)

    assert live_things(output) == []
    assert neutralise(output) == output


def test_a_fixed_seed_fuzz_over_span_tokens_is_inert_and_a_fixed_point() -> None:
    generator = random.Random(SEED)  # noqa: S311 - a reproducible test input, not a secret
    for _ in range(EXAMPLES):
        text = "".join(generator.choices(TOKENS, k=generator.randint(1, 24)))
        kind = MarkdownKind.SOURCE if generator.random() < 0.5 else MarkdownKind.PAGE
        try:
            output = neutralise(text, kind=kind)
        except MarkdownRefusedError:
            continue
        assert live_things(output) == [], (text, output)
        assert neutralise(output, kind=kind) == output, (text, output)
        assert "<%" not in output, (text, output)
        assert "<" not in prose_of(output), (text, output)


class TestTemplaterInCode:
    def test_the_opening_of_a_templater_tag_is_broken_in_a_code_block(self) -> None:
        output = neutralise('```js\n<% tp.system.prompt("x") %>\n<%* tR += 1 %>\n```')

        assert output == '```text\n< % tp.system.prompt("x") %>\n< %* tR += 1 %>\n```'

    def test_text_that_needs_no_breaking_is_kept_and_the_result_is_stable(self) -> None:
        output = neutralise("```\n<<%x <div> a < b\n```")

        assert output == "```text\n<< %x <div> a < b\n```"
        assert neutralise(output) == output

    def test_no_corpus_text_keeps_a_templater_opening_anywhere(self) -> None:
        for kind in MarkdownKind:
            assert "<%" not in neutralise("<% a %>\n\n```\n<% b %>\n```\n\n~~~x\n<%c\n", kind=kind)


class TestEmbedsInSources:
    def test_a_triple_bracket_embed_gets_one_escape_per_bracket(self) -> None:
        output = neutralise("![[[c]]]")

        assert output == "!\\[\\[\\[c]]]"
        assert neutralise(output) == output

    def test_in_a_page_the_embed_is_still_broken_and_a_link_stays(self) -> None:
        assert neutralise("![[a]] and [[b]]", kind=MarkdownKind.PAGE) == "!\\[\\[a]] and [[b]]"


def test_a_document_nests_at_most_the_documented_depth() -> None:
    lines = [" " * level + "- " * (MAX_NESTING + 3) + "x" for level in range(0, 80, 2)]
    lines += ["\t" * 20 + "> " * 20 + "- " * 20 + "x", "> " * 40 + "x"]

    output = neutralise("\n".join(lines))

    assert max_nesting(output) <= MAX_NESTING + MAX_INDENT_COLUMNS // 2
