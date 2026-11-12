"""The message table of tools/workctl: lookup, fallback, and the keys work.sh uses."""

import json
import re

import pytest
from tools.workctl import messages

from tests.selfhost.work_package.support import REPO_ROOT, SCRIPT

TABLE = json.loads((REPO_ROOT / "tools" / "workctl" / "messages.json").read_text(encoding="utf-8"))
DIRECTIVE = re.compile(r"%[^%\s]?")


def _directives(value: str) -> list[str]:
    return DIRECTIVE.findall(value.replace("%%", ""))


def test_text_returns_the_swedish_and_the_english_wording() -> None:
    assert messages.text("sv", "title") == "Sidekick Work: installationsguide"
    assert messages.text("en", "title") == "Sidekick Work: setup guide"


def test_text_of_an_unknown_key_is_the_key() -> None:
    assert messages.text("sv", "no_such_key") == "no_such_key"


def test_text_of_a_key_without_that_language_is_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(messages, "_table", lambda: {"only_sv": {"sv": "bara svenska"}})
    assert messages.text("en", "only_sv") == "only_sv"
    assert messages.text("sv", "only_sv") == "bara svenska"


def test_fill_fills_in_the_values_in_order() -> None:
    assert (
        messages.fill("en", "summary", "sv", "work,journal")
        == "App language: sv. Rooms: work,journal."
    )


def test_every_key_has_both_languages() -> None:
    assert [key for key, texts in TABLE.items() if sorted(texts) != ["en", "sv"]] == []


def test_both_languages_of_a_key_take_the_same_number_of_values() -> None:
    mismatched = {
        key: texts
        for key, texts in TABLE.items()
        if _directives(texts["sv"]) != _directives(texts["en"])
    }
    assert mismatched == {}


def test_every_directive_is_a_plain_string_value() -> None:
    """The texts are printf formats; they use only %s and %% (fill() relies on it)."""
    offenders = {
        key
        for key, texts in TABLE.items()
        for value in texts.values()
        if any(directive != "%s" for directive in _directives(value))
    }
    assert offenders == set()


def test_every_key_work_sh_names_literally_has_a_text() -> None:
    used = set(
        re.findall(
            r"""\b(?:say|sayf|errf|msg)\s+"?([a-z][a-z_0-9]*)"?""", SCRIPT.read_text("utf-8")
        )
    )
    assert used, "the pattern found no message keys"
    assert sorted(used - set(TABLE)) == []
