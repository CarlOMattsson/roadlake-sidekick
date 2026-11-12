"""Validation of work.env addresses in tools/workctl: model server URL and extra allowlist."""

import re

import pytest
from tools.workctl import addresses

# The model server port used by most tests; it must not collide with the gateway's MCP port.
MODEL_PORT = 8000


@pytest.mark.parametrize(
    ("raw", "scheme", "host", "port", "path", "is_ip"),
    [
        ("http://embed.lan/v1", "http", "embed.lan", 80, "/v1", False),
        ("https://embed.lan/v1", "https", "embed.lan", 443, "/v1", False),
        ("http://embed.lan:8000/v1", "http", "embed.lan", 8000, "/v1", False),
        ("https://embed.lan:8443/v1", "https", "embed.lan", 8443, "/v1", False),
        ("http://embed.lan/v1/", "http", "embed.lan", 80, "/v1", False),
        ("  https://embed.lan/v1  ", "https", "embed.lan", 443, "/v1", False),
        ("https://10.0.0.5:443/v1", "https", "10.0.0.5", 443, "/v1", True),
        ("http://[::1]:8000/v1", "http", "::1", 8000, "/v1", True),
    ],
)
def test_parse_base_url_accepts_valid_urls(
    raw: str, scheme: str, host: str, port: int, path: str, is_ip: bool
) -> None:
    parsed = addresses.parse_base_url(raw)

    assert parsed.scheme == scheme
    assert parsed.host == host
    assert parsed.port == port
    assert parsed.path == path
    assert parsed.is_ip is is_ip


def test_parse_base_url_lines_are_in_work_sh_order() -> None:
    assert addresses.parse_base_url("https://embed.lan:8443/v1").lines() == [
        "https",
        "embed.lan",
        "8443",
        "/v1",
        "0",
    ]
    assert addresses.parse_base_url("http://10.0.0.5/v1").lines() == [
        "http",
        "10.0.0.5",
        "80",
        "/v1",
        "1",
    ]


@pytest.mark.parametrize(
    ("raw", "lang", "fragment"),
    [
        # Missing path: the message names the path in both languages.
        ("http://embed.lan", "sv", "sökväg"),
        ("http://embed.lan", "en", "needs a path"),
        ("http://embed.lan:8000/", "sv", "sökväg"),
        ("http://embed.lan:8000/", "en", "needs a path"),
        # Wrong scheme, or no host at all.
        ("ftp://embed.lan/v1", "sv", "http:// eller https://"),
        ("ftp://embed.lan/v1", "en", "must start with http://"),
        ("", "sv", "http:// eller https://"),
        ("", "en", "must start with http://"),
        ("https://", "en", "must start with http://"),
        # Credentials, query and fragment share one message.
        ("http://user:pw@embed.lan/v1", "sv", "inloggning"),
        ("http://user:pw@embed.lan/v1", "en", "credentials"),
        ("http://embed.lan/v1?key=1", "sv", "inloggning"),
        ("http://embed.lan/v1?key=1", "en", "credentials"),
        ("http://embed.lan/v1#frag", "sv", "inloggning"),
        ("http://embed.lan/v1#frag", "en", "credentials"),
        # Port outside 0-65535 makes urlsplit raise; the parse error is reported.
        ("http://embed.lan:99999/v1", "sv", "kan inte tolkas"),
        ("http://embed.lan:99999/v1", "en", "cannot be parsed"),
    ],
)
def test_parse_base_url_rejects_invalid_urls(raw: str, lang: str, fragment: str) -> None:
    with pytest.raises(addresses.AddressError, match=re.escape(fragment)):
        addresses.parse_base_url(raw, lang=lang)


def test_parse_base_url_defaults_to_swedish_messages() -> None:
    with pytest.raises(addresses.AddressError, match="sökväg"):
        addresses.parse_base_url("http://embed.lan")


def test_parse_allowlist_empty_returns_empty_list() -> None:
    assert addresses.parse_allowlist("", MODEL_PORT) == []
    assert addresses.parse_allowlist("   ", MODEL_PORT) == []


def test_parse_allowlist_accepts_mixed_separators_and_normalises_case() -> None:
    result = addresses.parse_allowlist("Embed.Foretag.lan:443, b.lan:8443 C.lan:9443", MODEL_PORT)

    assert result == [("embed.foretag.lan", 443), ("b.lan", 8443), ("c.lan", 9443)]


@pytest.mark.parametrize("lang", ["sv", "en"])
def test_parse_allowlist_rejects_duplicate_port(lang: str) -> None:
    fragment = "porten 443 används redan" if lang == "sv" else "port 443 is already used"
    with pytest.raises(addresses.AddressError, match=re.escape(fragment)):
        addresses.parse_allowlist("a.lan:443,b.lan:443", MODEL_PORT, lang=lang)


@pytest.mark.parametrize("lang", ["sv", "en"])
def test_parse_allowlist_rejects_gateway_mcp_port(lang: str) -> None:
    fragment = "porten 8765" if lang == "sv" else "port 8765"
    with pytest.raises(addresses.AddressError, match=re.escape(fragment)):
        addresses.parse_allowlist("a.lan:8765", MODEL_PORT, lang=lang)


@pytest.mark.parametrize("lang", ["sv", "en"])
def test_parse_allowlist_rejects_model_port(lang: str) -> None:
    fragment = (
        f"porten {MODEL_PORT} används redan"
        if lang == "sv"
        else f"port {MODEL_PORT} is already used"
    )
    with pytest.raises(addresses.AddressError, match=re.escape(fragment)):
        addresses.parse_allowlist(f"a.lan:{MODEL_PORT}", MODEL_PORT, lang=lang)


@pytest.mark.parametrize(
    ("raw", "lang", "fragment"),
    [
        ("10.0.0.5:443", "sv", "IP-adresser"),
        ("10.0.0.5:443", "en", "IP addresses"),
    ],
)
def test_parse_allowlist_rejects_ip_address(raw: str, lang: str, fragment: str) -> None:
    with pytest.raises(addresses.AddressError, match=re.escape(fragment)):
        addresses.parse_allowlist(raw, MODEL_PORT, lang=lang)


@pytest.mark.parametrize(
    "raw",
    [
        "nohost",
        "host:abc",
        "host:",
        ":443",
        "-bad.lan:443",
        "[::1]:443",
    ],
)
def test_parse_allowlist_rejects_invalid_format(raw: str) -> None:
    with pytest.raises(addresses.AddressError, match=re.escape("write host:port")):
        addresses.parse_allowlist(raw, MODEL_PORT, lang="en")


@pytest.mark.parametrize("raw", ["a.lan:0", "a.lan:65536", "a.lan:99999"])
def test_parse_allowlist_rejects_port_out_of_range(raw: str) -> None:
    with pytest.raises(addresses.AddressError, match=re.escape("skriv värdnamn:port")):
        addresses.parse_allowlist(raw, MODEL_PORT)
