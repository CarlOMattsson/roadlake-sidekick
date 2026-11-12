"""Pure unit tests for the vCard and Markdown renderings of an owner export."""

from typing import Any

import pytest

from sidekick.owner_export.formats import ExportFormatError, contacts_to_vcard, journal_to_markdown

ANNA_ID = "00000000-0000-7000-8000-00000000c001"
KLAS_ID = "00000000-0000-7000-8000-00000000c002"
ENTRY_ID = "00000000-0000-7000-8000-00000000e001"
OTHER_ENTRY_ID = "00000000-0000-7000-8000-00000000e002"


def export_with(**collections: list[dict[str, Any]]) -> dict[str, Any]:
    return {"collections": collections}


def unfold(text: str) -> list[str]:
    """Undo RFC 6350 folding: CRLF followed by one space continues the previous line."""

    return text.replace("\r\n ", "").split("\r\n")[:-1]


def physical_lines(text: str) -> list[str]:
    return text.split("\r\n")[:-1]


def contact(**values: object) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": ANNA_ID,
        "display_name": "Anna",
        "organization": None,
        "role": None,
        "email": None,
        "phone": None,
        "context_note": None,
    }
    row.update(values)
    return row


def entry(**values: object) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": ENTRY_ID,
        "journal_date": "2026-10-27",
        "title": "Möten med Anna",
        "summary": None,
        "key_points": [],
        "occurred_at": None,
        "created_at": "2026-10-27T10:00:00+00:00",
    }
    row.update(values)
    return row


# vCard


def test_contact_fields_are_written_with_rfc_6350_escaping() -> None:
    document = export_with(
        contacts=[
            contact(
                display_name="Lindström; Anna, Maria",
                organization="Åsa Bygg; AB",
                role="Förvaltare, konsult",
                email="anna.lindstrom@example.com",
                phone="+46 70-174 06 05",
                address="Storgatan 1, Stockholm\nSverige",
                relationship="syster",
                context_note="Träffades på mässan\nDet är \\ ok; tack, hej",
            )
        ]
    )

    lines = unfold(contacts_to_vcard(document))

    assert lines[0] == "BEGIN:VCARD"
    assert lines[1] == "VERSION:4.0"
    assert lines[-1] == "END:VCARD"
    assert "FN:Lindström\\; Anna\\, Maria" in lines
    assert "ORG:Åsa Bygg\\; AB" in lines
    assert "ROLE:Förvaltare\\, konsult" in lines
    assert "EMAIL:anna.lindstrom@example.com" in lines
    assert "TEL;VALUE=uri:tel:+46701740605" in lines
    assert "ADR:;;Storgatan 1\\, Stockholm\\nSverige;;;;" in lines
    assert "UID:urn:uuid:" + ANNA_ID in lines
    assert "NOTE:Relation: syster\\nTräffades på mässan\\nDet är \\\\ ok\\; tack\\, hej" in lines


def test_relationship_alone_becomes_the_first_note_line() -> None:
    document = export_with(contacts=[contact(relationship="kollega")])

    lines = unfold(contacts_to_vcard(document))

    assert "NOTE:Relation: kollega" in lines
    assert not any(line.startswith("RELATED") for line in lines)


def test_aliases_become_nickname_lines_of_their_own_contact_only() -> None:
    document = export_with(
        contacts=[contact(display_name="Anna"), contact(id=KLAS_ID, display_name="Klas")],
        contact_aliases=[
            {"contact_id": ANNA_ID, "display_value": "Anna, A"},
            {"contact_id": KLAS_ID, "display_value": "Klasse"},
        ],
    )

    lines = unfold(contacts_to_vcard(document))
    anna_card = lines[: lines.index("END:VCARD") + 1]

    assert "NICKNAME:Anna\\, A" in anna_card
    assert not any(line.startswith("NICKNAME:Klasse") for line in anna_card)
    assert "NICKNAME:Klasse" in lines


