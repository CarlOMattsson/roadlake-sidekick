"""The backup key file of tools/workctl: created once, never replaced while backups exist."""

import os
import stat
from pathlib import Path

import pytest
from tools.workctl import backupkey

VALID_KEY = "A" * 43 + "="


@pytest.fixture(name="dirs")
def _dirs(tmp_path: Path) -> tuple[Path, Path]:
    backups = tmp_path / "backups"
    backups.mkdir()
    return tmp_path / "secrets" / "backup.key", backups


def test_generate_creates_a_valid_key_with_mode_600(dirs: tuple[Path, Path]) -> None:
    key_file, backups = dirs
    assert backupkey.ensure_key(key_file, backups, generate=True) is True
    text = key_file.read_text(encoding="ascii")
    assert text.endswith("\n") and backupkey.KEY_FORMAT.fullmatch(text.strip())
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    assert [entry.name for entry in key_file.parent.iterdir()] == ["backup.key"]


def test_two_generated_keys_differ(tmp_path: Path) -> None:
    backups = tmp_path / "backups"
    backups.mkdir()
    for name in ("a.key", "b.key"):
        backupkey.ensure_key(tmp_path / name, backups, generate=True)
    assert (tmp_path / "a.key").read_text() != (tmp_path / "b.key").read_text()


def test_an_existing_valid_key_is_kept_and_its_mode_tightened(dirs: tuple[Path, Path]) -> None:
    key_file, backups = dirs
    key_file.parent.mkdir()
    key_file.write_text(f" {VALID_KEY} \n", encoding="ascii")
    key_file.chmod(0o644)
    assert backupkey.ensure_key(key_file, backups, generate=True) is False
    assert key_file.read_text(encoding="ascii") == f" {VALID_KEY} \n"
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600


def test_a_missing_key_is_not_generated_without_the_flag(dirs: tuple[Path, Path]) -> None:
    key_file, backups = dirs
    with pytest.raises(backupkey.KeyProblem) as problem:
        backupkey.ensure_key(key_file, backups, generate=False)
    assert problem.value.key == "bk_key_missing"
    assert not key_file.exists()


def test_a_missing_key_is_never_replaced_while_encrypted_backups_exist(
    dirs: tuple[Path, Path],
) -> None:
    key_file, backups = dirs
    (backups / "sidekick-1.sql.enc").write_bytes(b"x")
    with pytest.raises(backupkey.KeyProblem) as problem:
        backupkey.ensure_key(key_file, backups, generate=True)
    assert problem.value.key == "bk_key_missing"
    assert not key_file.exists()


@pytest.mark.parametrize("content", ["", "short", "A" * 44, "A" * 43 + "x", "A" * 42 + "!="])
def test_a_key_of_the_wrong_shape_is_refused(dirs: tuple[Path, Path], content: str) -> None:
    key_file, backups = dirs
    key_file.parent.mkdir()
    key_file.write_text(content, encoding="ascii")
    with pytest.raises(backupkey.KeyProblem) as problem:
        backupkey.ensure_key(key_file, backups, generate=True)
    assert problem.value.key == "bk_key_bad"


def test_a_key_file_inside_the_backup_directory_is_refused(dirs: tuple[Path, Path]) -> None:
    _, backups = dirs
    with pytest.raises(backupkey.KeyProblem) as problem:
        backupkey.ensure_key(backups / "backup.key", backups, generate=True)
    assert problem.value.key == "bk_key_inside"
    assert not (backups / "backup.key").exists()


def test_a_key_made_by_a_concurrent_run_is_never_replaced(
    dirs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    key_file, backups = dirs
    real_link = os.link

    def link_after_a_rival_won(src: str, dst: Path) -> None:
        # The other run publishes its key between the existence check and ours.
        dst.write_text(f"{VALID_KEY}\n", encoding="ascii")
        real_link(src, dst)

    key_file.parent.mkdir()
    monkeypatch.setattr(backupkey.os, "link", link_after_a_rival_won)
    assert backupkey.ensure_key(key_file, backups, generate=True) is False
    assert key_file.read_text(encoding="ascii") == f"{VALID_KEY}\n"
    assert [entry.name for entry in key_file.parent.iterdir()] == ["backup.key"]
