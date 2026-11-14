"""The CLI's pairing link, `sidekick://pair?server=<url>&code=<code>` (no database)."""

from __future__ import annotations

import argparse
from urllib.parse import parse_qs, urlsplit

import pytest

from sidekick.companion.cli import _server_origin, build_parser, pairing_check, pairing_link


def test_the_link_carries_both_fields_url_encoded() -> None:
    link = pairing_link("https://sidekick.example", "rspair_a-b_c")
    parts = urlsplit(link)
    assert (parts.scheme, parts.netloc) == ("sidekick", "pair")
    assert "https%3A%2F%2Fsidekick.example" in link
    assert parse_qs(parts.query) == {
        "server": ["https://sidekick.example"],
        "code": ["rspair_a-b_c"],
    }


@pytest.mark.parametrize(
    ("given", "origin"),
    [
        ("https://sidekick.example", "https://sidekick.example"),
        (" https://sidekick.example/ ", "https://sidekick.example"),
        ("https://sidekick.example:8443", "https://sidekick.example:8443"),
        ("http://10.0.2.2:8100", "http://10.0.2.2:8100"),
    ],
)
def test_the_server_url_is_an_origin(given: str, origin: str) -> None:
    assert _server_origin(given) == origin


@pytest.mark.parametrize(
    "given",
    [
        "sidekick.example",
        "http://sidekick.example",
        "https://sidekick.example/mcp",
        "https://sidekick.example?x=1",
        "https://user:pw@sidekick.example",
        "ftp://sidekick.example",
        "https://",
    ],
)
def test_a_server_url_with_more_than_an_origin_is_refused(given: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        _server_origin(given)


def test_pair_accepts_a_server_url_and_defaults_to_none() -> None:
    parser = build_parser()
    base = ["pair", "--label", "Phone", "--preset", "app"]
    assert parser.parse_args(base).server_url is None
    given = parser.parse_args([*base, "--server-url", "https://s.example"])
    assert given.server_url == "https://s.example"


@pytest.mark.parametrize(
    ("code", "check"),
    [
        ("rspair_abcdefghijklmnop", "846 345"),
        ("rspair_a-b_c", "335 471"),
        (" rspair_a-b_c ", "335 471"),
    ],
)
def test_the_check_code_matches_the_one_the_app_derives(code: str, check: str) -> None:
    # The same vectors are asserted in frontend/tests/mobile-pairing-form.test.tsx.
    assert pairing_check(code) == check
