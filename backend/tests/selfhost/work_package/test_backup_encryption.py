"""Backups are encrypted with a key of their own and read back before they count."""

import os
import stat
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from tests.selfhost.work_package.support import (
    CRYPTO_MAGIC,
    RESTART_HINDSIGHT,
    RESTART_WRITERS,
    RESTORE_STAMP,
    SELFHOST,
    STOP_WRITERS,
    backup_key,
    backup_set,
    changes_nothing,
    docker_calls,
    docker_calls_if_any,
    ready_repo,
    run_restore,
    run_work,
)
from tests.support.polling import wait_until


def _tree_bytes(root: Path) -> bytes:
    return b"".join(p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file())


def test_the_first_backup_creates_a_private_key_outside_the_backup_directory(
    mini_repo: Path,
) -> None:
    work = ready_repo(mini_repo)
    key_file = work / "secrets" / "backup.key"
    assert not key_file.exists()
    result = run_work(mini_repo, "backup", SIDEKICK_WORK_LANG="en")
    assert result.returncode == 0, result.stderr
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    key = key_file.read_text(encoding="utf-8").strip()
    Fernet(key.encode())  # a valid Fernet key
    assert str(key_file) in result.stdout, "the path is printed"
    assert key_file.parent != work / "backups" and not list((work / "backups").glob("*.key"))
    # The key itself is never printed, logged or put on a command line.
    for text in (result.stdout, result.stderr, (work / "work.log").read_text(encoding="utf-8")):
        assert key not in text
    assert key not in docker_calls(mini_repo)
    assert key not in (mini_repo / "docker-calls.txt.crypto").read_text(encoding="utf-8")
    # A second backup keeps the same key.
    assert run_work(mini_repo, "backup").returncode == 0
    assert key_file.read_text(encoding="utf-8").strip() == key


def test_no_plain_dump_or_archive_is_left_on_disk_after_a_backup(mini_repo: Path) -> None:
    work = ready_repo(mini_repo)
    assert run_work(mini_repo, "backup").returncode == 0
    everything = _tree_bytes(work)
    assert b"PostgreSQL database dump complete" not in everything
    names = sorted(p.name for p in (work / "backups").iterdir())
    assert all(n.endswith(".enc") for n in names) and len(names) == 2, names


def test_a_backup_is_decrypted_and_checked_again_before_it_counts(mini_repo: Path) -> None:
    work = ready_repo(mini_repo)
    result = run_work(mini_repo, "backup")
    assert result.returncode == 0, result.stderr
    modes = (mini_repo / "docker-calls.txt.crypto").read_text(encoding="utf-8").split()
    assert modes == ["encrypt", "decrypt", "encrypt", "decrypt"], modes
    assert "avkrypterad och kontrollerad" in result.stdout
    # Reading both files back with the key gives what was backed up.
    key = Fernet(backup_key(work))
    dump = next((work / "backups").glob("*.sql.enc")).read_bytes()
    assert b"PostgreSQL database dump complete" in key.decrypt(dump[len(CRYPTO_MAGIC) :])


@pytest.mark.parametrize("failing", ["incomplete_dump", "crypto_decrypt", "crypto_encrypt"])
def test_a_backup_that_cannot_be_read_back_is_not_kept_and_the_writers_start_again(
    mini_repo: Path, failing: str
) -> None:
    work = ready_repo(mini_repo)
    result = run_work(mini_repo, "backup", STUB_FAIL=failing)
    assert result.returncode == 1
    assert "Säkerhetskopian misslyckades" in result.stderr
    assert not list((work / "backups").glob("*")), "nothing is kept"
    calls = docker_calls(mini_repo)
    assert calls.count(STOP_WRITERS) == 1 and calls.count(RESTART_WRITERS) == 1
    if failing != "crypto_encrypt":
        assert "gick inte att läsa tillbaka" in result.stderr


