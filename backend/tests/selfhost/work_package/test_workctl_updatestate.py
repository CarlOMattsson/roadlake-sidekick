"""The state files of update.sh as workctl writes them: journal, release, lock owner, snapshot."""

import os
import re
import stat
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from tools.workctl import backupfiles, cli, updatestate

NOW = datetime(2026, 11, 13, 9, 8, 7, tzinfo=UTC)
STAMP_LINE = "2026-11-13T09:08:07Z"


@pytest.fixture(autouse=True)
def _private_umask() -> Iterator[None]:
    """update.sh runs with umask 077, so new state files are 600."""
    previous = os.umask(0o077)
    yield
    os.umask(previous)


def _journal(tmp_path: Path) -> Path:
    return tmp_path / "update-state" / "journal.log"


def _state_dir(tmp_path: Path) -> Path:
    (tmp_path / "update-state").mkdir()
    return _journal(tmp_path)


def test_a_journal_line_is_utc_time_state_and_detail() -> None:
    assert (
        updatestate.journal_line("STARTED", "image=a previous=b", NOW)
        == f"{STAMP_LINE} STARTED image=a previous=b\n"
    )
    # An empty detail keeps the separating blank, as the lines of existing installations have it.
    assert updatestate.journal_line("DONE", "", NOW) == f"{STAMP_LINE} DONE \n"


def test_the_time_is_converted_to_utc() -> None:
    local = NOW.astimezone(timezone(timedelta(hours=2)))
    assert updatestate.journal_line("DONE", "", local).startswith(STAMP_LINE)


def test_entries_accumulate_and_the_earlier_lines_stay_byte_for_byte(tmp_path: Path) -> None:
    journal = _state_dir(tmp_path)
    journal.write_bytes(b"2026-01-01T00:00:00Z DONE image=x\n2026-01-02T00:00:00Z ABORTED manual\n")
    updatestate.add_journal_entry(journal, "STARTED", "image=y", lambda: NOW)
    lines = journal.read_text(encoding="utf-8").splitlines()
    assert lines == [
        "2026-01-01T00:00:00Z DONE image=x",
        "2026-01-02T00:00:00Z ABORTED manual",
        f"{STAMP_LINE} STARTED image=y",
    ]


def test_the_first_entry_creates_the_journal_with_mode_600_and_no_temporary_file_stays(
    tmp_path: Path,
) -> None:
    journal = _state_dir(tmp_path)
    updatestate.add_journal_entry(journal, "STARTED", "", lambda: NOW)
    assert stat.S_IMODE(journal.stat().st_mode) == 0o600
    assert [path.name for path in journal.parent.iterdir()] == ["journal.log"]


def test_the_file_is_flushed_before_the_rename_and_the_directory_after_it(tmp_path: Path) -> None:
    journal = _state_dir(tmp_path)
    journal.write_text("old\n", encoding="utf-8")
    seen: list[tuple[str, bool, str]] = []

    def record(path: Path) -> None:
        seen.append(
            (
                path.name,
                (journal.parent / "journal.log.tmp").exists(),
                journal.read_text(encoding="utf-8"),
            )
        )

    updatestate.add_journal_entry(journal, "DONE", "", lambda: NOW, record)
    new_content = f"old\n{STAMP_LINE} DONE \n"
    assert seen == [
        (
            "journal.log.tmp",
            True,
            "old\n",
        ),  # the new content is only in the temporary file, the journal is whole
        ("update-state", False, new_content),  # renamed, then the directory entry is flushed
    ]


def test_a_journal_written_by_workctl_is_what_the_recovery_reads(tmp_path: Path) -> None:
    journal = _state_dir(tmp_path)
    updatestate.add_journal_entry(
        journal, "STOPPING_WRITERS", "workers=backup:backup,push:push", lambda: NOW
    )
    last = journal.read_text(encoding="utf-8").splitlines()[-1]
    assert last.split()[1] == "STOPPING_WRITERS"  # update.sh reads the state as the second field
    assert re.match(r".* workers=([^ ]*)", last) is not None


