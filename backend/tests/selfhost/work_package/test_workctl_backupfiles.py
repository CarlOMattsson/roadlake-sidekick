"""The backup housekeeping of tools/workctl: sets kept, free space, time stamps and pruning."""

import os
import re
from datetime import datetime
from pathlib import Path

import pytest
from tools.workctl import backupfiles, cli

MB = 1048576
DB_ERE = r"sidekick-[0-9]{8}-[0-9]{6}\.sql\.enc"
MEM_ERE = r"hindsight-[0-9]{8}-[0-9]{6}\.tar\.gz\.enc"
DUMP_ERE = r"x-[0-9]{8}-[0-9]{6}\.dump"


def _db(stamp: str) -> str:
    return f"sidekick-{stamp}.sql.enc"


def _mem(stamp: str) -> str:
    return f"hindsight-{stamp}.tar.gz.enc"


def _sets(directory: Path, days: range, size: int = 10) -> None:
    for day in days:
        for name in (_db(f"2026010{day}-000000"), _mem(f"2026010{day}-000000")):
            (directory / name).write_bytes(b"x" * size)


def _dumps(directory: Path, days: range) -> list[str]:
    names = [f"x-2026010{day}-000000.dump" for day in days]
    for name in names:
        (directory / name).write_bytes(b"x" * 10)
    return names


@pytest.mark.parametrize(
    ("value", "valid"),
    [
        ("1", True),
        ("07", True),
        ("12", True),
        ("0", False),
        ("", False),
        ("-2", False),
        ("abc", False),
        ("1.5", False),
    ],
)
def test_the_number_of_sets_kept_is_a_whole_number_of_at_least_one(value: str, valid: bool) -> None:
    assert backupfiles.valid_keep(value) is valid
    assert (cli.main(["backup-keep-valid", value]) == 0) is valid


def test_finished_lists_only_exact_regular_files_oldest_first(tmp_path: Path) -> None:
    _sets(tmp_path, range(1, 3))
    (tmp_path / _db("20260103-000000")).write_bytes(b"x")
    for other in (
        "sidekick-notes.sql.enc",
        "sidekick-20260101-000000.sql.enc.part",
        ".sidekick-20260101-000000.sql.enc",
        "xsidekick-20260101-000000.sql.enc",
    ):
        (tmp_path / other).write_text("x")
    (tmp_path / _db("20260104-000000")).symlink_to(tmp_path / _db("20260101-000000"))
    (tmp_path / _db("20260105-000000")).mkdir()
    assert backupfiles.finished(tmp_path, re.compile(DB_ERE)) == [
        _db("20260101-000000"),
        _db("20260102-000000"),
        _db("20260103-000000"),
    ]
    assert backupfiles.finished(tmp_path / "absent", re.compile(DB_ERE)) == []


def test_the_newest_size_is_taken_by_name_not_by_file_time(tmp_path: Path) -> None:
    (tmp_path / _db("20260101-000000")).write_bytes(b"x" * 5)
    (tmp_path / _db("20260102-000000")).write_bytes(b"x" * 3)
    os.utime(tmp_path / _db("20260102-000000"), (1, 1))
    assert backupfiles.newest_size(tmp_path, re.compile(DB_ERE)) == 3
    assert backupfiles.newest_size(tmp_path, re.compile(MEM_ERE)) == 0


def _free(monkeypatch: pytest.MonkeyPatch, value: int | None) -> None:
    monkeypatch.setattr(backupfiles, "free_bytes", lambda _directory: value)


def test_the_first_backup_needs_only_the_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _free(monkeypatch, 64 * MB - 1)
    assert backupfiles.check_space(tmp_path, {}, [DB_ERE]) == backupfiles.SpaceCheck(
        backupfiles.TOO_LITTLE, 64 * MB, 64 * MB - 1
    )
    _free(monkeypatch, 64 * MB)
    assert backupfiles.check_space(tmp_path, {}, [DB_ERE]).outcome == backupfiles.ENOUGH


