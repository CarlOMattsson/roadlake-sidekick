"""Backup free-space floor, the number of sets kept and exact-name pruning."""

import time
from pathlib import Path

import pytest

from tests.selfhost.work_package.support import (
    MIGRATE,
    backup_key,
    docker_calls,
    make_clone,
    ready_repo,
    run_work,
)


def _fake_df(repo: Path, **env: str) -> dict[str, str]:
    """A `df -Pk` that answers FAKE_DF_AVAIL_KIB (or fails with FAKE_DF_BROKEN=1)."""

    df = repo / "bin" / "df"
    df.write_text(
        '#!/bin/sh\n[ "${FAKE_DF_BROKEN:-0}" = 1 ] && exit 1\n'
        'echo "Filesystem 1024-blocks Used Available Capacity Mounted on"\n'
        'echo "fake 100000000 1 ${FAKE_DF_AVAIL_KIB:-100000000} 1% /"\n',
        encoding="utf-8",
    )
    df.chmod(0o755)
    return env


def _seed_sets(work: Path, days: range, size: int = 100) -> None:
    backups = work / "backups"
    backups.mkdir(exist_ok=True)
    backup_key(work)
    for day in days:
        for name in (
            f"sidekick-2026010{day}-000000.sql.enc",
            f"hindsight-2026010{day}-000000.tar.gz.enc",
        ):
            (backups / name).write_bytes(b"x" * size)


def _no_database_work_done(repo: Path) -> bool:
    calls = (
        (repo / "docker-calls.txt").read_text(encoding="utf-8")
        if (repo / "docker-calls.txt").exists()
        else ""
    )
    return "pg_dump" not in calls and "stop " not in calls and "pause" not in calls


def test_backup_refuses_before_pausing_anything_when_the_disk_is_too_full(
    mini_repo: Path,
) -> None:
    work = ready_repo(mini_repo)
    _seed_sets(work, range(1, 3), size=4096)
    _fake_df(mini_repo)
    # Needed: (4096 + 4096) * 150 / 100 = 12288 bytes (floor 0); 11 KiB is free.
    result = run_work(
        mini_repo,
        "backup",
        SIDEKICK_BACKUP_SPACE_FLOOR_MB="0",
        FAKE_DF_AVAIL_KIB="11",
    )
    assert result.returncode == 1
    assert "För lite ledigt utrymme" in result.stderr
    assert "11264 byte ledigt, 12288 behövs" in result.stderr
    assert _no_database_work_done(mini_repo)
    assert len(list((work / "backups").glob("sidekick-*.sql.enc"))) == 2, "nothing pruned"


def test_backup_runs_when_the_room_is_just_enough(mini_repo: Path) -> None:
    work = ready_repo(mini_repo)
    _seed_sets(work, range(1, 3), size=4096)
    _fake_df(mini_repo)
    result = run_work(
        mini_repo,
        "backup",
        SIDEKICK_BACKUP_SPACE_FLOOR_MB="0",
        FAKE_DF_AVAIL_KIB="12",
    )
    assert result.returncode == 0, result.stderr


def test_the_floor_applies_when_there_is_no_earlier_backup(mini_repo: Path) -> None:
    ready_repo(mini_repo)
    _fake_df(mini_repo)
    result = run_work(mini_repo, "backup", FAKE_DF_AVAIL_KIB="1000")  # 1000 KiB free, floor 64 MiB
    assert result.returncode == 1
    assert "För lite ledigt utrymme" in result.stderr
    assert _no_database_work_done(mini_repo)


@pytest.mark.parametrize(
    "env",
    [
        {"FAKE_DF_BROKEN": "1"},
        {"SIDEKICK_BACKUP_SPACE_MARGIN_PCT": "99"},
        {"SIDEKICK_BACKUP_SPACE_MARGIN_PCT": "abc"},
    ],
)
def test_a_free_size_that_cannot_be_judged_refuses_the_backup(
    mini_repo: Path, env: dict[str, str]
) -> None:
    ready_repo(mini_repo)
    _fake_df(mini_repo)
    result = run_work(mini_repo, "backup", **env)
    assert result.returncode == 1
    assert "Kunde inte avgöra" in result.stderr
    assert _no_database_work_done(mini_repo)


def test_update_with_too_little_room_changes_nothing(
    mini_repo: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    make_clone(mini_repo, tmp_path_factory.mktemp("origin"))
    work = ready_repo(mini_repo)
    _fake_df(mini_repo)
    result = run_work(mini_repo, "update", FAKE_DF_AVAIL_KIB="1000")
    assert result.returncode == 1
    assert "För lite ledigt utrymme" in result.stderr
    calls = docker_calls(mini_repo)
    assert MIGRATE not in calls and "--force-recreate" not in calls
    assert not list((work / "backups").glob("*"))


def test_the_number_of_backups_kept_is_configurable(mini_repo: Path) -> None:
    work = ready_repo(mini_repo)
    _seed_sets(work, range(1, 10))
    result = run_work(mini_repo, "backup", SIDEKICK_WORK_KEEP_BACKUPS="3")
    assert result.returncode == 0, result.stderr
    backups = work / "backups"
    assert len(list(backups.glob("sidekick-*.sql.enc"))) == 3
    assert len(list(backups.glob("hindsight-*.tar.gz.enc"))) <= 3
    today = time.strftime("%Y%m%d")
    assert any(today in path.name for path in backups.glob("sidekick-*.sql.enc"))


def test_pruning_touches_only_exact_finished_names_and_keeps_the_newest_set(
    mini_repo: Path,
) -> None:
    work = ready_repo(mini_repo)
    _seed_sets(work, range(1, 10))
    backups = work / "backups"
    others = [
        backups / "sidekick-notes.sql.enc",
        backups / "sidekick-20260101-000000.sql.enc.part",
        backups / "sidekick-20260101-000000.sql",
        backups / "hindsight-20260101-000000.tar.gz",
        backups / ".sidekick-20260101-000000.sql.enc",
    ]
    for path in others:
        path.write_text("keep me", encoding="utf-8")
    result = run_work(mini_repo, "backup", SIDEKICK_WORK_KEEP_BACKUPS="1")
    assert result.returncode == 0, result.stderr
    assert all(path.exists() for path in others)
    (kept,) = backups.glob("sidekick-[0-9]*-[0-9]*.sql.enc")
    assert time.strftime("%Y%m%d") in kept.name, "only the set just written and read back is left"


@pytest.mark.parametrize("value", ["0", "abc", "-2"])
def test_an_invalid_keep_setting_refuses_the_backup_and_prunes_nothing(
    mini_repo: Path, value: str
) -> None:
    work = ready_repo(mini_repo)
    _seed_sets(work, range(1, 4))
    result = run_work(mini_repo, "backup", SIDEKICK_WORK_KEEP_BACKUPS=value)
    assert result.returncode == 1
    assert "SIDEKICK_WORK_KEEP_BACKUPS" in result.stderr
    assert len(list((work / "backups").glob("sidekick-*.sql.enc"))) == 3
    assert _no_database_work_done(mini_repo)