def test_the_release_pointer_has_the_two_lines_compose_reads(tmp_path: Path) -> None:
    release = tmp_path / "release.env"
    flushed: list[str] = []
    updatestate.write_release(
        release, "reg/app@sha256:new", "reg/app@sha256:old", lambda path: flushed.append(path.name)
    )
    assert release.read_text(encoding="utf-8") == (
        "SIDEKICK_API_IMAGE=reg/app@sha256:new\nSIDEKICK_API_IMAGE_PREVIOUS=reg/app@sha256:old\n"
    )
    assert stat.S_IMODE(release.stat().st_mode) == 0o600
    assert flushed == ["release.env.tmp", tmp_path.name]
    assert not (tmp_path / "release.env.tmp").exists()


def test_after_a_rollback_a_pinned_installation_gets_its_pin_back(tmp_path: Path) -> None:
    release = tmp_path / "release.env"
    release.write_text(
        "SIDEKICK_API_IMAGE=failed\nSIDEKICK_API_IMAGE_PREVIOUS=pinned\n", encoding="utf-8"
    )
    updatestate.restore_release(release, "pinned", "failed")
    assert (
        release.read_text(encoding="utf-8")
        == "SIDEKICK_API_IMAGE=pinned\nSIDEKICK_API_IMAGE_PREVIOUS=failed\n"
    )


def test_after_a_rollback_an_installation_without_a_pin_loses_the_pointer(tmp_path: Path) -> None:
    release = tmp_path / "release.env"
    release.write_text(
        "SIDEKICK_API_IMAGE=failed\nSIDEKICK_API_IMAGE_PREVIOUS=local\n", encoding="utf-8"
    )
    flushed: list[str] = []
    updatestate.restore_release(release, "", "failed", lambda path: flushed.append(path.name))
    assert not release.exists()
    assert flushed == [tmp_path.name]


def test_a_missing_pointer_is_not_created_by_a_rollback(tmp_path: Path) -> None:
    release = tmp_path / "release.env"
    updatestate.restore_release(release, "pinned", "failed", lambda _path: None)
    assert not release.exists()


@pytest.mark.parametrize(
    ("content", "owner"),
    [
        ("1234\n", "1234"),
        ("1234", "1234"),
        ("", ""),
        ("abc\n", ""),
        ("12 34\n", ""),
        ("12\n34\n", ""),
        ("-5\n", ""),
    ],
)
def test_the_lock_owner_is_a_recorded_pid_or_nothing(
    tmp_path: Path, content: str, owner: str
) -> None:
    pid_file = tmp_path / "update.lock.pid"
    pid_file.write_text(content, encoding="utf-8")
    assert updatestate.lock_owner(pid_file) == owner


def test_no_pid_file_means_no_owner(tmp_path: Path) -> None:
    assert updatestate.lock_owner(tmp_path / "absent") == ""


def test_the_snapshot_name_is_a_finished_name_and_a_partial_file_is_not(tmp_path: Path) -> None:
    name = updatestate.snapshot_name(NOW)
    assert name == "sidekick-pre-20261113T090807Z.dump.enc"
    pattern = re.compile(updatestate.SNAPSHOT_PATTERN)
    assert pattern.fullmatch(name)
    assert not pattern.fullmatch(name + ".partial")
    (tmp_path / name).write_bytes(b"x")
    (tmp_path / (name + ".partial")).write_bytes(b"x")
    assert backupfiles.finished(tmp_path, pattern) == [name]


