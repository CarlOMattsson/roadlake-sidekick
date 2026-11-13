"""The secret files of tools/workctl: generation with mode 600 and no overwrite, and the single-line
edits of the model key. Each test has its own temporary directory; no value is a real secret."""

import os
import re
import stat
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from tools.workctl import secretfiles
from tools.workctl.secretfiles import SecretsExist

GATEWAY = "gateway.work.lan"
MARKER_TEXT = "KEEP=me\n"
FILE_NAMES = [secretfiles.DB_FILE, secretfiles.APP_FILE, secretfiles.HINDSIGHT_FILE]

# A minimal stand-in for deploy/selfhost/hindsight.env.example: the five lines the generator
# replaces, and one line it must leave alone.
HINDSIGHT_EXAMPLE = (
    "HINDSIGHT_API_LLM_PROVIDER=x\n"
    "HINDSIGHT_API_LLM_BASE_URL=x\n"
    "HINDSIGHT_API_LLM_MODEL=x\n"
    "HINDSIGHT_API_LLM_API_KEY=x\n"
    "HINDSIGHT_API_TENANT_API_KEY=x\n"
    "HINDSIGHT_API_RETAIN_MISSION=keep\n"
)

# Values that are random hex (64 characters) and random base64 of 48 bytes (also 64 characters).
HEX_KEYS = ("POSTGRES_PASSWORD", "SIDEKICK_DB_APP_PASSWORD", "SIDEKICK_DB_MIGRATOR_PASSWORD")
BASE64_KEYS = (
    "SIDEKICK_CURSOR_SIGNING_SECRET",
    "SIDEKICK_TOKEN_PEPPER",
    "SIDEKICK_MEMORY_HINDSIGHT_API_TOKEN",
    "SIDEKICK_MEMORY_ID_DERIVATION_KEY",
    "HINDSIGHT_API_TENANT_API_KEY",
)
RANDOM_KEYS = HEX_KEYS + BASE64_KEYS


def _write_example(root: Path) -> Path:
    example = root / "hindsight.env.example"
    example.write_text(HINDSIGHT_EXAMPLE, encoding="utf-8")
    return example


def _generate(root: Path) -> Path:
    """Generate the three files into root/secrets from the example; returns that directory."""
    secrets_dir = root / "secrets"
    secrets_dir.mkdir(parents=True)
    secretfiles.generate_secrets(secrets_dir, _write_example(root), GATEWAY)
    return secrets_dir


def _read_env(path: Path) -> dict[str, str]:
    """The KEY=value lines of an env file; comments and blank lines are skipped."""
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").split("\n"):
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def _read_all(secrets_dir: Path) -> dict[str, str]:
    """All three generated files merged; their key names do not overlap."""
    merged: dict[str, str] = {}
    for name in FILE_NAMES:
        merged.update(_read_env(secrets_dir / name))
    return merged


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def _env_file(path: Path, text: str) -> Path:
    """A env file with the given text and mode 600, as the real secret files have."""
    path.write_text(text, encoding="utf-8")
    os.chmod(path, 0o600)
    return path


@pytest.fixture(name="generated")
def _generated(tmp_path: Path) -> Path:
    return _generate(tmp_path)


@pytest.mark.parametrize("name", FILE_NAMES)
def test_generate_creates_each_file_with_mode_600(generated: Path, name: str) -> None:
    path = generated / name
    assert path.is_file()
    assert _mode(path) == 0o600


def test_db_file_holds_the_passwords_and_the_migrator_url(generated: Path) -> None:
    db = _read_env(generated / secretfiles.DB_FILE)
    assert set(db) == {
        "POSTGRES_PASSWORD",
        "SIDEKICK_DB_APP_PASSWORD",
        "SIDEKICK_DB_MIGRATOR_PASSWORD",
        "SIDEKICK_MIGRATION_DATABASE_URL",
    }


def test_app_file_holds_the_app_settings(generated: Path) -> None:
    app = _read_env(generated / secretfiles.APP_FILE)
    assert set(app) == {
        "SIDEKICK_DATABASE_URL",
        "SIDEKICK_CURSOR_SIGNING_SECRET",
        "SIDEKICK_TOKEN_PEPPER",
        "SIDEKICK_MEMORY_HINDSIGHT_API_TOKEN",
        "SIDEKICK_MEMORY_ID_DERIVATION_KEY",
    }


