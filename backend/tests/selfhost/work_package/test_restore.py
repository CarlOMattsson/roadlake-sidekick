"""`tools/work.sh restore`: plan, checks, replacement of both stores and the rollbacks."""

import re
import tarfile
from pathlib import Path

import pytest

from tests.selfhost.work_package.support import (
    CRYPTO_STUB,
    MIGRATE,
    READINESS_CALL,
    RESTART_HINDSIGHT,
    RESTART_WRITERS,
    RESTORE_STAMP,
    STOP_WRITERS,
    backup_set,
    changes_nothing,
    docker_calls,
    docker_calls_if_any,
    encrypt,
    make_clone,
    ready_repo,
    run_restore,
    run_work,
)

UNPACK = "run --rm -i --network none -v sidekick-work_hindsight_pg0:/dst"


UNPACK_ANY = "run --rm -i "


LOAD = "--single-transaction"


UNDO_DATABASE = "DROP DATABASE IF EXISTS sidekick"


RESTORED_OWNER = "7e57d0e5-aaaa-4bbb-8ccc-dddddddddddd"


RENAME = re.compile(r"ALTER DATABASE sidekick RENAME TO (sidekick_before_restore_\d{8}_\d{6})")


def test_restore_without_apply_checks_the_set_shows_the_plan_and_changes_nothing(
    mini_repo: Path,
) -> None:
    work = ready_repo(mini_repo)
    dump, archive = backup_set(work)
    result = run_work(mini_repo, "restore", RESTORE_STAMP)
    assert result.returncode == 0, result.stderr
    assert str(dump) in result.stdout and str(archive) in result.stdout
    assert "projektet sidekick-work" in result.stdout
    assert "Provkörning: inget ändrat" in result.stdout
    changes_nothing(docker_calls_if_any(mini_repo))
    assert sorted(p.name for p in (work / "backups").iterdir()) == sorted([dump.name, archive.name])


def test_restore_accepts_a_path_to_either_file_of_the_set(mini_repo: Path) -> None:
    work = ready_repo(mini_repo)
    dump, archive = backup_set(work)
    for path in (dump, archive):
        result = run_work(mini_repo, "restore", str(path), SIDEKICK_WORK_LANG="en")
        assert result.returncode == 0, result.stderr
        assert "Dry run: nothing changed" in result.stdout


def test_restore_without_a_set_lists_only_the_complete_sets(mini_repo: Path) -> None:
    work = ready_repo(mini_repo)
    backup_set(work)
    (work / "backups" / "sidekick-20260102-000000.sql.enc").write_text("x", encoding="utf-8")
    result = run_work(mini_repo, "restore")
    assert result.returncode == 2
    assert RESTORE_STAMP in result.stderr and "20260102-000000" not in result.stderr


def test_restore_refuses_a_name_that_is_no_backup(mini_repo: Path) -> None:
    ready_repo(mini_repo)
    result = run_work(mini_repo, "restore", "latest")
    assert result.returncode == 2
    assert "varken en tidsstämpel" in result.stderr
    changes_nothing(docker_calls_if_any(mini_repo))


@pytest.mark.parametrize("broken", ["no_memory", "no_database", "unfinished_dump", "empty_archive"])
def test_restore_refuses_a_missing_or_partial_backup_set(mini_repo: Path, broken: str) -> None:
    work = ready_repo(mini_repo)
    dump, archive = backup_set(work)
    expected = {
        "no_memory": "Säkerhetskopian är ofullständig",
        "no_database": "Säkerhetskopian är ofullständig",
        "unfinished_dump": "ingen komplett databasdump",
        "empty_archive": "inget läsbart minnesarkiv",
    }[broken]
    if broken == "no_memory":
        archive.unlink()
    elif broken == "no_database":
        dump.unlink()
    elif broken == "unfinished_dump":
        dump.write_bytes(encrypt(work, b"CREATE TABLE half (\n"))
    else:
        empty = work / "empty.tar.gz"
        with tarfile.open(empty, "w:gz"):
            pass
        archive.write_bytes(encrypt(work, empty.read_bytes()))
        empty.unlink()
    result = run_restore(mini_repo)
    assert result.returncode == 1
    assert expected in result.stderr and "Inget ändrat" in result.stderr
    changes_nothing(docker_calls_if_any(mini_repo))


