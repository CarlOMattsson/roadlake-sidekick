"""`tools/work.sh backup`: what a set holds, pausing the writers, pruning, flushing."""

import os
import stat
import time
from pathlib import Path

import pytest

from tests.selfhost.work_package.support import (
    CRYPTO_MAGIC,
    CRYPTO_STUB,
    MIGRATE,
    RESTART_HINDSIGHT,
    RESTART_WRITERS,
    STOP_WRITERS,
    STUB_IMAGE_ID,
    backup_key,
    docker_calls,
    make_clone,
    ready_repo,
    run_work,
)


@pytest.mark.parametrize("failing", ["database", "memory"])
def test_update_stops_before_changing_anything_when_either_backup_fails(
    mini_repo: Path, tmp_path_factory: pytest.TempPathFactory, failing: str
) -> None:
    """A failed dump of the database or of Hindsight's memory aborts before any migration."""

    make_clone(mini_repo, tmp_path_factory.mktemp("origin"))
    work = ready_repo(mini_repo)
    result = run_work(mini_repo, "update", STUB_FAIL=failing)
    assert result.returncode == 1
    assert "Säkerhetskopian misslyckades" in result.stderr
    assert not list((work / "backups").glob("*")), "no half backup is kept"
    calls = docker_calls(mini_repo)
    assert MIGRATE not in calls and "--force-recreate" not in calls
    # The build came first: the old image goes back under its name before the writers start again.
    assert calls.index(" build api") < calls.index(f"tag {STUB_IMAGE_ID} roadlake-sidekick:work")
    assert calls.index(f"tag {STUB_IMAGE_ID} roadlake-sidekick:work") < calls.rindex(
        RESTART_WRITERS
    )
    if failing == "memory":
        # Hindsight was stopped for the copy and is started again even though the copy failed.
        assert calls.index("stop hindsight") < calls.rindex(RESTART_HINDSIGHT)


def test_hindsight_is_started_again_when_the_backup_is_interrupted(mini_repo: Path) -> None:
    """Ctrl-C or kill during the archive must not leave the memory stopped or a half backup."""

    work = ready_repo(mini_repo)
    result = run_work(mini_repo, "backup", STUB_FAIL="interrupt")
    assert result.returncode == 143
    calls = docker_calls(mini_repo)
    assert calls.index("stop hindsight") < calls.index("--network none")
    assert calls.index("--network none") < calls.rindex(RESTART_HINDSIGHT)
    assert not list((work / "backups").glob("*")), "no half backup is kept"


def test_backup_keeps_the_database_dump_and_the_memory_archive_with_the_same_stamp(
    mini_repo: Path,
) -> None:
    work = ready_repo(mini_repo)
    result = run_work(mini_repo, "backup")
    assert result.returncode == 0, result.stderr
    backups = work / "backups"
    assert stat.S_IMODE(backups.stat().st_mode) == 0o700
    dump = next(backups.glob("sidekick-*.sql.enc"))
    memory = next(backups.glob("hindsight-*.tar.gz.enc"))
    assert dump.name.removeprefix("sidekick-").removesuffix(".sql.enc") == (
        memory.name.removeprefix("hindsight-").removesuffix(".tar.gz.enc")
    )
    assert dump.read_bytes().startswith(CRYPTO_MAGIC), "the dump is encrypted"
    assert b"PostgreSQL" not in dump.read_bytes()
    assert memory.read_bytes().startswith(CRYPTO_MAGIC), "the archive is encrypted"
    assert stat.S_IMODE(dump.stat().st_mode) == stat.S_IMODE(memory.stat().st_mode) == 0o600
    calls = docker_calls(mini_repo)
    # Hindsight is stopped for the copy, the archive is made offline from a read-only mount,
    # then it is started again.
    assert calls.index("stop hindsight") < calls.index("--network none")
    assert calls.index("--network none") < calls.rindex(RESTART_HINDSIGHT)
    assert "-v sidekick-work_hindsight_pg0:/src:ro" in calls
    assert not list(backups.glob("*.part"))


