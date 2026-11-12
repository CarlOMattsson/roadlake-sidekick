"""secrets-to-files.sh moves secrets out of selfhost.env without printing them."""

import shutil
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "deploy" / "selfhost" / "secrets-to-files.sh"
PEPPER = "AbCd+/Ef==abcdefghijklmnopqrstuvwxyz0123456789"
ENV = f"SELFHOST_DOMAIN=x.example\nSIDEKICK_TOKEN_PEPPER={PEPPER}\nSIDEKICK_PUSH_AUTH_TOKEN=\n"


@pytest.fixture(name="deploy")
def _deploy(tmp_path: Path) -> Path:
    """A copy of the script in its own directory, so the default layout is exercised for real."""

    directory = tmp_path / "selfhost"
    directory.mkdir()
    shutil.copy(SCRIPT, directory / "secrets-to-files.sh")
    (directory / "selfhost.env").write_text(ENV)
    (directory / "selfhost.env").chmod(0o600)
    return directory


def _run(directory: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(directory / "secrets-to-files.sh"), *args],
        cwd=directory,
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_default_layout_moves_the_value_and_never_prints_it(deploy: Path) -> None:
    result = _run(deploy)

    assert result.returncode == 0, result.stderr
    assert PEPPER not in result.stdout + result.stderr
    secret = deploy / "secrets" / "token_pepper"
    assert secret.read_text() == PEPPER + "\n"
    assert stat.S_IMODE(secret.stat().st_mode) == 0o644
    assert stat.S_IMODE(secret.parent.stat().st_mode) == 0o700
    env = (deploy / "selfhost.env").read_text()
    assert "SIDEKICK_TOKEN_PEPPER=" not in env
    assert "\nSELFHOST_TOKEN_PEPPER_FILE=./secrets/token_pepper\n" in env
    assert stat.S_IMODE((deploy / "selfhost.env").stat().st_mode) == 0o600
    assert sorted(path.name for path in deploy.rglob("*.tmp.*")) == []


def test_another_directory_below_the_script_is_named_as_it_is(deploy: Path) -> None:
    result = _run(deploy, "--secrets-dir", "keys")

    assert result.returncode == 0, result.stderr
    assert (deploy / "keys" / "token_pepper").is_file()
    assert (
        "\nSELFHOST_TOKEN_PEPPER_FILE=./keys/token_pepper\n"
        in (deploy / "selfhost.env").read_text()
    )


def test_a_directory_outside_the_script_directory_is_named_by_its_absolute_path(
    deploy: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "elsewhere"

    result = _run(deploy, "--secrets-dir", str(outside))

    assert result.returncode == 0, result.stderr
    assert (outside / "token_pepper").is_file()
    env = (deploy / "selfhost.env").read_text()
    assert f"\nSELFHOST_TOKEN_PEPPER_FILE={outside}/token_pepper\n" in env


def test_an_empty_file_line_does_not_count_as_already_moved(deploy: Path) -> None:
    (deploy / "selfhost.env").write_text(ENV + "SELFHOST_TOKEN_PEPPER_FILE=\n")

    result = _run(deploy)

    assert result.returncode == 0, result.stderr
    assert "already a file" not in result.stdout
    assert (deploy / "secrets" / "token_pepper").is_file()


def test_a_second_run_changes_nothing(deploy: Path) -> None:
    _run(deploy)
    before = (deploy / "selfhost.env").read_text()

    result = _run(deploy)

    assert result.returncode == 0, result.stderr
    assert "already a file" in result.stdout
    assert (deploy / "selfhost.env").read_text() == before


def test_a_symbolic_link_is_refused_and_left_alone(deploy: Path) -> None:
    real = deploy / "real.env"
    (deploy / "selfhost.env").rename(real)
    (deploy / "selfhost.env").symlink_to(real)

    result = _run(deploy)

    assert result.returncode == 1
    assert "symbolic link" in result.stderr
    assert (deploy / "selfhost.env").is_symlink()
    assert real.read_text() == ENV
    assert not (deploy / "secrets").exists()


def test_a_dry_run_writes_nothing(deploy: Path) -> None:
    result = _run(deploy, "--dry-run")

    assert result.returncode == 0, result.stderr
    assert (deploy / "selfhost.env").read_text() == ENV
    assert not (deploy / "secrets").exists()