def test_later_backups_need_the_newest_of_each_kind_times_the_margin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sets(tmp_path, range(1, 3), size=4096)
    environment = {"SIDEKICK_BACKUP_SPACE_FLOOR_MB": "0"}
    patterns = [DB_ERE, MEM_ERE]
    _free(monkeypatch, 12287)
    assert backupfiles.check_space(tmp_path, environment, patterns) == backupfiles.SpaceCheck(
        backupfiles.TOO_LITTLE, 12288, 12287
    )
    _free(monkeypatch, 12288)
    assert backupfiles.check_space(tmp_path, environment, patterns).outcome == backupfiles.ENOUGH
    doubled = {**environment, "SIDEKICK_BACKUP_SPACE_MARGIN_PCT": "200"}
    assert backupfiles.check_space(tmp_path, doubled, patterns).needed == 16384
    # An empty setting counts as unset.
    unset = {**environment, "SIDEKICK_BACKUP_SPACE_MARGIN_PCT": ""}
    assert backupfiles.check_space(tmp_path, unset, patterns).needed == 12288
    # One kind alone is half of that.
    assert backupfiles.check_space(tmp_path, environment, [DB_ERE]).needed == 6144


def test_the_floor_wins_over_a_small_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _dumps(tmp_path, range(1, 2))
    _free(monkeypatch, 2 * MB - 1)
    check = backupfiles.check_space(tmp_path, {"SIDEKICK_BACKUP_SPACE_FLOOR_MB": "2"}, [DUMP_ERE])
    assert check == backupfiles.SpaceCheck(backupfiles.TOO_LITTLE, 2 * MB, 2 * MB - 1)


@pytest.mark.parametrize(
    "environment",
    [
        {"SIDEKICK_BACKUP_SPACE_MARGIN_PCT": "99"},
        {"SIDEKICK_BACKUP_SPACE_MARGIN_PCT": "abc"},
        {"SIDEKICK_BACKUP_SPACE_FLOOR_MB": "-1"},
    ],
)
def test_an_invalid_setting_is_a_refusal_never_enough(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, environment: dict[str, str]
) -> None:
    _free(monkeypatch, 10**12)
    assert backupfiles.check_space(tmp_path, environment, [DB_ERE]).outcome == backupfiles.UNKNOWN


def test_a_free_size_that_cannot_be_read_is_a_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _free(monkeypatch, None)
    assert backupfiles.check_space(tmp_path, {}, [DB_ERE]) == backupfiles.SpaceCheck(
        backupfiles.UNKNOWN, 64 * MB, 0
    )


def test_the_real_free_size_of_a_directory_is_read(tmp_path: Path) -> None:
    free = backupfiles.free_bytes(tmp_path)
    assert free is not None and free > 0


def test_the_stamp_waits_while_the_set_exists(tmp_path: Path) -> None:
    (tmp_path / _db("20261102-100000")).write_bytes(b"x")
    times = iter(
        [
            datetime(2026, 11, 2, 10, 0, 0),
            datetime(2026, 11, 2, 10, 0, 0),
            datetime(2026, 11, 2, 10, 0, 1),
        ]
    )
    slept: list[float] = []
    stamp = backupfiles.next_stamp(tmp_path, now=lambda: next(times), sleep=slept.append)
    assert stamp == "20261102-100001"
    assert slept == [1, 1]


def test_the_stamp_also_waits_for_a_lone_memory_archive(tmp_path: Path) -> None:
    (tmp_path / _mem("20261102-100000")).write_bytes(b"x")
    times = iter([datetime(2026, 11, 2, 10, 0, 0), datetime(2026, 11, 2, 10, 0, 5)])
    assert (
        backupfiles.next_stamp(tmp_path, now=lambda: next(times), sleep=lambda _s: None)
        == "20261102-100005"
    )


def test_prune_keeps_the_newest_and_the_protected_file(tmp_path: Path) -> None:
    names = _dumps(tmp_path, range(1, 8))
    assert backupfiles.prune(tmp_path, 2, DUMP_ERE, names[0]) == 4
    assert sorted(os.listdir(tmp_path)) == [names[0], names[5], names[6]]


def test_prune_with_keep_one_still_keeps_the_newest(tmp_path: Path) -> None:
    names = _dumps(tmp_path, range(1, 4))
    assert backupfiles.prune(tmp_path, 1, DUMP_ERE, names[1]) == 1
    assert sorted(os.listdir(tmp_path)) == [names[1], names[2]]