def test_a_memory_archive_that_cannot_be_read_back_is_removed_and_hindsight_starts(
    mini_repo: Path,
) -> None:
    """Only the second decryption (the archive) fails: the dump is thrown away with it."""

    work = ready_repo(mini_repo)
    docker = mini_repo / "bin" / "docker"
    stub = docker.read_text(encoding="utf-8")
    counted = stub.replace(
        '[ "${STUB_FAIL:-}" = "crypto_$mode" ] && exit 1',
        '[ "$mode" = decrypt ] && [ "$(grep -c decrypt "${STUB_CALLS}.crypto")" = 2 ] && exit 1',
    )
    docker.write_text(counted, encoding="utf-8")
    result = run_work(mini_repo, "backup")
    assert result.returncode == 1
    assert not list((work / "backups").glob("*")), "no half backup is kept"
    calls = docker_calls(mini_repo)
    assert calls.rindex(RESTART_HINDSIGHT) < calls.index(RESTART_WRITERS)


def test_backup_fails_closed_when_the_key_is_missing_and_encrypted_backups_exist(
    mini_repo: Path,
) -> None:
    work = ready_repo(mini_repo)
    assert run_work(mini_repo, "backup").returncode == 0
    (work / "secrets" / "backup.key").unlink()
    before = sorted(p.name for p in (work / "backups").iterdir())
    (mini_repo / "docker-calls.txt").unlink()
    result = run_work(mini_repo, "backup", SIDEKICK_WORK_LANG="en")
    assert result.returncode == 1
    assert "key for the backups is missing" in result.stderr and "Nothing changed" in result.stderr
    assert not (work / "secrets" / "backup.key").exists(), (
        "no new key that would orphan the old backups"
    )
    assert sorted(p.name for p in (work / "backups").iterdir()) == before
    changes_nothing(docker_calls_if_any(mini_repo))


@pytest.mark.parametrize("content", ["", "not a key\n", "short\n"])
def test_backup_refuses_a_key_file_that_holds_no_valid_key(mini_repo: Path, content: str) -> None:
    work = ready_repo(mini_repo)
    (work / "secrets" / "backup.key").write_text(content, encoding="utf-8")
    result = run_work(mini_repo, "backup", SIDEKICK_WORK_LANG="en")
    assert result.returncode == 1
    assert "does not hold a valid key" in result.stderr
    assert not (work / "backups").exists() or not list((work / "backups").glob("*"))
    changes_nothing(docker_calls_if_any(mini_repo))


def test_the_key_may_not_live_in_the_backup_directory(mini_repo: Path) -> None:
    work = ready_repo(mini_repo)
    result = run_work(
        mini_repo,
        "backup",
        SIDEKICK_WORK_BACKUP_KEY_FILE=str(work / "backups" / "backup.key"),
        SIDEKICK_WORK_LANG="en",
    )
    assert result.returncode == 1
    assert "inside the backup directory" in result.stderr
    changes_nothing(docker_calls_if_any(mini_repo))


