"""CLI tests for the `vcard` and `markdown` commands, using only temporary files."""

import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from sidekick.owner_export import cli as owner_export_cli
from sidekick.owner_export.core import EXPORT_SOURCES, build_export_document

OWNER_ID = UUID("00000000-0000-7000-8000-000000000001")
ANNA_ID = "00000000-0000-7000-8000-00000000c001"
ENTRY_ID = "00000000-0000-7000-8000-00000000e001"
SOURCE_ID = "00000000-0000-7000-8000-00000000f001"
EXPORTED_AT = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


def full_row(source_name: str, **values: object) -> dict[str, Any]:
    """A row carrying every non-derived column of its table, so the export verifies."""

    source = next(source for source in EXPORT_SOURCES if source.name == source_name)
    row: dict[str, Any] = {
        column.name: None for column in source.row_type.__table__.columns if column.computed is None
    }
    row["owner_id"] = str(OWNER_ID)
    row.update(values)
    return row


def write_export(tmp_path: Path, **collections: list[dict[str, Any]]) -> Path:
    catalogue: dict[str, list[dict[str, Any]]] = {source.name: [] for source in EXPORT_SOURCES}
    catalogue.update(collections)
    document = build_export_document(OWNER_ID, catalogue, exported_at=EXPORTED_AT)
    path = tmp_path / "export.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


