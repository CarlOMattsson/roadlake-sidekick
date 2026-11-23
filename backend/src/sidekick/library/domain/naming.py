"""Names the library derives from what it was given: slugs, file names, title keys and URL keys.

Every function here is total over what it accepts or refuses with a closed code. A slug and a
file name are the only parts of a path the vault mirror ever writes, so their patterns are the
whole defence against a title that tries to climb out of the folder.
"""

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import SplitResult, quote, urlsplit
from uuid import UUID

from sidekick.library.domain.errors import LibraryRefusedError

SLUG_PATTERN = re.compile(r"[a-z0-9-]{1,60}")
FILENAME_PATTERN = re.compile(r"[a-z0-9-]{1,60}-[0-9a-f]{8}\.md")
MAX_SLUG_CHARS = 60
FALLBACK_SLUG = "untitled"
MAX_TITLE_KEY_CHARS = 200
MAX_URL_CHARS = 2048
MAX_HOST_CHARS = 253
TRACKING_PARAMETERS = frozenset({"fbclid", "gclid"})
TRACKING_PREFIX = "utm_"

_LETTERS_WITHOUT_DECOMPOSITION = str.maketrans(
    {
        "ß": "ss",
        "æ": "ae",
        "œ": "oe",
        "ø": "o",
        "đ": "d",
        "ð": "d",
        "ł": "l",
        "þ": "th",
        chr(0x131): "i",
    }
)
_NOT_SLUG = re.compile(r"[^a-z0-9]+")
_PERCENT = re.compile(r"%[0-9a-fA-F]{2}")
_HOST = re.compile(r"[a-z0-9]([a-z0-9._-]*[a-z0-9])?")
_IPV6 = re.compile(r"[0-9a-f:.]+")
_DEFAULT_PORTS = {"http": 80, "https": 443}
_ESCAPED = re.compile(r"[^\x00-\x7f]+|[()\[\]<>|\"\\`]")
_CONTROL = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})


# --- slugs and file names ----------------------------------------------------------------------


def slugify(title: str) -> str:
    """A slug for any title: `[a-z0-9-]{1,60}`, never empty, never starting or ending in `-`.

    Letters lose their accents (`å` becomes `a`), a few letters without a decomposition are
    spelled out (`ß` becomes `ss`), and everything else runs together as one `-`. A title with
    no letter or digit at all becomes `untitled`. A long title is cut at a word boundary.
    """

    folded = (
        unicodedata.normalize("NFKD", title).casefold().translate(_LETTERS_WITHOUT_DECOMPOSITION)
    )
    ascii_only = "".join(character for character in folded if not unicodedata.combining(character))
    slug = _NOT_SLUG.sub("-", ascii_only).strip("-")
    if len(slug) > MAX_SLUG_CHARS:
        cut = slug[:MAX_SLUG_CHARS]
        if slug[MAX_SLUG_CHARS] != "-" and "-" in cut:
            cut = cut[: cut.rindex("-")]
        slug = cut.strip("-")
    return slug or FALLBACK_SLUG


def is_slug(value: str) -> bool:
    """True for a string that is a whole slug: the pattern, and no `-` at either end."""

    return (
        SLUG_PATTERN.fullmatch(value) is not None
        and not value.startswith("-")
        and not value.endswith("-")
    )


def vault_filename(slug: str, record_id: UUID) -> str:
    """`<slug>-<8 hex>.md`, the hex being the last eight digits of the id (the random end)."""

    if not is_slug(slug):
        raise LibraryRefusedError("slug_invalid")
    return f"{slug}-{record_id.hex[-8:]}.md"


def is_vault_filename(name: str) -> bool:
    """True when `name` is exactly a file name that `vault_filename` can produce."""

    found = FILENAME_PATTERN.fullmatch(name)
    return found is not None and is_slug(name[: -len("-00000000.md")])


def title_key(title: str) -> str:
    """The key a `[[Title]]` link resolves through: NFC, case-folded, whitespace collapsed."""

    collapsed = " ".join(unicodedata.normalize("NFC", title).split())
    return unicodedata.normalize("NFC", collapsed.casefold())[:MAX_TITLE_KEY_CHARS]


