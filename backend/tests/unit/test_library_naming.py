"""Slugs, vault file names, title keys and URL keys: total, stable and safe as path parts."""

import hashlib
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sidekick.library.domain.errors import LibraryRefusedError
from sidekick.library.domain.naming import (
    FALLBACK_SLUG,
    FILENAME_PATTERN,
    MAX_SLUG_CHARS,
    SLUG_PATTERN,
    is_slug,
    is_vault_filename,
    normalise_url,
    parse_source_url,
    slugify,
    title_key,
    vault_filename,
)

ANY_CHARACTER = st.characters(exclude_categories=())
ANY_TEXT = st.text(alphabet=ANY_CHARACTER, max_size=200)
RECORD = UUID("01930000-0000-7000-8000-0123456789ab")


class TestSlugify:
    @given(title=ANY_TEXT)
    def test_the_slug_pattern_is_total_over_every_string(self, title: str) -> None:
        slug = slugify(title)

        assert SLUG_PATTERN.fullmatch(slug)
        assert is_slug(slug)
        assert len(slug) <= MAX_SLUG_CHARS
        assert slugify(slug) == slug

    @pytest.mark.parametrize(
        ("title", "slug"),
        [
            ("Dräneringsrör för dummies", "draneringsror-for-dummies"),
            ("Åke Öberg: Bästa  sättet!", "ake-oberg-basta-sattet"),
            ("Straße & Café", "strasse-cafe"),
            ("  --Hello__World--  ", "hello-world"),
            ("Ørsted / Łódź", "orsted-lodz"),
            ("2026-11-22 notes", "2026-11-22-notes"),
            ("日本語のタイトル", FALLBACK_SLUG),
            ("", FALLBACK_SLUG),
            ("---", FALLBACK_SLUG),
            ("../../etc/passwd", "etc-passwd"),
            ("..\\..\\windows\\system32", "windows-system32"),
            ("a\x00b\nc", "a-b-c"),
            ("\uff26\uff35\uff2c\uff2c\u3000\uff37\uff29\uff24\uff34\uff28", "full-width"),
        ],
    )
    def test_known_titles(self, title: str, slug: str) -> None:
        assert slugify(title) == slug

    def test_a_long_title_is_cut_at_a_word_and_never_ends_in_a_hyphen(self) -> None:
        slug = slugify("word " * 40)

        assert len(slug) <= MAX_SLUG_CHARS
        assert not slug.endswith("-")
        assert slug == "-".join(["word"] * (len(slug) // 5 + 1))[: len(slug)]

    def test_one_very_long_word_is_cut_hard(self) -> None:
        assert slugify("x" * 500) == "x" * MAX_SLUG_CHARS

    def test_a_cut_exactly_at_a_hyphen_keeps_the_whole_word(self) -> None:
        title = "a" * 59 + " bbb"

        assert slugify(title) == "a" * 59


class TestVaultFilename:
    def test_it_is_the_slug_and_the_last_eight_hex_digits_of_the_id(self) -> None:
        assert vault_filename("my-page", RECORD) == "my-page-456789ab.md"

    @given(title=ANY_TEXT, record=st.uuids())
    def test_every_name_made_from_a_slug_passes_the_path_check(
        self, title: str, record: UUID
    ) -> None:
        name = vault_filename(slugify(title), record)

        assert FILENAME_PATTERN.fullmatch(name)
        assert is_vault_filename(name)
        assert "/" not in name and "\\" not in name and ".." not in name

    @pytest.mark.parametrize(
        "slug", ["", "-", "-a", "a-", "A", "a_b", "a b", "a/b", "../x", "a.b", "x" * 61, "å"]
    )
    def test_a_slug_that_is_not_one_is_refused(self, slug: str) -> None:
        with pytest.raises(LibraryRefusedError) as refused:
            vault_filename(slug, RECORD)
        assert refused.value.refusal == "slug_invalid"

    @pytest.mark.parametrize(
        "name",
        [
            "my-page-456789ab.md",
            "a-00000000.md",
            "x" * 60 + "-deadbeef.md",
        ],
    )
    def test_names_the_mirror_may_write(self, name: str) -> None:
        assert is_vault_filename(name)

    @pytest.mark.parametrize(
        "name",
        [
            "",
            ".md",
            "-456789ab.md",
            "my-page.md",
            "my-page-456789AB.md",
            "my-page-456789a.md",
            "my-page-456789abc.md",
            "My-Page-456789ab.md",
            "my-page-456789ab.MD",
            "my-page-456789ab.md\n",
            "my-page-456789ab.md/",
            "../my-page-456789ab.md",
            "a/b-456789ab.md",
            "..\\a-456789ab.md",
            "x" * 61 + "-deadbeef.md",
            "a--456789ab.md",
            "a-456789ab.md.exe",
            "a b-456789ab.md",
        ],
    )
    def test_names_the_mirror_must_never_write(self, name: str) -> None:
        # `a--456789ab.md` has a slug ending in a hyphen, which `slugify` never makes.
        assert not is_vault_filename(name)

    @given(name=ANY_TEXT)
    def test_nothing_that_passes_the_check_can_leave_the_folder(self, name: str) -> None:
        if is_vault_filename(name):
            assert name == name.strip()
            assert not {"/", "\\", "\x00", ":"} & set(name)
            assert name not in {".", ".."}


class TestTitleKey:
    def test_case_and_spacing_do_not_matter(self) -> None:
        assert title_key("  Dräneringsrör   Guide ") == title_key("DRÄNERINGSRÖR guide")

    def test_composed_and_decomposed_letters_are_the_same_key(self) -> None:
        assert title_key("Å") == title_key("Å") == "å"

    @given(title=ANY_TEXT)
    def test_it_is_stable_and_bounded(self, title: str) -> None:
        key = title_key(title)

        assert title_key(key) == key
        assert len(key) <= 200


def key_of(url: str) -> str:
    return parse_source_url(url).key


class TestUrls:
    def test_equal_pages_share_a_key_whatever_the_spelling(self) -> None:
        spellings = [
            "https://example.com/a",
            "HTTPS://Example.COM/a",
            "https://example.com:443/a",
            "https://example.com./a",
            "https://example.com/a#section",
            "https://example.com/a?utm_source=x&utm_medium=y",
            "https://example.com/a?fbclid=abc",
            "https://example.com/a?gclid=abc&UTM_Campaign=z",
            "  https://example.com/a  ",
        ]

        assert len({key_of(spelling) for spelling in spellings}) == 1

    def test_different_pages_do_not_share_a_key(self) -> None:
        keys = {
            key_of(url)
            for url in [
                "https://example.com/a",
                "https://example.com/b",
                "http://example.com/a",
                "https://example.com:8443/a",
                "https://example.org/a",
                "https://example.com/a?id=1",
                "https://example.com/a?id=2",
                "https://example.com/A",
                "https://example.com/a/",
            ]
        }

        assert len(keys) == 9

    def test_other_query_parameters_are_kept_in_their_order(self) -> None:
        assert (
            normalise_url("https://e.com/p?b=1&utm_x=2&a=%2f&fbclid=3")
            == "https://e.com/p?b=1&a=%2F"
        )

    def test_an_empty_path_is_a_slash_and_the_fragment_goes(self) -> None:
        assert normalise_url("http://E.com#top") == "http://e.com/"
        assert normalise_url("http://e.com/?utm_a=1") == "http://e.com/"

    def test_the_key_is_the_sha256_of_the_normalised_address(self) -> None:
        assert key_of("https://e.com/a?utm_a=1") == hashlib.sha256(b"https://e.com/a").hexdigest()
        assert len(key_of("https://e.com/")) == 64

    def test_the_shown_address_keeps_the_page_and_lowers_scheme_and_host(self) -> None:
        parsed = parse_source_url(" HTTPS://Example.COM:443/Path?utm_a=1&b=2#frag ")

        assert parsed.url == "https://example.com/Path?utm_a=1&b=2#frag"
        assert parsed.domain == "example.com"

    def test_an_odd_port_is_part_of_the_key_but_not_of_the_domain(self) -> None:
        parsed = parse_source_url("http://example.com:8080/x")

        assert parsed.url == "http://example.com:8080/x"
        assert parsed.domain == "example.com"
        assert normalise_url("http://example.com:80/x") == "http://example.com/x"

    def test_international_addresses_become_ascii(self) -> None:
        parsed = parse_source_url("https://bücher.example/Räv?q=å#å")

        assert parsed.domain == "xn--bcher-kva.example"
        assert parsed.url.isascii()
        assert parsed.url.startswith("https://xn--bcher-kva.example/R%C3%A4v?q=%C3%A5")
        assert key_of("https://bücher.example/Räv?q=å") == key_of(
            "https://xn--bcher-kva.example/R%C3%A4v?q=%C3%A5"
        )

    def test_characters_that_close_a_markdown_link_or_a_quote_are_escaped(self) -> None:
        parsed = parse_source_url('https://example.com/a(b)[c]<d>|e"f\\g`h?q=(1)#[x]')

        assert parsed.url == (
            "https://example.com/a%28b%29%5Bc%5D%3Cd%3E%7Ce%22f%5Cg%60h?q=%281%29#%5Bx%5D"
        )
        assert not set('()[]<>|"\\`') & set(parsed.url)
        assert parse_source_url(parsed.url) == parsed
        assert key_of("https://example.com/a(b)") == key_of("https://example.com/a%28b%29")

    def test_an_ipv6_host_keeps_its_brackets(self) -> None:
        parsed = parse_source_url("http://[::1]:8080/x")

        assert parsed.url == "http://[::1]:8080/x"
        assert parsed.domain == "::1"

    @pytest.mark.parametrize(
        ("url", "refusal"),
        [
            ("", "url_scheme_refused"),
            ("example.com/a", "url_scheme_refused"),
            ("javascript:alert(1)", "url_scheme_refused"),
            ("ftp://example.com/a", "url_scheme_refused"),
            ("file:///etc/passwd", "url_scheme_refused"),
            ("data:text/html,x", "url_scheme_refused"),
            ("obsidian://open?vault=a", "url_scheme_refused"),
            ("//example.com/a", "url_scheme_refused"),
            ("https://", "url_host_missing"),
            ("https:///a", "url_host_missing"),
            ("https://user:pass@example.com/a", "url_credentials_refused"),
            ("https://example.com\\@evil.example/a", "url_credentials_refused"),
            ("https://exa mple.com/a", "url_invalid"),
            ("https://example.com/a b", "url_invalid"),
            ("https://example.com/a\nb", "url_invalid"),
            ("https://example.com/a\x00", "url_invalid"),
            ("https://example.com/\u202e", "url_invalid"),
            ("https://example.com:99999/a", "url_invalid"),
            ("https://example.com:abc/a", "url_invalid"),
            ("https://[::1/a", "url_invalid"),
            ("https://-bad-.example/a", "url_invalid"),
            ("https://exa_mple$.com/a", "url_invalid"),
            ("https://" + "a" * 254 + ".com/", "url_invalid"),
            ("https://example.com/" + "a" * 2048, "url_too_long"),
        ],
    )
    def test_what_is_not_an_http_address_is_refused_with_a_closed_code(
        self, url: str, refusal: str
    ) -> None:
        with pytest.raises(LibraryRefusedError) as refused:
            parse_source_url(url)
        assert refused.value.refusal == refusal

    def test_a_refusal_never_quotes_the_address(self) -> None:
        with pytest.raises(LibraryRefusedError) as refused:
            parse_source_url("https://user:secret@example.com/a")
        assert "secret" not in str(refused.value)

    @given(url=ANY_TEXT)
    def test_any_text_is_accepted_whole_or_refused_cleanly(self, url: str) -> None:
        try:
            parsed = parse_source_url(url)
        except LibraryRefusedError:
            return

        assert parsed.url.startswith(("http://", "https://"))
        assert parsed.url.isascii()
        assert not any(character.isspace() for character in parsed.url)
        assert len(parsed.key) == 64
        assert parse_source_url(parsed.url).key == parsed.key