def test_restore_refuses_a_target_without_a_memory_volume(mini_repo: Path) -> None:
    (mini_repo / "bin" / "docker").write_text(
        f'#!/bin/sh\n{CRYPTO_STUB}echo "$*" >> "$STUB_CALLS"\nexit 0\n', encoding="utf-8"
    )
    work = ready_repo(mini_repo)
    backup_set(work)
    result = run_restore(mini_repo)
    assert result.returncode == 1
    assert "minnesvolym finns inte" in result.stderr
    changes_nothing(docker_calls_if_any(mini_repo))


@pytest.mark.parametrize("answer", ["", "ja\n", "yes\n", "sidekick\n"])
def test_restore_apply_changes_nothing_without_the_project_name(
    mini_repo: Path, answer: str
) -> None:
    work = ready_repo(mini_repo)
    backup_set(work)
    result = run_work(mini_repo, "restore", RESTORE_STAMP, "--apply", stdin=answer)
    assert result.returncode == 1
    assert "projektet sidekick-work" in result.stderr, "the prompt names the target"
    changes_nothing(docker_calls_if_any(mini_repo))
    assert len(list((work / "backups").iterdir())) == 2


def test_restore_apply_backs_up_first_then_replaces_both_and_waits_for_readiness(
    mini_repo: Path,
) -> None:
    work = ready_repo(mini_repo)
    dump, archive = backup_set(work)
    result = run_restore(mini_repo)
    assert result.returncode == 0, result.stderr
    calls = docker_calls(mini_repo)
    rename = RENAME.search(calls)
    assert rename, "the previous database is renamed, not dropped"
    # One pause covers the safety backup and the restore; the writers start once, at the end.
    assert calls.count(STOP_WRITERS) == 1 and calls.count(RESTART_WRITERS) == 1
    assert calls.index(STOP_WRITERS) < calls.index("pg_dump") < rename.start()
    assert rename.start() < calls.index("CREATE DATABASE sidekick") < calls.index(LOAD)
    assert calls.index(LOAD) < calls.rindex("stop hindsight") < calls.index(UNPACK)
    assert calls.index(UNPACK) < calls.index(MIGRATE) < calls.rindex(RESTART_HINDSIGHT)
    assert calls.rindex(RESTART_HINDSIGHT) < calls.index(RESTART_WRITERS)
    assert calls.index(RESTART_WRITERS) < calls.index(READINESS_CALL)
    assert "DROP DATABASE" not in calls and calls.count(UNPACK_ANY) == 1
    # The way back is kept next to the restored set, which is untouched; nothing is pruned.
    backups = sorted(p.name for p in (work / "backups").iterdir())
    assert len(backups) == 4 and dump.name in backups and archive.name in backups
    assert not list((work / "backups").glob("*.part"))
    # Claude Desktop now acts as the restored owner.
    secrets = work / "secrets"
    assert (secrets / "user-id").read_text(encoding="utf-8").strip() == RESTORED_OWNER
    desktop = (secrets / "claude_desktop_config.json").read_text(encoding="utf-8")
    assert RESTORED_OWNER in desktop
    assert f"DROP DATABASE {rename.group(1)}" in result.stdout, "says how to free the space"


@pytest.mark.parametrize("failing", ["load", "unpack", "migrate", "term_unpack"])
def test_a_restore_that_fails_midway_puts_both_back_and_starts_the_writers(
    mini_repo: Path, failing: str
) -> None:
    work = ready_repo(mini_repo)
    backup_set(work)
    result = run_restore(mini_repo, STUB_FAIL=failing)
    assert result.returncode == (143 if failing == "term_unpack" else 1)
    assert "Det som fanns före är tillbaka" in result.stderr
    if failing != "term_unpack":
        assert "Återställningen misslyckades vid" in result.stderr
    calls = docker_calls(mini_repo)
    rename = RENAME.search(calls)
    assert rename
    failed_at = {"load": LOAD, "unpack": UNPACK, "migrate": MIGRATE, "term_unpack": UNPACK}[failing]
    # The previous database is renamed back after the failing step, then the writers start.
    assert calls.index(failed_at) < calls.index(UNDO_DATABASE)
    assert f"ALTER DATABASE {rename.group(1)} RENAME TO sidekick" in calls
    assert calls.index(UNDO_DATABASE) < calls.index(RESTART_WRITERS)
    assert calls.count(RESTART_WRITERS) == 1
    assert READINESS_CALL not in calls
    if failing == "load":
        assert UNPACK_ANY not in calls, "the memory is not touched when the database fails"
    else:
        # The memory is put back from the safety backup (a second unpacking) before anything starts.
        assert calls.count(UNPACK_ANY) == 2
        assert calls.rindex(UNPACK_ANY) < calls.rindex(RESTART_HINDSIGHT)
        assert calls.rindex(RESTART_HINDSIGHT) < calls.index(RESTART_WRITERS)
    assert not list((work / "backups").glob("*.part"))
    assert len(list((work / "backups").iterdir())) == 4, "the way back is kept"