def test_prune_never_touches_other_names_or_symlinks(tmp_path: Path) -> None:
    names = _dumps(tmp_path, range(1, 5))
    others = [
        "x-20260101-000000.dump.partial",
        ".x-20260101-000000.dump",
        "x-20260101-000000.dump.bak",
        "notes.txt",
        "x-2026-000000.dump",
    ]
    for other in others:
        (tmp_path / other).write_bytes(b"x")
    outside = tmp_path.parent / f"{tmp_path.name}-outside.dump"
    outside.write_bytes(b"precious")
    (tmp_path / "x-20260100-000000.dump").symlink_to(outside)
    backupfiles.prune(tmp_path, 1, DUMP_ERE, names[3])
    remaining = set(os.listdir(tmp_path))
    assert set(others) <= remaining
    assert "x-20260100-000000.dump" in remaining and outside.read_bytes() == b"precious"
    assert names[3] in remaining and not set(names[:3]) & remaining


@pytest.mark.parametrize("protected", ["", "x-20269999-000000.dump", "x-20260104-000000.dump"])
def test_prune_does_nothing_unless_the_protected_file_exists_and_is_not_empty(
    tmp_path: Path, protected: str
) -> None:
    names = _dumps(tmp_path, range(1, 5))
    (tmp_path / "x-20260104-000000.dump").write_bytes(
        b""
    )  # the newest is empty: not a finished backup
    assert backupfiles.prune(tmp_path, 1, DUMP_ERE, protected) == 0
    assert sorted(os.listdir(tmp_path)) == names


def test_prune_does_not_follow_a_symlinked_protected_file(tmp_path: Path) -> None:
    names = _dumps(tmp_path, range(1, 4))
    (tmp_path / "x-20260109-000000.dump").symlink_to(tmp_path / names[2])
    assert backupfiles.prune(tmp_path, 1, DUMP_ERE, "x-20260109-000000.dump") == 0
    assert len(os.listdir(tmp_path)) == 4


def test_the_prune_command_prints_the_count_and_refuses_a_bad_keep(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _sets(tmp_path, range(1, 4))
    args = [
        "backup-prune",
        "--dir",
        str(tmp_path),
        "--pattern",
        DB_ERE,
        "--protected",
        _db("20260103-000000"),
    ]
    assert cli.main([*args, "--keep", "0"]) == 1
    assert len(list(tmp_path.glob("sidekick-*"))) == 3
    assert cli.main([*args, "--keep", "1"]) == 0
    assert capsys.readouterr().out == "2\n"
    assert (
        len(list(tmp_path.glob("sidekick-*"))) == 1 and len(list(tmp_path.glob("hindsight-*"))) == 3
    )


def test_the_space_command_prints_needed_and_free_and_tells_the_outcome_by_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["backup-space", "--dir", str(tmp_path), "--pattern", DB_ERE]
    _free(monkeypatch, 1000)
    assert cli.main(args) == 1
    assert capsys.readouterr().out == f"{64 * MB} 1000\n"
    _free(monkeypatch, None)
    assert cli.main(args) == cli.BACKUP_SPACE_UNKNOWN
    _free(monkeypatch, 64 * MB)
    assert cli.main(args) == 0


def test_the_preflight_names_a_bad_keep_in_the_language_asked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = [
        "backup-preflight",
        "--lang",
        "en",
        "--dir",
        str(tmp_path),
        "--pattern",
        DB_ERE,
        "--keep",
        "0",
    ]
    assert cli.main(args) == 1
    assert (
        capsys.readouterr().err
        == "SIDEKICK_WORK_KEEP_BACKUPS=0 is not a whole number of at least 1. Nothing changed.\n"
    )


def test_the_preflight_reports_missing_room_with_both_sizes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    args = [
        "backup-preflight",
        "--lang",
        "sv",
        "--dir",
        str(tmp_path),
        "--pattern",
        DB_ERE,
        "--keep",
        "7",
    ]
    _free(monkeypatch, 1000)
    assert cli.main(args) == 1
    assert f"1000 byte ledigt, {64 * MB} behövs" in capsys.readouterr().err
    _free(monkeypatch, None)
    assert cli.main(args) == 1
    assert "Kunde inte avgöra" in capsys.readouterr().err
    _free(monkeypatch, 64 * MB)
    assert cli.main(args) == 0


def test_the_stamp_command_prints_a_stamp(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["backup-stamp", "--dir", str(tmp_path)]) == 0
    assert len(capsys.readouterr().out.strip()) == len("20261102-100000")