def test_backup_files_are_private_from_the_first_byte(mini_repo: Path) -> None:
    """The dump and the Hindsight archive are created 0600 before a byte is written."""

    ready_repo(mini_repo)
    result = run_work(mini_repo, "backup")
    assert result.returncode == 0, result.stderr
    modes = (mini_repo / "docker-calls.txt.modes").read_text(encoding="utf-8").split()
    assert len(modes) == 2, modes  # the encrypted dump and the encrypted archive
    assert set(modes) == {"600"}


def test_backup_pauses_the_writers_before_either_copy_and_starts_them_after_both(
    mini_repo: Path,
) -> None:
    """The dump and the Hindsight archive describe the same moment: nothing writes between."""

    ready_repo(mini_repo)
    result = run_work(mini_repo, "backup")
    assert result.returncode == 0, result.stderr
    calls = docker_calls(mini_repo)
    assert calls.count(STOP_WRITERS) == 1 and calls.count(RESTART_WRITERS) == 1
    assert calls.index(STOP_WRITERS) < calls.index("pg_dump")
    assert calls.index("pg_dump") < calls.index("stop hindsight")
    assert calls.index("--network none") < calls.rindex(RESTART_HINDSIGHT)
    assert calls.rindex(RESTART_HINDSIGHT) < calls.index(RESTART_WRITERS)


@pytest.mark.parametrize("failing", ["database", "memory", "interrupt"])
def test_the_writers_are_started_again_when_the_backup_fails(mini_repo: Path, failing: str) -> None:
    work = ready_repo(mini_repo)
    result = run_work(mini_repo, "backup", STUB_FAIL=failing)
    assert result.returncode != 0
    calls = docker_calls(mini_repo)
    assert calls.index(STOP_WRITERS) < calls.index("pg_dump")
    assert calls.count(RESTART_WRITERS) == 1
    assert calls.index("pg_dump") < calls.index(RESTART_WRITERS)
    if failing != "database":
        assert calls.rindex(RESTART_HINDSIGHT) < calls.index(RESTART_WRITERS)
    assert not list((work / "backups").glob("*")), "no half backup is kept"


def test_the_writers_come_up_even_when_the_script_is_terminated_during_their_restart(
    mini_repo: Path,
) -> None:
    ready_repo(mini_repo)
    result = run_work(mini_repo, "backup", STUB_FAIL="term_restart")
    assert result.returncode == 143
    # The first attempt was cut off by the signal; the trap made a second one that completed.
    assert docker_calls(mini_repo).count(RESTART_WRITERS) == 2


def test_nothing_is_stopped_or_started_when_no_writer_is_running(mini_repo: Path) -> None:
    (mini_repo / "bin" / "docker").write_text(
        """#!/bin/sh
"""
        + CRYPTO_STUB
        + """echo "$*" >> "$STUB_CALLS"
case "$*" in
  *pg_dump*) echo '-- PostgreSQL database dump complete' ;;
  *"ps -a -q"*) echo "cid-${*##* }" ;;
  *"inspect -f {{.State.Status}}"*) echo "exited always" ;;
  *"ps -q"*) echo cid ;;
esac
exit 0
""",
        encoding="utf-8",
    )
    ready_repo(mini_repo)
    result = run_work(mini_repo, "backup")
    assert result.returncode == 0, result.stderr
    calls = docker_calls(mini_repo)
    assert " stop api" not in calls and RESTART_WRITERS not in calls
    for svc in ("api", "memory-worker", "automation-worker"):
        assert f"ps -a -q {svc}" in calls