def test_vcard_command_writes_the_contacts_and_reports_the_count(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    export = write_export(
        tmp_path,
        contacts=[
            full_row(
                "contacts",
                id=ANNA_ID,
                display_name="Lindström; Anna, Maria",
                display_name_key="lindström; anna, maria",
                email="anna@example.com",
                archived=False,
                version=1,
            )
        ],
    )
    output = tmp_path / "contacts.vcf"

    assert owner_export_cli.main(["vcard", str(export), str(output)]) == 0

    data = output.read_bytes().decode("utf-8")
    assert "FN:Lindström\\; Anna\\, Maria\r\n" in data
    assert "EMAIL:anna@example.com\r\n" in data
    assert data.endswith("END:VCARD\r\n")
    assert json.loads(capsys.readouterr().out) == {"contact_count": 1}


def test_vcard_command_refuses_to_overwrite_an_existing_file(tmp_path: Path) -> None:
    export = write_export(tmp_path)
    output = tmp_path / "contacts.vcf"
    output.write_bytes(b"keep me")

    assert owner_export_cli.main(["vcard", str(export), str(output)]) == 1

    assert output.read_bytes() == b"keep me"


def test_vcard_command_refuses_a_tampered_export_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    export = write_export(
        tmp_path,
        contacts=[full_row("contacts", id=ANNA_ID, display_name="Anna")],
    )
    document = json.loads(export.read_text(encoding="utf-8"))
    document["collections"]["contacts"][0]["display_name"] = "Forged"
    export.write_text(json.dumps(document), encoding="utf-8")
    output = tmp_path / "contacts.vcf"

    assert owner_export_cli.main(["vcard", str(export), str(output)]) == 1

    assert not output.exists()
    assert "vcard export refused" in capsys.readouterr().err


def test_markdown_command_writes_one_file_per_entry_into_a_new_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    export = write_export(
        tmp_path,
        journal_sources=[full_row("journal_sources", id=SOURCE_ID, raw_text="Hela dagboken.")],
        journal_entries=[
            full_row(
                "journal_entries",
                id=ENTRY_ID,
                source_id=SOURCE_ID,
                journal_date="2026-10-27",
                title="Möten med Anna",
                summary="Vi pratade om budgeten.",
                key_points=[],
            )
        ],
    )
    output_dir = tmp_path / "dagbok" / "2026"

    assert owner_export_cli.main(["markdown", str(export), str(output_dir)]) == 0

    assert sorted(path.name for path in output_dir.iterdir()) == ["2026-10-27-moten-med-anna.md"]
    content = (output_dir / "2026-10-27-moten-med-anna.md").read_bytes().decode("utf-8")
    assert content.startswith('---\ndate: 2026-10-27\ntitle: "Möten med Anna"\n---\n')
    assert "Vi pratade om budgeten." in content
    assert content.endswith("## Text\n\nHela dagboken.\n")
    assert json.loads(capsys.readouterr().out) == {"entry_count": 1}


def test_markdown_command_refuses_an_existing_file_and_writes_nothing_else(
    tmp_path: Path,
) -> None:
    export = write_export(
        tmp_path,
        journal_entries=[
            full_row(
                "journal_entries",
                id=ENTRY_ID,
                journal_date="2026-10-27",
                title="Möten med Anna",
                key_points=[],
            )
        ],
    )
    output_dir = tmp_path / "dagbok"
    output_dir.mkdir()
    existing = output_dir / "2026-10-27-moten-med-anna.md"
    existing.write_bytes(b"keep me")

    assert owner_export_cli.main(["markdown", str(export), str(output_dir)]) == 1

    assert existing.read_bytes() == b"keep me"
    assert sorted(path.name for path in output_dir.iterdir()) == [existing.name]


def test_both_commands_never_open_the_database_or_read_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the export commands must not touch the database")

    monkeypatch.setattr(owner_export_cli, "get_settings", refuse)
    monkeypatch.setattr(owner_export_cli, "SqlAlchemyStore", refuse)
    monkeypatch.setattr(owner_export_cli, "create_session_factory", refuse)
    export = write_export(
        tmp_path,
        contacts=[full_row("contacts", id=ANNA_ID, display_name="Anna")],
        journal_entries=[
            full_row("journal_entries", id=ENTRY_ID, journal_date="2026-10-27", title="Dag")
        ],
    )

    assert owner_export_cli.main(["vcard", str(export), str(tmp_path / "a.vcf")]) == 0
    assert owner_export_cli.main(["markdown", str(export), str(tmp_path / "md")]) == 0


def test_markdown_words_follow_the_locale_flag_or_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    export = write_export(
        tmp_path,
        journal_entries=[
            full_row("journal_entries", id=ENTRY_ID, journal_date="2026-10-27", title=" ")
        ],
    )
    monkeypatch.delenv("SIDEKICK_MCP_APP_LOCALE", raising=False)

    assert owner_export_cli.main(["markdown", str(export), str(tmp_path / "sv")]) == 0
    assert [path.name for path in (tmp_path / "sv").iterdir()] == ["2026-10-27-utan-titel.md"]

    assert (
        owner_export_cli.main(["markdown", str(export), str(tmp_path / "en"), "--locale", "en"])
        == 0
    )
    assert [path.name for path in (tmp_path / "en").iterdir()] == ["2026-10-27-untitled.md"]

    monkeypatch.setenv("SIDEKICK_MCP_APP_LOCALE", "en")
    assert owner_export_cli.main(["markdown", str(export), str(tmp_path / "env")]) == 0
    assert [path.name for path in (tmp_path / "env").iterdir()] == ["2026-10-27-untitled.md"]


def test_written_files_are_private_and_new_directories_are_owner_only(tmp_path: Path) -> None:
    export = write_export(
        tmp_path,
        contacts=[full_row("contacts", id=ANNA_ID, display_name="Anna")],
        journal_entries=[
            full_row("journal_entries", id=ENTRY_ID, journal_date="2026-10-27", title="Dag")
        ],
    )
    output_dir = tmp_path / "private" / "dagbok"
    previous = os.umask(0o022)
    try:
        assert owner_export_cli.main(["vcard", str(export), str(tmp_path / "a.vcf")]) == 0
        assert owner_export_cli.main(["markdown", str(export), str(output_dir)]) == 0
    finally:
        os.umask(previous)

    assert stat.S_IMODE((tmp_path / "a.vcf").stat().st_mode) == 0o600
    assert stat.S_IMODE(output_dir.stat().st_mode) == 0o700
    (note,) = output_dir.iterdir()
    assert stat.S_IMODE(note.stat().st_mode) == 0o600


def test_a_malformed_field_is_reported_by_position_and_never_by_value(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    marker = "SECRET-MARKER-4711"
    export = write_export(
        tmp_path,
        journal_entries=[
            full_row("journal_entries", id=ENTRY_ID, journal_date=marker, title=marker)
        ],
    )
    output_dir = tmp_path / "dagbok"

    assert owner_export_cli.main(["markdown", str(export), str(output_dir)]) == 1

    err = capsys.readouterr().err
    assert marker not in err
    assert "journal_entries row 0 has an invalid journal_date" in err
    assert not output_dir.exists()


def test_unexpected_errors_print_a_fixed_message_without_their_own_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = "SECRET-MARKER-4711"

    def explode(_document: object) -> str:
        raise ValueError(f"bad value {marker}")

    monkeypatch.setattr(owner_export_cli, "contacts_to_vcard", explode)
    export = write_export(tmp_path)

    assert owner_export_cli.main(["vcard", str(export), str(tmp_path / "a.vcf")]) == 1

    err = capsys.readouterr().err
    assert marker not in err
    assert "export content could not be read" in err


def test_new_intermediate_directories_are_owner_only_even_under_a_loose_umask(
    tmp_path: Path,
) -> None:
    export = write_export(
        tmp_path,
        journal_entries=[
            full_row("journal_entries", id=ENTRY_ID, journal_date="2026-10-27", title="Dag")
        ],
    )
    output_dir = tmp_path / "a" / "b" / "c"
    previous = os.umask(0o000)
    try:
        assert owner_export_cli.main(["markdown", str(export), str(output_dir)]) == 0
    finally:
        os.umask(previous)

    for directory in (tmp_path / "a", tmp_path / "a" / "b", output_dir):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700


def test_a_symlinked_output_directory_is_refused_and_nothing_is_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    export = write_export(
        tmp_path,
        contacts=[full_row("contacts", id=ANNA_ID, display_name="Anna")],
        journal_entries=[
            full_row("journal_entries", id=ENTRY_ID, journal_date="2026-10-27", title="Dag")
        ],
    )
    target = tmp_path / "elsewhere"
    target.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)

    assert owner_export_cli.main(["markdown", str(export), str(link)]) == 1
    assert owner_export_cli.main(["vcard", str(export), str(link / "a.vcf")]) == 1

    assert list(target.iterdir()) == []
    assert "output directory must be a real directory" in capsys.readouterr().err


def test_a_directory_open_to_others_is_refused_for_markdown_but_fine_for_vcard(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    export = write_export(
        tmp_path,
        contacts=[full_row("contacts", id=ANNA_ID, display_name="Anna")],
        journal_entries=[
            full_row("journal_entries", id=ENTRY_ID, journal_date="2026-10-27", title="Dag")
        ],
    )
    open_dir = tmp_path / "open"
    open_dir.mkdir()
    open_dir.chmod(0o755)

    assert owner_export_cli.main(["markdown", str(export), str(open_dir)]) == 1
    assert list(open_dir.iterdir()) == []
    assert "output directory must not be accessible to others" in capsys.readouterr().err

    assert owner_export_cli.main(["vcard", str(export), str(open_dir / "a.vcf")]) == 0
    assert stat.S_IMODE((open_dir / "a.vcf").stat().st_mode) == 0o600
    assert stat.S_IMODE(open_dir.stat().st_mode) == 0o755


def test_a_directory_swapped_in_after_mkdir_is_refused_not_adopted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    export = write_export(
        tmp_path,
        journal_entries=[
            full_row("journal_entries", id=ENTRY_ID, journal_date="2026-10-27", title="Dag")
        ],
    )
    output_dir = tmp_path / "dagbok"

    real_mkdir = os.mkdir

    def swapped_in(path: Path, _mode: int = 0o777) -> None:
        real_mkdir(path)
        Path(path).chmod(0o755)

    monkeypatch.setattr(owner_export_cli.os, "mkdir", swapped_in)

    assert owner_export_cli.main(["markdown", str(export), str(output_dir)]) == 1

    assert stat.S_IMODE(output_dir.stat().st_mode) == 0o755
    assert list(output_dir.iterdir()) == []
    assert "output directory must not be accessible to others" in capsys.readouterr().err
