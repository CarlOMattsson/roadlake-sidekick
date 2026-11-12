"""Open file formats generated from an owner export document.

Both functions are pure: they read the JSON-shaped export that `sidekick.owner_export.core`
already produced and verified, and return text or file contents. They never touch a store,
a session, or the network, and they do not change the export format. A collection that an
older schema head lacked is absent from the document and reads as empty here.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, cast

from sidekick.shared.errors.core import ValidationError
from sidekick.shared.locale import DEFAULT_LOCALE, AppLocale

_CRLF = "\r\n"
# RFC 6350 section 3.2: a content line is at most 75 octets; continuation lines begin with
# one space, so they carry at most 74 octets of content.
_VCARD_LINE_OCTETS = 75
_SLUG_MAX_LENGTH = 60


@dataclass(frozen=True)
class _ExportWords:
    """The words the Markdown export writes itself, in one app language."""

    key_point_labels: Mapping[str, str]
    key_points_heading: str
    untitled: str
    slug_fallback: str


_EXPORT_WORDS: dict[AppLocale, _ExportWords] = {
    "sv": _ExportWords(
        key_point_labels={
            "fact": "Fakta",
            "reflection": "Reflektion",
            "decision": "Beslut",
            "commitment": "Åtagande",
            "question": "Fråga",
        },
        key_points_heading="Nyckelpunkter",
        untitled="Utan titel",
        slug_fallback="post",
    ),
    "en": _ExportWords(
        key_point_labels={
            "fact": "Fact",
            "reflection": "Reflection",
            "decision": "Decision",
            "commitment": "Commitment",
            "question": "Question",
        },
        key_points_heading="Key points",
        untitled="Untitled",
        slug_fallback="entry",
    ),
}


class ExportFormatError(ValidationError):
    """A file export refused with a fixed message that names a position, never a value."""


def _rows(export: Mapping[str, Any], name: str) -> list[Mapping[str, Any]]:
    collections = cast(Mapping[str, Any], export["collections"])
    return cast(list[Mapping[str, Any]], collections.get(name, []))


def _text(row: Mapping[str, Any], field: str) -> str | None:
    """A trimmed string field; absent, non-string, and blank values all read as None."""

    value = row.get(field)
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _escape_text(value: str) -> str:
    """RFC 6350 section 3.4 text escaping: backslash, comma, semicolon and newline."""

    value = value.replace("\t", " ")
    return (
        value.replace("\\", "\\\\")
        .replace(",", "\\,")
        .replace(";", "\\;")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _fold(logical_line: str) -> list[str]:
    """Split one content line into physical lines of at most 75 octets (RFC 6350 section 3.2).

    The split happens only between characters or escape pairs, never inside a UTF-8
    sequence or inside an escaped `\\,` pair, so unfolding restores the exact line.
    """

    tokens: list[str] = []
    index = 0
    while index < len(logical_line):
        if logical_line[index] == "\\" and index + 1 < len(logical_line):
            tokens.append(logical_line[index : index + 2])
            index += 2
        else:
            tokens.append(logical_line[index])
            index += 1

    physical: list[str] = []
    current = ""
    current_octets = 0
    limit = _VCARD_LINE_OCTETS
    for token in tokens:
        size = len(token.encode("utf-8"))
        if current and current_octets + size > limit:
            physical.append(current)
            current = ""
            current_octets = 0
            limit = _VCARD_LINE_OCTETS - 1
        current += token
        current_octets += size
    physical.append(current)
    return [physical[0], *(f" {part}" for part in physical[1:])]


def _tel_uri(phone: str) -> str | None:
    """A `tel:` URI keeping only the leading plus sign and the digits (RFC 3966 subset)."""

    digits = "".join(char for char in phone if char in "0123456789")
    if not digits:
        return None
    prefix = "+" if phone.startswith("+") else ""
    return f"tel:{prefix}{digits}"


def _contact_lines(contact: Mapping[str, Any], aliases: list[str]) -> list[str]:
    display_name = _text(contact, "display_name") or "Unnamed contact"
    lines = ["BEGIN:VCARD", "VERSION:4.0", f"FN:{_escape_text(display_name)}"]
    contact_id = contact.get("id")
    if isinstance(contact_id, str) and contact_id:
        lines.append(f"UID:urn:uuid:{contact_id}")
    organization = _text(contact, "organization")
    if organization is not None:
        lines.append(f"ORG:{_escape_text(organization)}")
    role = _text(contact, "role")
    if role is not None:
        lines.append(f"ROLE:{_escape_text(role)}")
    email = _text(contact, "email")
    if email is not None:
        lines.append(f"EMAIL:{_escape_text(email)}")
    phone = _text(contact, "phone")
    tel = _tel_uri(phone) if phone is not None else None
    if tel is not None:
        lines.append(f"TEL;VALUE=uri:{tel}")
    address = _text(contact, "address")
    if address is not None:
        # RFC 6350 section 6.3.1: the free-form address is written in the street component.
        lines.append(f"ADR:;;{_escape_text(address)};;;;")
    lines.extend(f"NICKNAME:{_escape_text(alias)}" for alias in aliases)
    # RFC 6350 RELATED takes a closed TYPE vocabulary, and Sidekick's relationship is free text,
    # so the relationship is written as the first line of NOTE instead.
    note_parts: list[str] = []
    relationship = _text(contact, "relationship")
    if relationship is not None:
        note_parts.append(f"Relation: {relationship}")
    note = _text(contact, "context_note")
    if note is not None:
        note_parts.append(note)
    if note_parts:
        note_value = "\n".join(note_parts)
        lines.append(f"NOTE:{_escape_text(note_value)}")
    lines.append("END:VCARD")
    return lines


def contacts_to_vcard(export: Mapping[str, Any]) -> str:
    """Render every contact of a verified export as one vCard 4.0 card, in name order.

    Name, organization, role, email, phone, address (as ADR), aliases (as NICKNAME), and the
    relationship and context note (together in NOTE) are written when present; empty fields
    are omitted. Lines use CRLF and are folded.
    """

    aliases_by_contact: dict[str, list[str]] = {}
    for alias in _rows(export, "contact_aliases"):
        contact_id = _text(alias, "contact_id")
        display_value = _text(alias, "display_value")
        if contact_id is not None and display_value is not None:
            aliases_by_contact.setdefault(contact_id, []).append(display_value)

    contacts = sorted(
        _rows(export, "contacts"),
        key=lambda row: (
            (_text(row, "display_name") or "").casefold(),
            str(row.get("id") or ""),
        ),
    )
    output: list[str] = []
    for contact in contacts:
        contact_id = str(contact.get("id") or "")
        aliases = sorted(aliases_by_contact.get(contact_id, []), key=str.casefold)
        for logical_line in _contact_lines(contact, aliases):
            output.extend(_fold(logical_line))
    return "".join(f"{line}{_CRLF}" for line in output)


def _tags(entry: Mapping[str, Any]) -> list[str]:
    raw = entry.get("tags")
    if not isinstance(raw, list):
        return []
    return [tag.strip() for tag in cast(list[Any], raw) if isinstance(tag, str) and tag.strip()]


def _title(entry: Mapping[str, Any], words: _ExportWords) -> str:
    raw = _text(entry, "title") or ""
    return " ".join(raw.split()) or words.untitled


def _slug(title: str, fallback: str) -> str:
    """An ASCII slug; Swedish letters fold to a, a, o through NFKD decomposition."""

    ascii_text = (
        unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii").lower()
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")[:_SLUG_MAX_LENGTH].strip("-")
    return slug or fallback


def _key_point_lines(entry: Mapping[str, Any], words: _ExportWords) -> list[str]:
    raw = entry.get("key_points")
    if not isinstance(raw, list):
        return []
    lines: list[str] = []
    for item in cast(list[Any], raw):
        if not isinstance(item, Mapping):
            continue
        point = cast(Mapping[str, Any], item)
        text = _text(point, "text")
        if text is None:
            continue
        text = " ".join(text.split())
        kind = point.get("kind")
        label = words.key_point_labels.get(kind, kind) if isinstance(kind, str) else None
        lines.append(f"- {label}: {text}" if label else f"- {text}")
    return lines


def _entry_sort_key(entry: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(entry.get("journal_date") or ""),
        str(entry.get("occurred_at") or ""),
        str(entry.get("created_at") or ""),
        str(entry.get("id") or ""),
    )


def journal_to_markdown(
    export: Mapping[str, Any], locale: AppLocale = DEFAULT_LOCALE
) -> dict[str, str]:
    """Map `YYYY-MM-DD-<slug>.md` file names to Markdown documents, one per journal entry.

    Each document starts with YAML frontmatter (date, title, and tags when the entry has
    any), then the title as a heading, the summary, the key points, and the owner's own text
    under "## Text" when the entry's source has one. Name collisions on the same date get a
    numeric suffix, assigned in a deterministic order. The words the export writes itself (key-point
    labels, their heading, the untitled fallback) follow `locale`; the owner's own text does not.
    """

    words = _EXPORT_WORDS[locale]
    source_texts: dict[str, str] = {}
    for source in _rows(export, "journal_sources"):
        source_id = _text(source, "id")
        raw_text = _text(source, "raw_text")
        if source_id is not None and raw_text is not None:
            source_texts[source_id] = raw_text

    files: dict[str, str] = {}
    entries = list(enumerate(_rows(export, "journal_entries")))
    for position, entry in sorted(entries, key=lambda pair: _entry_sort_key(pair[1])):
        try:
            entry_date = date.fromisoformat(str(entry.get("journal_date"))).isoformat()
        except ValueError:
            raise ExportFormatError(
                f"journal_entries row {position} has an invalid journal_date"
            ) from None
        title = _title(entry, words)
        base = f"{entry_date}-{_slug(title, words.slug_fallback)}"
        file_name = f"{base}.md"
        suffix = 2
        while file_name in files:
            file_name = f"{base}-{suffix}.md"
            suffix += 1

        frontmatter = [
            "---",
            f"date: {entry_date}",
            f"title: {json.dumps(title, ensure_ascii=False)}",
        ]
        tags = _tags(entry)
        if tags:
            frontmatter.append(f"tags: {json.dumps(tags, ensure_ascii=False)}")
        frontmatter.append("---")

        blocks = [f"# {title}"]
        summary = _text(entry, "summary")
        if summary is not None:
            blocks.append(summary)
        key_points = _key_point_lines(entry, words)
        if key_points:
            blocks.append(f"## {words.key_points_heading}\n\n" + "\n".join(key_points))
        source_text = source_texts.get(str(entry.get("source_id") or ""))
        if source_text is not None:
            blocks.append("## Text\n\n" + source_text)
        files[file_name] = "\n".join(frontmatter) + "\n\n" + "\n\n".join(blocks) + "\n"
    return files