def test_app_database_url_carries_the_app_password(generated: Path) -> None:
    db = _read_env(generated / secretfiles.DB_FILE)
    app = _read_env(generated / secretfiles.APP_FILE)
    parts = urlsplit(app["SIDEKICK_DATABASE_URL"])
    assert parts.username == "sidekick_app"
    assert parts.password == db["SIDEKICK_DB_APP_PASSWORD"]
    assert parts.hostname == "postgres"
    assert parts.port == 5432
    assert parts.path == "/sidekick"


def test_migration_url_carries_the_migrator_password(generated: Path) -> None:
    db = _read_env(generated / secretfiles.DB_FILE)
    parts = urlsplit(db["SIDEKICK_MIGRATION_DATABASE_URL"])
    assert parts.username == "sidekick_migrator"
    assert parts.password == db["SIDEKICK_DB_MIGRATOR_PASSWORD"]
    assert parts.password != db["SIDEKICK_DB_APP_PASSWORD"]


def test_memory_token_in_app_file_equals_the_hindsight_tenant_key(generated: Path) -> None:
    app = _read_env(generated / secretfiles.APP_FILE)
    hindsight = _read_env(generated / secretfiles.HINDSIGHT_FILE)
    assert app["SIDEKICK_MEMORY_HINDSIGHT_API_TOKEN"] == hindsight["HINDSIGHT_API_TENANT_API_KEY"]


def test_hindsight_file_points_at_the_gateway_with_the_replaced_values(generated: Path) -> None:
    hindsight = _read_env(generated / secretfiles.HINDSIGHT_FILE)
    assert hindsight["HINDSIGHT_API_LLM_PROVIDER"] == "openai"
    assert hindsight["HINDSIGHT_API_LLM_BASE_URL"] == f"http://{GATEWAY}/v1"
    assert hindsight["HINDSIGHT_API_LLM_MODEL"] == "set-in-work-env"
    assert hindsight["HINDSIGHT_API_LLM_API_KEY"] == "not-needed"
    # A line the generator does not touch is kept as it was in the example.
    assert hindsight["HINDSIGHT_API_RETAIN_MISSION"] == "keep"


def test_no_generated_value_is_empty(generated: Path) -> None:
    values = _read_all(generated)
    assert values
    assert all(value for value in values.values())


@pytest.mark.parametrize("key", HEX_KEYS)
def test_hex_values_are_64_hex_characters(generated: Path, key: str) -> None:
    value = _read_all(generated)[key]
    assert re.fullmatch(r"[0-9a-f]{64}", value)


@pytest.mark.parametrize("key", BASE64_KEYS)
def test_base64_values_are_64_characters(generated: Path, key: str) -> None:
    value = _read_all(generated)[key]
    assert re.fullmatch(r"[A-Za-z0-9+/]{64}", value)


def test_two_runs_draw_different_values(tmp_path: Path) -> None:
    first = _read_all(_generate(tmp_path / "first"))
    second = _read_all(_generate(tmp_path / "second"))
    for key in RANDOM_KEYS:
        assert first[key] != second[key]


@pytest.mark.parametrize("name", FILE_NAMES)
@pytest.mark.parametrize("kind", ["regular", "symlink", "broken-symlink"])
def test_generate_refuses_when_a_file_is_already_there(
    tmp_path: Path, name: str, kind: str
) -> None:
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    example = _write_example(tmp_path)
    target = secrets_dir / name
    if kind == "regular":
        target.write_text(MARKER_TEXT, encoding="utf-8")
    elif kind == "symlink":
        (tmp_path / "elsewhere.env").write_text(MARKER_TEXT, encoding="utf-8")
        target.symlink_to(tmp_path / "elsewhere.env")
    else:
        target.symlink_to(tmp_path / "missing.env")

    with pytest.raises(SecretsExist):
        secretfiles.generate_secrets(secrets_dir, example, GATEWAY)

    # Nothing is written: no other file, no symlink target, the existing file is unchanged.
    assert sorted(path.name for path in secrets_dir.iterdir()) == [name]
    assert target.is_symlink() == (kind != "regular")
    assert not (tmp_path / "missing.env").exists()
    if kind == "regular":
        assert target.read_text(encoding="utf-8") == MARKER_TEXT
    if kind == "symlink":
        assert (tmp_path / "elsewhere.env").read_text(encoding="utf-8") == MARKER_TEXT


