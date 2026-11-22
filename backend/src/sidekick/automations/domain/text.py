"""Normalising untrusted text before it is stored, screened or shown.

Every free-text field of a suggestion goes through these functions. They remove what hides an
instruction from the person reading it and turn markup into inert text, so no later renderer has
to be trusted to escape it.
"""

import html
import re
import unicodedata
from collections.abc import Iterator
from urllib.parse import unquote

from sidekick.work.domain.ai_spec import clean_text

_TAG_START = re.compile(r"<(?=[A-Za-z/!?])")
_IMAGE_START = re.compile(r"!\[")
_INERT_ANGLE = chr(0x2039)
"""A single left-pointing angle quotation mark: what a tag-opening `<` becomes."""


def inert_markup(value: str) -> str:
    """`value` with HTML tags and Markdown images turned into plain text that cannot render."""

    without_tags = _TAG_START.sub(_INERT_ANGLE, value)
    return _IMAGE_START.sub("[image] [", without_tags)


def normalise_line(value: str) -> str:
    """One-line text: NFC, no invisible characters, collapsed whitespace, inert markup."""

    return inert_markup(" ".join(clean_text(value).split()))


def normalise_block(value: str) -> str:
    """Multi-line text: as `normalise_line`, with line breaks kept and each line trimmed."""

    lines = [line.rstrip() for line in clean_text(value, multiline=True).splitlines()]
    return inert_markup("\n".join(lines).strip())


def match_key(value: str) -> str:
    """A form of `value` for comparing two texts: NFKC, case-folded, whitespace collapsed."""

    cleaned = clean_text(unicodedata.normalize("NFKC", value))
    return " ".join(cleaned.casefold().split())


# --- readings for detection ---------------------------------------------------------------------

_LOOKALIKES = str.maketrans(
    {
        # Cyrillic letters that are drawn like a Latin one (lower case: the fold casefolds first).
        "\u0430": "a",
        "\u0432": "b",
        "\u0435": "e",
        "\u043a": "k",
        "\u043c": "m",
        "\u043d": "h",
        "\u043e": "o",
        "\u0440": "p",
        "\u0441": "c",
        "\u0442": "t",
        "\u0443": "y",
        "\u0445": "x",
        "\u0455": "s",
        "\u0456": "i",
        "\u0457": "i",
        "\u0458": "j",
        "\u04bb": "h",
        "\u04cf": "l",
        "\u0501": "d",
        "\u051b": "q",
        "\u051d": "w",
        "\u0475": "v",
        # Greek letters, after casefold (final sigma becomes sigma).
        "\u03b1": "a",
        "\u03b2": "b",
        "\u03b3": "y",
        "\u03b5": "e",
        "\u03b7": "n",
        "\u03b9": "i",
        "\u03ba": "k",
        "\u03bc": "u",
        "\u03bd": "v",
        "\u03bf": "o",
        "\u03c1": "p",
        "\u03c3": "o",
        "\u03c4": "t",
        "\u03c5": "u",
        "\u03c7": "x",
        "\u03c9": "w",
        "\u03f2": "c",
        # Latin look-alikes that compatibility folding leaves alone.
        "\u0131": "i",
        "\u0251": "a",
        "\u0261": "g",
        "\u0269": "i",
        # Punctuation that reads as a dot, a colon or a slash.
        "\u3002": ".",
        "\u2024": ".",
        "\u2215": "/",
        "\u2044": "/",
        "\u2236": ":",
        "\ua789": ":",
    }
)
_MAX_DECODE_ROUNDS = 4


def _without_marks(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return unicodedata.normalize(
        "NFC", "".join(char for char in decomposed if not unicodedata.combining(char))
    )


def folded_forms(value: str) -> tuple[str, ...]:
    """The readings of `value` that a person or a model sees through look-alike characters.

    The first is NFKC, case-folded, with look-alike Cyrillic and Greek letters turned into Latin
    ones (fullwidth and mathematical letters, a Cyrillic o inside "ignore"). The second also drops
    combining marks. A detector looks at the text as it is as well, and at these readings only to
    see what the text imitates.
    """

    compatible = unicodedata.normalize("NFKC", clean_text(value)).casefold()
    folded = clean_text(compatible).translate(_LOOKALIKES)
    stripped = _without_marks(folded)
    return (folded,) if stripped == folded else (folded, stripped)


def decoded_readings(value: str) -> Iterator[str]:
    """`value`, then each reading after HTML entities and URL escapes are undone, repeatedly.

    A text that is escaped twice (`%2569`, `&#37;69`) shows its meaning after the second round.
    """

    yield value
    current = value
    for _ in range(_MAX_DECODE_ROUNDS):
        decoded = unquote(html.unescape(current).replace("+", " "))
        if decoded == current:
            return
        yield decoded
        current = decoded


def detection_readings(value: str) -> Iterator[str]:
    """Every reading a text detector should look at: the text as cleaned, its decoded readings
    and the folded form of each."""

    seen: set[str] = set()
    for reading in decoded_readings(clean_text(value)):
        for form in (reading, *folded_forms(reading)):
            if form not in seen:
                seen.add(form)
                yield form