def test_empty_fields_are_omitted_and_blank_strings_count_as_empty() -> None:
    document = export_with(
        contacts=[
            contact(
                display_name="Klas Ekdahl",
                organization="   ",
                role="",
                email=None,
                phone="",
                context_note="  ",
                address=" ",
                relationship="",
            )
        ]
    )

    names = [line.split(":")[0].split(";")[0] for line in unfold(contacts_to_vcard(document))]

    assert names == ["BEGIN", "VERSION", "FN", "UID", "END"]


def test_contacts_are_sorted_by_name_for_a_stable_output() -> None:
    document = export_with(
        contacts=[
            contact(id=KLAS_ID, display_name="Örjan"),
            contact(id=ANNA_ID, display_name="anna"),
        ]
    )

    fn_lines = [line for line in unfold(contacts_to_vcard(document)) if line.startswith("FN:")]

    assert fn_lines == ["FN:anna", "FN:Örjan"]


def test_missing_collections_and_no_contacts_give_empty_output() -> None:
    assert contacts_to_vcard(export_with()) == ""
    assert contacts_to_vcard({"collections": {}}) == ""


def test_lines_use_crlf_and_long_lines_fold_at_75_octets() -> None:
    note = "Åsa och Örjan träffades på mässan i Göteborg och pratade om ärendet, " * 4
    document = export_with(contacts=[contact(context_note=note)])

    text = contacts_to_vcard(document)

    assert text.endswith("\r\n")
    assert "\n" not in text.replace("\r\n", "")
    assert any(line.startswith(" ") for line in physical_lines(text))
    assert all(len(line.encode("utf-8")) <= 75 for line in physical_lines(text))
    assert "NOTE:" + note.strip().replace(",", "\\,") in unfold(text)


def test_folding_never_splits_an_escape_pair() -> None:
    # 5 octets of "NOTE:" plus 69 letters fill 74 octets, so the escape "\;" must move whole.
    note = "x" * 69 + ";" + "tail"
    document = export_with(contacts=[contact(context_note=note)])

    physical = physical_lines(contacts_to_vcard(document))

    assert not any(line.endswith("\\") for line in physical)
    assert "NOTE:" + "x" * 69 + "\\;tail" in unfold(contacts_to_vcard(document))


# Markdown


def test_entry_becomes_a_dated_markdown_file_with_frontmatter() -> None:
    files = journal_to_markdown(
        export_with(journal_entries=[entry(summary="Vi pratade om budgeten.")])
    )

    assert list(files) == ["2026-10-27-moten-med-anna.md"]
    assert files["2026-10-27-moten-med-anna.md"] == (
        '---\ndate: 2026-10-27\ntitle: "Möten med Anna"\n---\n\n'
        "# Möten med Anna\n\nVi pratade om budgeten.\n"
    )


SOURCE_ID = "00000000-0000-7000-8000-00000000f001"


def test_the_owner_text_of_the_source_follows_the_key_points_under_a_text_heading() -> None:
    document = export_with(
        journal_sources=[
            {"id": SOURCE_ID, "raw_text": "  Hela dagboken, med åäö.\n\nAndra stycket.\n"}
        ],
        journal_entries=[
            entry(
                source_id=SOURCE_ID,
                summary="Vi pratade.",
                key_points=[{"kind": "fact", "text": "Budget 5000 kr"}],
            )
        ],
    )

    content = journal_to_markdown(document)["2026-10-27-moten-med-anna.md"]

    assert content.endswith(
        "- Fakta: Budget 5000 kr\n\n## Text\n\nHela dagboken, med åäö.\n\nAndra stycket.\n"
    )
    assert content.index("Vi pratade.") < content.index("## Nyckelpunkter")
    assert content.index("## Nyckelpunkter") < content.index("## Text")