def test_the_key_file_can_be_kept_elsewhere(
    mini_repo: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    work = ready_repo(mini_repo)
    store = tmp_path_factory.mktemp("keystore") / "work-backup.key"
    result = run_work(mini_repo, "backup", SIDEKICK_WORK_BACKUP_KEY_FILE=str(store))
    assert result.returncode == 0, result.stderr
    assert store.exists() and stat.S_IMODE(store.stat().st_mode) == 0o600
    assert not (work / "secrets" / "backup.key").exists()


def test_restore_round_trip_writes_back_exactly_what_the_backup_captured(mini_repo: Path) -> None:
    """backup, then restore --apply: the stand-in psql and tar get the decrypted data."""

    work = ready_repo(mini_repo)
    assert run_work(mini_repo, "backup").returncode == 0
    stamp = next((work / "backups").glob("sidekick-*.sql.enc")).name[len("sidekick-") :][:-8]
    # The way back that restore takes gets a stamp of its own: wait until the clock has left the
    # second (the stamp has one-second resolution) the backup was named after.
    wait_until(
        lambda: time.strftime("%Y%m%d-%H%M%S") != stamp,
        timeout=5,
        what="the clock to pass the backup's stamp",
    )
    result = run_work(mini_repo, "restore", stamp, "--apply", stdin="sidekick-work\n")
    assert result.returncode == 0, result.stderr
    loaded = (mini_repo / "docker-calls.txt.loaded").read_bytes()
    assert loaded == b"-- PostgreSQL database dump complete\n"
    # The only unpacking is the restored set (a second would be a rollback).
    unpacked = sorted(mini_repo.glob("docker-calls.txt.unpacked.*"))
    assert len(unpacked) == 1
    with tarfile.open(unpacked[0], "r:gz") as tar:
        assert [m.name for m in tar.getmembers()] == ["docker-calls.txt.member"]
        member = tar.extractfile("docker-calls.txt.member")
        assert member is not None and member.read() == b"16"
    # The restore also kept a fresh encrypted way back; no plain file appeared anywhere.
    assert len(list((work / "backups").glob("*.enc"))) == 4
    assert b"PostgreSQL database dump complete" not in _tree_bytes(work)


def test_restore_fails_closed_without_the_key_and_changes_nothing(mini_repo: Path) -> None:
    work = ready_repo(mini_repo)
    backup_set(work)
    (work / "secrets" / "backup.key").unlink()
    for extra in ((), ("--apply",)):
        result = run_work(
            mini_repo,
            "restore",
            RESTORE_STAMP,
            *extra,
            stdin="sidekick-work\n",
            SIDEKICK_WORK_LANG="en",
        )
        assert result.returncode == 1
        assert "key for the backups is missing" in result.stderr
    assert not (work / "secrets" / "backup.key").exists()
    changes_nothing(docker_calls_if_any(mini_repo))


def test_restore_refuses_a_wrong_key_and_a_changed_file_and_changes_nothing(
    mini_repo: Path,
) -> None:
    work = ready_repo(mini_repo)
    dump, archive = backup_set(work)
    key_file = work / "secrets" / "backup.key"
    right = key_file.read_bytes()
    key_file.write_bytes(Fernet.generate_key() + b"\n")
    result = run_restore(mini_repo)
    assert result.returncode == 1
    assert "ingen komplett databasdump" in result.stderr and "Inget ändrat" in result.stderr
    key_file.write_bytes(right)
    raw = bytearray(archive.read_bytes())
    raw[-5] ^= 0x01  # one flipped bit: the authenticated token no longer opens
    archive.write_bytes(bytes(raw))
    result = run_restore(mini_repo)
    assert result.returncode == 1
    assert "inget läsbart minnesarkiv" in result.stderr
    changes_nothing(docker_calls_if_any(mini_repo))
    assert dump.exists()


def test_restore_refuses_the_plain_files_of_an_older_version(mini_repo: Path) -> None:
    work = ready_repo(mini_repo)
    (work / "backups").mkdir()
    old = work / "backups" / "sidekick-20260101-000000.sql"
    old.write_text("-- PostgreSQL database dump complete\n", encoding="utf-8")
    result = run_work(mini_repo, "restore", str(old))
    assert result.returncode == 2
    assert "varken en tidsstämpel" in result.stderr
    changes_nothing(docker_calls_if_any(mini_repo))


def test_the_crypto_helper_round_trips_and_never_prints_data_or_key_on_failure() -> None:
    env = {**os.environ, "SIDEKICK_BACKUP_ENCRYPTION_KEY": Fernet.generate_key().decode()}
    helper = str(SELFHOST / "snapshot_crypto.py")

    def run(mode: str, data: bytes, env: dict[str, str]) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [sys.executable, "-I", helper, mode], input=data, capture_output=True, env=env
        )

    token = run("encrypt", b"secret rows", env)
    assert token.returncode == 0 and token.stdout.startswith(CRYPTO_MAGIC)
    assert b"secret rows" not in token.stdout
    assert run("decrypt", token.stdout, env).stdout == b"secret rows"
    other = {**env, "SIDEKICK_BACKUP_ENCRYPTION_KEY": Fernet.generate_key().decode()}
    wrong = run("decrypt", token.stdout, other)
    assert wrong.returncode == 1 and wrong.stdout == b""
    assert b"secret rows" not in wrong.stderr
    assert env["SIDEKICK_BACKUP_ENCRYPTION_KEY"].encode() not in wrong.stderr
    assert run("encrypt", b"", env).returncode == 1
    assert run("decrypt", b"plain text", env).returncode == 1