def test_set_line_replaces_an_existing_key_and_leaves_other_lines(tmp_path: Path) -> None:
    path = _env_file(tmp_path / "file.env", "A=1\nB=2\nB_EXTRA=keep\nC=3\n")
    secretfiles.set_line(path, "B", "9")
    # The old row is dropped and the new one appended: the key moves last, other rows keep order.
    assert path.read_text(encoding="utf-8") == "A=1\nB_EXTRA=keep\nC=3\nB=9\n"


@pytest.mark.parametrize("text", ["A=1\n", "A=1"])
def test_set_line_appends_a_missing_key(tmp_path: Path, text: str) -> None:
    path = _env_file(tmp_path / "file.env", text)
    secretfiles.set_line(path, "B", "2")
    assert path.read_text(encoding="utf-8") == "A=1\nB=2\n"


def test_set_line_keeps_mode_600_and_leaves_no_temp_files(tmp_path: Path) -> None:
    path = _env_file(tmp_path / "file.env", "A=1\n")
    secretfiles.set_line(path, "A", "2")
    assert _mode(path) == 0o600
    assert [entry.name for entry in tmp_path.iterdir()] == ["file.env"]


def test_drop_line_removes_only_that_key(tmp_path: Path) -> None:
    path = _env_file(tmp_path / "file.env", "A=1\nWORK_MODEL_API_KEY=k\nB=2\n")
    secretfiles.drop_line(path, "WORK_MODEL_API_KEY")
    assert path.read_text(encoding="utf-8") == "A=1\nB=2\n"
    assert _mode(path) == 0o600


def test_drop_line_is_fine_when_the_key_is_missing(tmp_path: Path) -> None:
    path = _env_file(tmp_path / "file.env", "A=1\n")
    secretfiles.drop_line(path, "WORK_MODEL_API_KEY")
    assert path.read_text(encoding="utf-8") == "A=1\n"


@pytest.fixture(name="model_files")
def _model_files(tmp_path: Path) -> Path:
    """sidekick.env and hindsight.env as generate_secrets leaves them, minus the random values."""
    _env_file(tmp_path / secretfiles.APP_FILE, "SIDEKICK_DATABASE_URL=x\n")
    _env_file(
        tmp_path / secretfiles.HINDSIGHT_FILE,
        "HINDSIGHT_API_LLM_API_KEY=not-needed\nHINDSIGHT_API_RETAIN_MISSION=keep\n",
    )
    return tmp_path


def test_apply_model_key_writes_the_key_to_both_files(model_files: Path) -> None:
    secretfiles.apply_model_key(model_files, "sk-test-123")
    app = _read_env(model_files / secretfiles.APP_FILE)
    hindsight = _read_env(model_files / secretfiles.HINDSIGHT_FILE)
    assert app[secretfiles.MODEL_KEY_NAME] == "sk-test-123"
    assert hindsight[secretfiles.HINDSIGHT_KEY_NAME] == "sk-test-123"
    assert app["SIDEKICK_DATABASE_URL"] == "x"
    assert hindsight["HINDSIGHT_API_RETAIN_MISSION"] == "keep"
    assert _mode(model_files / secretfiles.APP_FILE) == 0o600
    assert _mode(model_files / secretfiles.HINDSIGHT_FILE) == 0o600


def test_apply_model_key_replaces_an_earlier_key(model_files: Path) -> None:
    secretfiles.apply_model_key(model_files, "old-key")
    secretfiles.apply_model_key(model_files, "new-key")
    app_text = (model_files / secretfiles.APP_FILE).read_text(encoding="utf-8")
    assert app_text.count(f"{secretfiles.MODEL_KEY_NAME}=") == 1
    assert secretfiles.stored_model_key(model_files) == "new-key"


def test_apply_empty_key_removes_the_key_and_sets_not_needed(model_files: Path) -> None:
    secretfiles.apply_model_key(model_files, "sk-test-123")
    secretfiles.apply_model_key(model_files, "")
    app_text = (model_files / secretfiles.APP_FILE).read_text(encoding="utf-8")
    assert secretfiles.MODEL_KEY_NAME not in app_text
    hindsight = _read_env(model_files / secretfiles.HINDSIGHT_FILE)
    assert hindsight[secretfiles.HINDSIGHT_KEY_NAME] == "not-needed"
    assert secretfiles.stored_model_key(model_files) == ""