def test_an_entry_without_a_source_text_has_no_text_heading() -> None:
    document = export_with(
        journal_sources=[{"id": SOURCE_ID, "raw_text": "Annan källa."}],
        journal_entries=[entry(source_id=None, summary="Ingen källa.")],
    )

    content = journal_to_markdown(document)["2026-10-27-moten-med-anna.md"]

    assert "## Text" not in content
    assert "Annan källa." not in content


def test_swedish_letters_and_punctuation_become_an_ascii_slug() -> None:
    files = journal_to_markdown(
        export_with(journal_entries=[entry(title="Åsa, Örebro & Ärlig: planering!")])
    )

    assert list(files) == ["2026-10-27-asa-orebro-arlig-planering.md"]


def test_same_day_and_same_title_get_a_numeric_suffix() -> None:
    files = journal_to_markdown(
        export_with(
            journal_entries=[
                entry(id=ENTRY_ID, summary="Första."),
                entry(id=OTHER_ENTRY_ID, summary="Andra."),
            ]
        )
    )

    assert set(files) == {"2026-10-27-moten-med-anna.md", "2026-10-27-moten-med-anna-2.md"}
    assert "Första." in files["2026-10-27-moten-med-anna.md"]
    assert "Andra." in files["2026-10-27-moten-med-anna-2.md"]


def test_frontmatter_quotes_the_title_and_lists_tags_only_when_present() -> None:
    files = journal_to_markdown(
        export_with(
            journal_entries=[
                entry(id=ENTRY_ID, title='Hej: "vän"', tags=["resa", "jobb, möten"]),
                entry(id=OTHER_ENTRY_ID, journal_date="2026-10-28", title="Utan taggar"),
            ]
        )
    )

    tagged = files["2026-10-27-hej-van.md"]
    untagged = files["2026-10-28-utan-taggar.md"]
    assert tagged.startswith(
        '---\ndate: 2026-10-27\ntitle: "Hej: \\"vän\\""\ntags: ["resa", "jobb, möten"]\n---\n'
    )
    assert "tags:" not in untagged


def test_key_points_get_swedish_labels_and_blank_points_are_skipped() -> None:
    files = journal_to_markdown(
        export_with(
            journal_entries=[
                entry(
                    key_points=[
                        {"kind": "decision", "text": "Köp\nny soffa"},
                        {"kind": "question", "text": "   "},
                        {"kind": "fact", "text": "Budget 5000 kr"},
                        {"kind": "odd", "text": "Okänd typ"},
                    ]
                )
            ]
        )
    )

    content = files["2026-10-27-moten-med-anna.md"]
    assert (
        "# Möten med Anna\n\n## Nyckelpunkter\n\n"
        "- Beslut: Köp ny soffa\n- Fakta: Budget 5000 kr\n- odd: Okänd typ\n"
    ) in content
    assert "Fråga" not in content


def test_the_words_the_export_writes_itself_follow_the_locale() -> None:
    document = export_with(
        journal_entries=[
            entry(
                title="  ",
                key_points=[
                    {"kind": "commitment", "text": "Ring Anna"},
                    {"kind": "question", "text": "Vem bokar?"},
                ],
            )
        ]
    )

    files = journal_to_markdown(document, "en")

    assert list(files) == ["2026-10-27-untitled.md"]
    assert (
        "# Untitled\n\n## Key points\n\n- Commitment: Ring Anna\n- Question: Vem bokar?\n"
        in (files["2026-10-27-untitled.md"])
    )
    # The default stays Swedish.
    assert list(journal_to_markdown(document)) == ["2026-10-27-utan-titel.md"]


def test_an_export_without_journal_entries_gives_no_files() -> None:
    assert journal_to_markdown(export_with()) == {}


def test_an_invalid_journal_date_is_refused() -> None:
    with pytest.raises(ExportFormatError):
        journal_to_markdown(export_with(journal_entries=[entry(journal_date="2026-13-40")]))
