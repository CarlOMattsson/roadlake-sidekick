"""The snapshot encryption holds its input in memory, so it has an explicit size ceiling."""

import importlib.util
import io
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from cryptography.fernet import Fernet

SCRIPT = Path(__file__).resolve().parents[3] / "deploy" / "selfhost" / "snapshot_crypto.py"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("snapshot_crypto_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(
    monkeypatch: pytest.MonkeyPatch, mode: str, data: bytes, *, ceiling: int | None = None
) -> tuple[int, bytes, str]:
    module = load()
    if ceiling is not None:
        monkeypatch.setattr(module, "MAX_PLAINTEXT_BYTES", ceiling)
        monkeypatch.setattr(module, "MAX_TOKEN_BYTES", ceiling * 2 + 1024)
    monkeypatch.setenv("SIDEKICK_BACKUP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    out, err = io.BytesIO(), io.StringIO()
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(data)))
    monkeypatch.setattr(sys, "stdout", SimpleNamespace(buffer=out))
    monkeypatch.setattr(sys, "stderr", err)
    return module.main(mode), out.getvalue(), err.getvalue()


def test_input_over_the_ceiling_is_refused_with_an_explicit_message_and_no_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code, out, err = run(monkeypatch, "encrypt", b"x" * 33, ceiling=32)
    assert code == 1
    assert out == b""
    assert "refused" in err and "MiB ceiling" in err
    assert "x" * 5 not in err


def test_input_at_the_ceiling_is_still_encrypted(monkeypatch: pytest.MonkeyPatch) -> None:
    code, out, _err = run(monkeypatch, "encrypt", b"x" * 32, ceiling=32)
    assert code == 0
    assert out.startswith(b"SIDEKICK-SNAPSHOT-1\n")


def test_decrypt_input_over_the_ceiling_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    code, out, err = run(monkeypatch, "decrypt", b"SIDEKICK-SNAPSHOT-1\n" + b"y" * 5000, ceiling=32)
    assert code == 1
    assert out == b""
    assert "MiB ceiling" in err


@pytest.mark.parametrize("size", [1, 15, 16, 17, 1000, 65537])
def test_the_decrypt_bound_always_fits_a_token_for_the_largest_plaintext(size: int) -> None:
    """MAX_TOKEN_BYTES is derived from the plaintext ceiling with the same overhead formula."""

    module = load()
    assert module.MAX_PLAINTEXT_BYTES == 512 * 1024 * 1024
    token = Fernet(Fernet.generate_key()).encrypt(b"x" * size)
    assert len(token) <= (size + 16 + 73) * 4 // 3 + 4


def test_the_key_can_come_from_the_file_a_docker_secret_provides(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    key = Fernet.generate_key()
    key_file = tmp_path / "backup_encryption_key"
    key_file.write_bytes(key + b"\n")
    module = load()
    monkeypatch.delenv("SIDEKICK_BACKUP_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("SIDEKICK_BACKUP_ENCRYPTION_KEY_FILE", str(key_file))
    out, err = io.BytesIO(), io.StringIO()
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(b"dump")))
    monkeypatch.setattr(sys, "stdout", SimpleNamespace(buffer=out))
    monkeypatch.setattr(sys, "stderr", err)

    assert module.main("encrypt") == 0
    assert Fernet(key).decrypt(out.getvalue()[len(module.MAGIC) :]) == b"dump"


def test_an_empty_key_file_variable_falls_back_to_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("SIDEKICK_BACKUP_ENCRYPTION_KEY_FILE", "")
    monkeypatch.setenv("SIDEKICK_BACKUP_ENCRYPTION_KEY", key)

    assert load().read_key() == key.encode()


def test_a_key_value_together_with_a_key_file_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    key = Fernet.generate_key().decode()
    key_file = tmp_path / "key"
    key_file.write_text(key)
    monkeypatch.setenv("SIDEKICK_BACKUP_ENCRYPTION_KEY", key)
    monkeypatch.setenv("SIDEKICK_BACKUP_ENCRYPTION_KEY_FILE", str(key_file))

    with pytest.raises(ValueError, match="both set"):
        load().read_key()


@pytest.mark.parametrize("content", [b"x" * 4097, b"\n"])
def test_a_key_file_that_is_too_large_or_empty_is_refused_not_truncated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, content: bytes
) -> None:
    key_file = tmp_path / "key"
    key_file.write_bytes(content)
    monkeypatch.delenv("SIDEKICK_BACKUP_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("SIDEKICK_BACKUP_ENCRYPTION_KEY_FILE", str(key_file))

    with pytest.raises(ValueError, match="key file"):
        load().read_key()