def test_stored_model_key_is_empty_when_the_file_is_missing(tmp_path: Path) -> None:
    assert secretfiles.stored_model_key(tmp_path) == ""


def test_stored_model_key_is_empty_when_the_line_is_missing(tmp_path: Path) -> None:
    _env_file(tmp_path / secretfiles.APP_FILE, "SIDEKICK_DATABASE_URL=x\n")
    assert secretfiles.stored_model_key(tmp_path) == ""


def test_stored_model_key_returns_the_value_after_the_first_equals_sign(tmp_path: Path) -> None:
    _env_file(tmp_path / secretfiles.APP_FILE, f"{secretfiles.MODEL_KEY_NAME}=a=b\n")
    assert secretfiles.stored_model_key(tmp_path) == "a=b"


def test_stored_model_key_returns_the_last_line(tmp_path: Path) -> None:
    _env_file(
        tmp_path / secretfiles.APP_FILE,
        f"{secretfiles.MODEL_KEY_NAME}=first\nA=1\n{secretfiles.MODEL_KEY_NAME}=second\n",
    )
    assert secretfiles.stored_model_key(tmp_path) == "second"


def test_a_missing_hindsight_example_leaves_no_files_behind(tmp_path: Path) -> None:
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    with pytest.raises(FileNotFoundError):
        secretfiles.generate_secrets(
            secrets_dir, tmp_path / "absent.env.example", "model.work.internal"
        )
    assert list(secrets_dir.iterdir()) == []


def test_a_failure_while_creating_removes_the_files_already_made(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    real_create = secretfiles._create
    calls: list[Path] = []

    def failing_create(path: Path, text: str) -> None:
        calls.append(path)
        if len(calls) == 3:
            raise OSError("disk full")
        real_create(path, text)

    monkeypatch.setattr(secretfiles, "_create", failing_create)
    with pytest.raises(OSError, match="disk full"):
        secretfiles.generate_secrets(secrets_dir, _write_example(tmp_path), "model.work.internal")
    assert list(secrets_dir.iterdir()) == []


def test_set_line_and_drop_line_treat_a_missing_file_as_empty(tmp_path: Path) -> None:
    # The shell version carried on without the file: set_line created it, drop_line left it empty.
    added = tmp_path / "added.env"
    secretfiles.set_line(added, "KEY", "value")
    assert added.read_text(encoding="utf-8") == "KEY=value\n"
    assert _mode(added) == 0o600
    dropped = tmp_path / "dropped.env"
    secretfiles.drop_line(dropped, "KEY")
    assert dropped.read_text(encoding="utf-8") == ""


def test_write_rooms_env_writes_one_line_with_mode_600(tmp_path: Path) -> None:
    secretfiles.write_rooms_env(tmp_path, "work,journal")
    target = tmp_path / "rooms.env"
    assert target.read_text(encoding="utf-8") == "SIDEKICK_ENABLED_ROOMS=work,journal\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_write_rooms_env_with_no_rooms_removes_the_file(tmp_path: Path) -> None:
    (tmp_path / "rooms.env").write_text("SIDEKICK_ENABLED_ROOMS=work\n", encoding="utf-8")
    secretfiles.write_rooms_env(tmp_path, "")
    secretfiles.write_rooms_env(tmp_path, "")
    assert not (tmp_path / "rooms.env").exists()


def test_write_private_replaces_a_file_atomically_with_mode_600(tmp_path: Path) -> None:
    target = tmp_path / "x.env"
    target.write_text("old", encoding="utf-8")
    target.chmod(0o644)
    secretfiles.write_private(target, "new\n")
    assert target.read_text(encoding="utf-8") == "new\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert [entry.name for entry in tmp_path.iterdir()] == ["x.env"]


def test_write_private_flushes_the_file_and_then_the_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    flushed: list[int] = []
    real_fsync = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (flushed.append(fd), real_fsync(fd))[1])
    secretfiles.write_private(tmp_path / "x.env", "v\n")
    assert len(flushed) == 2