def test_backup_without_a_memory_volume_still_dumps_the_database(mini_repo: Path) -> None:
    dump_line = "echo '-- PostgreSQL database dump complete'"
    (mini_repo / "bin" / "docker").write_text(
        f'#!/bin/sh\n{CRYPTO_STUB}case "$*" in\n  *pg_dump*) {dump_line} ;;\nesac\nexit 0\n',
        encoding="utf-8",
    )
    work = ready_repo(mini_repo)
    result = run_work(mini_repo, "backup")
    assert result.returncode == 0, result.stderr
    assert list((work / "backups").glob("sidekick-*.sql.enc"))
    assert not list((work / "backups").glob("hindsight-*"))


def test_backups_are_pruned_to_the_last_seven_of_each_kind(mini_repo: Path) -> None:
    work = ready_repo(mini_repo)
    backups = work / "backups"
    backups.mkdir()
    backup_key(work)  # the old backups exist, so a missing key would be refused, not generated
    for day in range(1, 10):
        for name in (
            f"sidekick-2026010{day}-000000.sql.enc",
            f"hindsight-2026010{day}-000000.tar.gz.enc",
        ):
            path = backups / name
            path.write_text("x", encoding="utf-8")
            os.utime(path, (1_700_000_000 + day, 1_700_000_000 + day))
    assert run_work(mini_repo, "backup").returncode == 0
    assert len(list(backups.glob("sidekick-*.sql.enc"))) == 7
    assert len(list(backups.glob("hindsight-*.tar.gz.enc"))) == 7


def test_pruning_goes_by_the_time_in_the_name_and_never_removes_the_new_set(
    mini_repo: Path,
) -> None:
    """File times can be anything after a copy or a restore; the new, verified set must survive."""

    work = ready_repo(mini_repo)
    backups = work / "backups"
    backups.mkdir()
    backup_key(work)
    future = time.time() + 10 * 86400
    for day in range(1, 10):
        for name in (
            f"sidekick-2026010{day}-000000.sql.enc",
            f"hindsight-2026010{day}-000000.tar.gz.enc",
        ):
            path = backups / name
            path.write_text("x", encoding="utf-8")
            os.utime(path, (future + day, future + day))  # newer than anything the backup writes
    assert run_work(mini_repo, "backup").returncode == 0
    names = sorted(p.name for p in backups.glob("sidekick-*.sql.enc"))
    assert len(names) == 7
    assert not any(n.startswith("sidekick-2026010") and n < "sidekick-20260104" for n in names)
    today = time.strftime("%Y%m%d")
    assert any(today in n for n in names), "the new backup is the newest and is kept"
    assert len(list(backups.glob("hindsight-*.tar.gz.enc"))) <= 7


def test_a_backup_is_flushed_before_the_rename_and_the_directory_after_it(
    mini_repo: Path,
) -> None:
    work = ready_repo(mini_repo)
    sync_log = mini_repo / "sync.log"
    stub = mini_repo / "bin" / "sync"
    stub.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >>"$SYNC_LOG"\n', encoding="utf-8")
    stub.chmod(0o755)
    result = run_work(mini_repo, "backup", SYNC_LOG=str(sync_log))
    assert result.returncode == 0, result.stderr
    flushed = sync_log.read_text(encoding="utf-8").splitlines()
    backups = work / "backups"
    # Each backup's partial file is flushed before the directory.
    db = next(backups.glob("sidekick-*.sql.enc"))
    part = flushed.index(f"{db}.part")
    assert str(backups) in flushed[part + 1 :], "the directory is flushed after the rename"
    assert not list(backups.glob("*.part"))


def test_a_failed_verification_prunes_nothing_and_keeps_no_new_file(mini_repo: Path) -> None:
    work = ready_repo(mini_repo)
    backups = work / "backups"
    backups.mkdir()
    backup_key(work)
    for day in range(1, 10):
        (backups / f"sidekick-2026010{day}-000000.sql.enc").write_text("x", encoding="utf-8")
    result = run_work(mini_repo, "backup", STUB_FAIL="crypto_decrypt")
    assert result.returncode == 1
    assert len(list(backups.glob("sidekick-*.sql.enc"))) == 9, "nothing is pruned"
    assert not list(backups.glob("*.part"))