def test_a_restore_that_cannot_put_the_memory_back_leaves_the_services_stopped(
    mini_repo: Path,
) -> None:
    work = ready_repo(mini_repo)
    backup_set(work)
    result = run_restore(mini_repo, STUB_FAIL="unpack_always", SIDEKICK_WORK_LANG="en")
    assert result.returncode == 1
    assert "Could not put everything back automatically" in result.stderr
    assert (
        "left stopped" in result.stderr
        and "docs/operate/work-laptop/backup-and-update.md" in result.stderr
    )
    calls = docker_calls(mini_repo)
    assert calls.count(UNPACK_ANY) == 2
    assert calls.index(UNDO_DATABASE) > calls.rindex(UNPACK_ANY), "the database is still put back"
    assert RESTART_WRITERS not in calls
    assert calls.count(RESTART_HINDSIGHT) == 1, "only the one after the safety backup"


def test_a_restore_that_is_not_ready_after_the_start_rolls_nothing_back(mini_repo: Path) -> None:
    work = ready_repo(mini_repo)
    backup_set(work)
    result = run_restore(
        mini_repo,
        STUB_FAIL="notready",
        SIDEKICK_WORK_READY_TIMEOUT="1",
        SIDEKICK_WORK_READY_POLL="1",
    )
    assert result.returncode == 1
    assert "Inget rullas tillbaka nu" in result.stderr
    assert "sidekick_before_restore_" in result.stderr
    calls = docker_calls(mini_repo)
    assert UNDO_DATABASE not in calls and calls.count(RESTART_WRITERS) == 1


def _databases(repo: Path) -> list[str]:
    return (repo / "docker-calls.txt.dbs").read_text(encoding="utf-8").split()


def test_a_restore_terminated_right_after_the_rename_still_puts_the_database_back(
    mini_repo: Path,
) -> None:
    """SIGTERM between the rename and the next line must not leave the stack without sidekick."""

    work = ready_repo(mini_repo)
    backup_set(work)
    result = run_restore(mini_repo, STUB_FAIL="term_rename")
    assert result.returncode == 143
    assert "Det som fanns före är tillbaka" in result.stderr
    calls = docker_calls(mini_repo)
    rename = RENAME.search(calls)
    assert rename
    assert calls.index(rename.group(0)) < calls.index(UNDO_DATABASE)
    assert f"ALTER DATABASE {rename.group(1)} RENAME TO sidekick" in calls
    assert calls.index(UNDO_DATABASE) < calls.index(RESTART_WRITERS)
    assert _databases(mini_repo) == ["sidekick"]


def test_a_restore_whose_rename_failed_finds_sidekick_in_place_and_drops_nothing(
    mini_repo: Path,
) -> None:
    """The rollback asks Postgres which names exist; without the rename there is nothing to undo."""

    work = ready_repo(mini_repo)
    backup_set(work)
    result = run_restore(mini_repo, STUB_FAIL="rename")
    assert result.returncode == 1
    assert "Återställningen misslyckades vid databasen" in result.stderr
    calls = docker_calls(mini_repo)
    assert "FROM pg_database" in calls
    assert "DROP DATABASE" not in calls and "RENAME TO sidekick\n" not in calls
    assert calls.count(RESTART_WRITERS) == 1


