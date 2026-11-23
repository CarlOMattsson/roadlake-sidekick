"""`restore.sh` hands the photo files to the one-off container: a staged, read-only copy.

A stub `docker` records its arguments and what it could see of the mounted folder, so nothing
here starts a container.
"""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "deploy" / "selfhost" / "restore.sh"
OWNER = "00000000-0000-7000-8000-0000000000aa"
CHECKSUM = "a" * 64

# The plan the script reads its checksum from, printed in the shape `sidekick-backup import` uses.
STUB = f"""#!/bin/bash
printf '%s\\n' "$*" >> "$STUB_LOG"
mount=""
for argument in "$@"; do
  case "$argument" in *:/restore-media:ro) mount="${{argument%%:/restore-media:ro}}" ;; esac
done
if [ -n "$mount" ]; then
  printf 'staged=%s\\n' "$(find "$mount" -type f | wc -l)" >> "$STUB_LOG"
  printf 'mode=%s\\n' "$(stat -c %a "$mount")" >> "$STUB_LOG"
  printf 'dir=%s\\n' "$mount" >> "$STUB_LOG"
fi
cat > /dev/null
echo '{{"plan_checksum": "{CHECKSUM}"}}'
"""


@pytest.fixture(name="install")
def _install(tmp_path: Path) -> Path:
    folder = tmp_path / "selfhost"
    folder.mkdir()
    shutil.copy(SCRIPT, folder / "restore.sh")
    (folder / "compose.yaml").write_text("name: sidekick\n", encoding="utf-8")
    (folder / "selfhost.env").write_text("", encoding="utf-8")
    bin_folder = tmp_path / "bin"
    bin_folder.mkdir()
    docker = bin_folder / "docker"
    docker.write_text(STUB, encoding="utf-8")
    docker.chmod(docker.stat().st_mode | stat.S_IXUSR)
    return folder


def run(
    install: Path, tmp_path: Path, *arguments: str | Path
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    log = tmp_path / "docker.log"
    env = {
        "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}",
        "STUB_LOG": str(log),
        "HOME": str(tmp_path),
    }
    result = subprocess.run(  # noqa: S603 - the script under test, with a stub docker
        ["/bin/bash", str(install / "restore.sh"), "--target-owner", OWNER, *map(str, arguments)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def backups_with_media(tmp_path: Path) -> Path:
    backups = tmp_path / "backups"
    (backups / "media" / "ab").mkdir(parents=True)
    (backups / "media" / "ab" / "file").write_bytes(b"token")
    (backups / "media" / "ab" / "file").chmod(0o600)  # only the user may read it
    (backups / "sidekick-backup-20261122T120000Z-0123456789ab.skbackup").write_text("{}")
    return backups


def test_the_media_folder_beside_the_backup_is_staged_readable_and_mounted_read_only(
    install: Path, tmp_path: Path
) -> None:
    backups = backups_with_media(tmp_path)

    result, log = run(install, tmp_path, "--backup", next(backups.glob("*.skbackup")))

    assert result.returncode == 0, result.stderr
    calls = [line for line in log if line.startswith("compose")]
    assert len(calls) == 1  # the dry run
    assert "--media-directory /restore-media" in calls[0]
    assert ":/restore-media:ro" in calls[0]
    assert "staged=1" in log
    mode = int(next(line for line in log if line.startswith("mode=")).removeprefix("mode="), 8)
    assert mode & 0o055 == 0o055  # the container user can read the copy; the originals stay 0600
    staged = next(line for line in log if line.startswith("dir=")).removeprefix("dir=")
    assert not Path(staged).exists()  # removed when the script ends
    assert oct((backups / "media" / "ab" / "file").stat().st_mode & 0o777) == "0o600"


def test_apply_runs_the_same_import_with_the_checksum_and_the_media_folder(
    install: Path, tmp_path: Path
) -> None:
    backups = backups_with_media(tmp_path)

    result, log = run(install, tmp_path, "--backup", next(backups.glob("*.skbackup")), "--apply")

    assert result.returncode == 0, result.stderr
    calls = [line for line in log if line.startswith("compose")]
    assert len(calls) == 2
    assert f"--apply --plan-checksum {CHECKSUM}" in calls[1]
    assert all("--media-directory /restore-media" in call for call in calls)


def test_a_media_dir_can_be_named_and_an_export_folder_brings_its_own(
    install: Path, tmp_path: Path
) -> None:
    export = tmp_path / "export"
    (export / "media").mkdir(parents=True)
    (export / "media" / "one.jpg").write_bytes(b"x")
    (export / "export.json").write_text("{}")
    other = tmp_path / "elsewhere"
    other.mkdir()
    (other / "two.jpg").write_bytes(b"y")
    (other / "three.jpg").write_bytes(b"z")

    own, own_log = run(install, tmp_path, "--backup", export)
    named, named_log = run(install, tmp_path, "--backup", export, "--media-dir", other)

    assert own.returncode == 0 and named.returncode == 0, own.stderr + named.stderr
    assert "staged=1" in own_log
    assert "staged=2" in named_log


def test_without_a_media_folder_nothing_is_mounted(install: Path, tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    backup = plain / "owner-export.json"
    backup.write_text("{}")

    result, log = run(install, tmp_path, "--backup", backup)

    assert result.returncode == 0, result.stderr
    assert "restore-media" not in "\n".join(log)


def test_a_media_dir_that_is_not_a_folder_is_refused(install: Path, tmp_path: Path) -> None:
    backup = tmp_path / "owner-export.json"
    backup.write_text("{}")

    result, log = run(install, tmp_path, "--backup", backup, "--media-dir", tmp_path / "nope")

    assert result.returncode == 1
    assert "media folder not found" in result.stderr
    assert log == []