# --- addresses ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceUrl:
    """An accepted address: what to keep and show, what to compare by, and where it points."""

    url: str
    key: str
    domain: str


def parse_source_url(raw: str) -> SourceUrl:
    """The address `raw` as a `SourceUrl`, or a refusal. The address is never fetched.

    `url` is `raw` trimmed, with its scheme and host in lower case and international characters
    and the characters ( ) [ ] < > | " \\ and ` written as percent escapes, so it satisfies the
    `^https?://` rule and cannot close a Markdown link or a quoted value. `key` is the SHA-256 of
    `normalise_url(raw)`, and two spellings of the same page share it. `domain` is the host in
    ASCII (punycode for an international name).
    """

    parts, host = _split(raw)
    display = SplitResult(
        parts.scheme.lower(),
        _netloc(parts, host),
        parts.path,
        parts.query,
        parts.fragment,
    )
    key = hashlib.sha256(normalise_url(raw).encode("ascii")).hexdigest()
    return SourceUrl(url=display.geturl(), key=key, domain=host)


def normalise_url(raw: str) -> str:
    """The comparable form: lower-case scheme and host, default port and fragment removed,
    `utm_*`, `fbclid` and `gclid` parameters removed, percent escapes in capitals, and `/` for an
    empty path. The order of the other parameters is kept, because it can matter to the page.
    """

    parts, host = _split(raw)
    path = _upper_escapes(parts.path) or "/"
    kept = [
        segment
        for segment in parts.query.split("&")
        if segment and not _is_tracking(segment.split("=", 1)[0])
    ]
    query = f"?{_upper_escapes('&'.join(kept))}" if kept else ""
    return f"{parts.scheme.lower()}://{_netloc(parts, host)}{path}{query}"


def _is_tracking(name: str) -> bool:
    lowered = name.lower()
    return lowered.startswith(TRACKING_PREFIX) or lowered in TRACKING_PARAMETERS


def _upper_escapes(value: str) -> str:
    return _PERCENT.sub(lambda found: found.group().upper(), value)


def _escape_unsafe(value: str) -> str:
    return _ESCAPED.sub(lambda found: quote(found.group()), value)


def _split(raw: str) -> tuple[SplitResult, str]:
    """The address in ASCII (path, query and fragment escaped) and its host, or a refusal."""

    text = raw.strip()
    if len(text) > MAX_URL_CHARS:
        raise LibraryRefusedError("url_too_long")
    if any(
        character.isspace() or unicodedata.category(character) in _CONTROL for character in text
    ):
        raise LibraryRefusedError("url_invalid")
    try:
        parts = urlsplit(text)
        _ = parts.port  # reading it is what validates the port
    except ValueError as error:
        raise LibraryRefusedError("url_invalid") from error
    if parts.scheme.lower() not in _DEFAULT_PORTS:
        raise LibraryRefusedError("url_scheme_refused")
    if "@" in parts.netloc or "\\" in parts.netloc:
        raise LibraryRefusedError("url_credentials_refused")
    host = _host(parts)
    escaped = SplitResult(
        parts.scheme,
        parts.netloc,
        _escape_unsafe(parts.path),
        _escape_unsafe(parts.query),
        _escape_unsafe(parts.fragment),
    )
    return escaped, host


def _host(parts: SplitResult) -> str:
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise LibraryRefusedError("url_host_missing")
    if not host.isascii():
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError as error:
            raise LibraryRefusedError("url_invalid") from error
    if len(host) > MAX_HOST_CHARS:
        raise LibraryRefusedError("url_invalid")
    pattern = _IPV6 if ":" in host else _HOST
    if pattern.fullmatch(host) is None:
        raise LibraryRefusedError("url_invalid")
    return host


def _netloc(parts: SplitResult, host: str) -> str:
    shown = f"[{host}]" if ":" in host else host
    port = parts.port
    if port is not None and port != _DEFAULT_PORTS[parts.scheme.lower()]:
        return f"{shown}:{port}"
    return shown