def test_the_commands_write_and_print_what_update_sh_expects(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    journal = _state_dir(tmp_path)
    assert cli.main(["journal-add", "--file", str(journal), "STARTED", "image=x"]) == 0
    assert cli.main(["journal-add", "--file", str(journal), "DONE"]) == 0
    states = [line.split()[1] for line in journal.read_text(encoding="utf-8").splitlines()]
    assert states == ["STARTED", "DONE"]
    assert journal.read_text(encoding="utf-8").endswith(" DONE \n")

    release = tmp_path / "release.env"
    assert (
        cli.main(["release-write", "--file", str(release), "--image", "a", "--previous", "b"]) == 0
    )
    assert (
        release.read_text(encoding="utf-8")
        == "SIDEKICK_API_IMAGE=a\nSIDEKICK_API_IMAGE_PREVIOUS=b\n"
    )
    assert (
        cli.main(["release-restore", "--file", str(release), "--pinned", "", "--image", "a"]) == 0
    )
    assert not release.exists()

    pid_file = tmp_path / "update.lock.pid"
    pid_file.write_text("77\n", encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["lock-owner", "--file", str(pid_file)]) == 0
    assert capsys.readouterr().out == "77\n"
    assert cli.main(["snapshot-pattern"]) == 0
    assert capsys.readouterr().out == updatestate.SNAPSHOT_PATTERN + "\n"
    assert cli.main(["snapshot-name"]) == 0
    assert re.fullmatch(updatestate.SNAPSHOT_PATTERN, capsys.readouterr().out.strip())


def test_a_replaced_file_keeps_its_mode_and_a_new_one_follows_the_umask(tmp_path: Path) -> None:
    existing = tmp_path / "existing"
    existing.write_text("old", encoding="utf-8")
    existing.chmod(0o640)
    old_umask = os.umask(0o027)
    try:
        updatestate.replace_file(existing, b"new")
        updatestate.replace_file(tmp_path / "fresh", b"new")
    finally:
        os.umask(old_umask)
    assert stat.S_IMODE(existing.stat().st_mode) == 0o640
    assert (
        stat.S_IMODE((tmp_path / "fresh").stat().st_mode) == 0o640
    )  # 0o666 without the umask's 027 bits
    existing.chmod(0o600)
    updatestate.replace_file(existing, b"again")
    assert stat.S_IMODE(existing.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    ("content", "state"),
    [
        (b"2026-01-01T00:00:00Z DONE image=x\n", "DONE"),
        (b"2026-01-01T00:00:00Z DONE image=x", "DONE"),  # no final newline
        (b"2026-01-01T00:00:00Z DONE image=x\n2026-01-02T00:00:00Z STARTED a b\n", "STARTED"),
        (b"2026-01-01T00:00:00Z DONE\n", "DONE"),
        (b"2026-01-01T00:00:00Z DONE \n", "DONE"),  # the empty detail keeps its blank
        (b"  2026-01-01T00:00:00Z \t RESUMING x\n", "RESUMING"),  # blanks and tabs separate fields
        (b"2026-01-01T00:00:00Z\n", ""),  # a line without a state
        (b"2026-01-01T00:00:00Z DONE\n\n", ""),  # a blank last line is the last line
        (b"\n", ""),
        (b"2026-01-01T00:00:00Z DONE\r\n", "DONE\r"),  # nothing is stripped
        (b"2026-01-01T00:00:00Z \xff\xfe x\n", "��"),  # bytes that are not text
    ],
)
def test_the_journal_state_is_the_second_field_of_the_last_line(
    tmp_path: Path, content: bytes, state: str
) -> None:
    journal = tmp_path / "journal.log"
    journal.write_bytes(content)
    assert updatestate.last_journal_state(journal) == state


def test_a_missing_or_empty_journal_has_no_state(tmp_path: Path) -> None:
    assert updatestate.last_journal_state(tmp_path / "absent") is None
    (tmp_path / "journal.log").write_bytes(b"")
    assert updatestate.last_journal_state(tmp_path / "journal.log") is None


def test_the_journal_state_is_what_the_journal_commands_wrote(tmp_path: Path) -> None:
    journal = _state_dir(tmp_path)
    updatestate.add_journal_entry(journal, "STARTED", "image=y", lambda: NOW)
    updatestate.add_journal_entry(journal, "DONE", "", lambda: NOW)
    assert updatestate.last_journal_state(journal) == "DONE"


@pytest.mark.parametrize(
    ("content", "key", "value"),
    [
        (
            "SIDEKICK_API_IMAGE=a@sha256:1\nSIDEKICK_API_IMAGE_PREVIOUS=b\n",
            "SIDEKICK_API_IMAGE",
            "a@sha256:1",
        ),
        (
            "SIDEKICK_API_IMAGE=a\nSIDEKICK_API_IMAGE_PREVIOUS=b\n",
            "SIDEKICK_API_IMAGE_PREVIOUS",
            "b",
        ),
        (
            "SIDEKICK_API_IMAGE=a\nSIDEKICK_API_IMAGE=c\n",
            "SIDEKICK_API_IMAGE",
            "c",
        ),  # the last line wins
        ("SIDEKICK_API_IMAGE=a", "SIDEKICK_API_IMAGE", "a"),  # no final newline
        ("SIDEKICK_API_IMAGE=\n", "SIDEKICK_API_IMAGE", ""),  # an empty value is a value
        ("SIDEKICK_API_IMAGE=a=b c\n", "SIDEKICK_API_IMAGE", "a=b c"),
        ("SIDEKICK_API_IMAGE=a\r\n", "SIDEKICK_API_IMAGE", "a\r"),  # nothing is stripped
    ],
)
def test_a_release_value_is_the_text_after_the_key_on_its_last_line(
    tmp_path: Path, content: str, key: str, value: str
) -> None:
    release = tmp_path / "release.env"
    release.write_text(content, encoding="utf-8")
    assert updatestate.release_value(release, key) == value


@pytest.mark.parametrize(
    "content",
    [
        "",
        "SIDEKICK_API_IMAGE_PREVIOUS=b\n",  # a longer name is not the key
        " SIDEKICK_API_IMAGE=a\n",  # the key starts the line
        "# SIDEKICK_API_IMAGE=a\n",
        "xSIDEKICK_API_IMAGE=a\n",
        "SIDEKICK_API_IMAGE a\n",
    ],
)
def test_a_release_pointer_without_the_key_has_no_value(tmp_path: Path, content: str) -> None:
    release = tmp_path / "release.env"
    release.write_text(content, encoding="utf-8")
    assert updatestate.release_value(release, "SIDEKICK_API_IMAGE") is None
    assert updatestate.release_value(tmp_path / "absent", "SIDEKICK_API_IMAGE") is None


def test_the_readers_print_nothing_when_there_is_nothing_and_fail_when_a_file_cannot_be_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    assert cli.main(["journal-state", "--file", str(tmp_path / "absent")]) == 0
    assert cli.main(["release-pin", "--file", str(tmp_path / "absent"), "SIDEKICK_API_IMAGE"]) == 0
    assert capsys.readouterr().out == ""

    journal = tmp_path / "journal.log"
    journal.write_text("2026-01-01T00:00:00Z DONE x\n", encoding="utf-8")
    release = tmp_path / "release.env"
    release.write_text("SIDEKICK_API_IMAGE=a\nSIDEKICK_API_IMAGE_PREVIOUS=\n", encoding="utf-8")
    assert cli.main(["journal-state", "--file", str(journal)]) == 0
    assert cli.main(["release-pin", "--file", str(release), "SIDEKICK_API_IMAGE"]) == 0
    assert cli.main(["release-pin", "--file", str(release), "SIDEKICK_API_IMAGE_PREVIOUS"]) == 0
    assert capsys.readouterr().out == "DONE\na\n\n"

    if os.geteuid() == 0:
        return  # root reads a file whatever its mode
    journal.chmod(0)
    release.chmod(0)
    assert cli.main(["journal-state", "--file", str(journal)]) == 1
    assert cli.main(["release-pin", "--file", str(release), "SIDEKICK_API_IMAGE"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "cannot be read" in captured.err
    assert str(tmp_path) not in captured.err