@pytest.mark.parametrize("command", ["restore", "backup", "update"])
@pytest.mark.parametrize("failing", ["ps", "still_running"])
def test_an_unknown_or_failed_pause_stops_before_anything_is_changed(
    mini_repo: Path,
    tmp_path_factory: pytest.TempPathFactory,
    command: str,
    failing: str,
) -> None:
    """compose ps failing, or a writer still running after the stop, fails closed."""

    if command == "update":
        make_clone(mini_repo, tmp_path_factory.mktemp("origin"))
    work = ready_repo(mini_repo)
    backup_set(work)
    if command == "restore":
        result = run_restore(mini_repo, STUB_FAIL=failing, SIDEKICK_WORK_LANG="en")
    else:
        result = run_work(mini_repo, command, STUB_FAIL=failing, SIDEKICK_WORK_LANG="en")
    assert result.returncode == 1
    expected = "Could not tell which" if failing == "ps" else "is still running after the stop"
    assert expected in result.stderr
    calls = docker_calls(mini_repo)
    # An update builds first (that touches no data); the build is what the others must not do.
    for destructive in ("pg_dump", "ALTER DATABASE", "stop hindsight", MIGRATE):
        assert destructive not in calls, destructive
    if command != "update":
        assert " build " not in calls
    if failing == "still_running":
        # The writers that were stopped are started again by the trap.
        assert calls.index(STOP_WRITERS) < calls.index(RESTART_WRITERS)
    else:
        assert STOP_WRITERS not in calls
    assert sorted(p.name for p in (work / "backups").iterdir()) == [
        f"hindsight-{RESTORE_STAMP}.tar.gz.enc",
        f"sidekick-{RESTORE_STAMP}.sql.enc",
    ]


@pytest.mark.parametrize("state", ["restarting always", "paused always", "created unless-stopped"])
def test_a_writer_that_is_restarting_paused_or_created_with_a_policy_is_stopped(
    mini_repo: Path, state: str
) -> None:
    """Not only "running" counts: Docker starts these again by itself during the copies."""

    ready_repo(mini_repo)
    result = run_work(mini_repo, "backup", STUB_WRITER=f"memory-worker:{state}:exited no")
    assert result.returncode == 0, result.stderr
    calls = docker_calls(mini_repo)
    assert calls.index(STOP_WRITERS) < calls.index("pg_dump")
    assert calls.count(RESTART_WRITERS) == 1


@pytest.mark.parametrize("command", ["restore", "backup", "update"])
@pytest.mark.parametrize("state", ["restarting always", "paused no", "created always"])
def test_a_writer_that_is_still_alive_after_the_stop_aborts_before_anything_changes(
    mini_repo: Path,
    tmp_path_factory: pytest.TempPathFactory,
    command: str,
    state: str,
) -> None:
    if command == "update":
        make_clone(mini_repo, tmp_path_factory.mktemp("origin"))
    work = ready_repo(mini_repo)
    backup_set(work)
    odd = {"STUB_WRITER": f"automation-worker:running always:{state}", "SIDEKICK_WORK_LANG": "en"}
    result = (
        run_restore(mini_repo, **odd)
        if command == "restore"
        else run_work(mini_repo, command, **odd)
    )
    assert result.returncode == 1
    assert "is still running after the stop" in result.stderr
    calls = docker_calls(mini_repo)
    for destructive in ("pg_dump", "ALTER DATABASE", "stop hindsight", MIGRATE):
        assert destructive not in calls, destructive
    if command != "update":  # an update builds first, which touches no data
        assert " build " not in calls
    assert calls.index(STOP_WRITERS) < calls.index(RESTART_WRITERS)


@pytest.mark.parametrize("state", ["exited always", "created no", "created", "dead no"])
def test_a_writer_that_cannot_start_by_itself_is_left_alone(mini_repo: Path, state: str) -> None:
    ready_repo(mini_repo)
    result = run_work(mini_repo, "backup", STUB_WRITER=f"memory-worker:{state}:{state}")
    assert result.returncode == 0, result.stderr
    calls = docker_calls(mini_repo)
    assert "stop api automation-worker\n" in calls
    assert "up -d --wait --wait-timeout 300 api automation-worker\n" in calls


def test_an_inspect_that_fails_stops_before_anything_is_changed(mini_repo: Path) -> None:
    ready_repo(mini_repo)
    result = run_work(mini_repo, "backup", STUB_FAIL="inspect", SIDEKICK_WORK_LANG="en")
    assert result.returncode == 1
    assert "Could not tell which" in result.stderr
    assert STOP_WRITERS not in docker_calls(mini_repo) and "pg_dump" not in docker_calls(mini_repo)
