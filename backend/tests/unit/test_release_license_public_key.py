"""tools/check-license-public-key.py: a release image needs the licensor's real public key."""

import base64
import importlib.util
import secrets
from pathlib import Path
from types import ModuleType

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

TOOL = Path(__file__).resolve().parents[3] / "tools" / "check-license-public-key.py"


def load_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_license_public_key", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def module_with(tmp_path: Path, value: str) -> Path:
    path = tmp_path / "public_key.py"
    path.write_text(
        'from typing import Final\n\nPLACEHOLDER_PUBLIC_KEY: Final = "UNSET-OWNER-PUBLIC-KEY"\n\n'
        f"DEFAULT_LICENSE_PUBLIC_KEY: Final = {value}\n",
        encoding="utf-8",
    )
    return path


def test_the_check_matches_the_repository_module() -> None:
    # Ordinary CI and development run with the placeholder, which fails only this release check;
    # once the licensor has set the real key the same check passes.
    from sidekick.license.public_key import DEFAULT_LICENSE_PUBLIC_KEY, PLACEHOLDER_PUBLIC_KEY

    placeholder = DEFAULT_LICENSE_PUBLIC_KEY == PLACEHOLDER_PUBLIC_KEY
    assert load_tool().main([]) == (1 if placeholder else 0)


def real_public_key() -> str:
    return base64.b64encode(Ed25519PrivateKey.generate().public_key().public_bytes_raw()).decode(
        "ascii"
    )


def test_a_real_32_byte_key_passes(tmp_path: Path) -> None:
    key = real_public_key()
    assert load_tool().main(["--file", str(module_with(tmp_path, f'"{key}"'))]) == 0


def test_placeholder_or_malformed_values_fail(tmp_path: Path) -> None:
    tool = load_tool()
    for value in (
        "PLACEHOLDER_PUBLIC_KEY",
        '"UNSET-OWNER-PUBLIC-KEY"',
        f'"{base64.b64encode(secrets.token_bytes(16)).decode("ascii")}"',
        '"not base64!"',
    ):
        assert tool.main(["--file", str(module_with(tmp_path, value))]) == 1


def test_a_missing_file_is_a_usage_error(tmp_path: Path) -> None:
    assert load_tool().main(["--file", str(tmp_path / "missing.py")]) == 2


def test_the_release_workflows_run_the_check() -> None:
    root = TOOL.parents[1]
    workflows = [root / ".github/workflows/release-image.yml"]
    assert workflows[0].exists()
    for workflow in workflows:
        assert "python3 tools/check-license-public-key.py" in workflow.read_text(encoding="utf-8")


def test_values_that_are_not_valid_ed25519_points_fail(tmp_path: Path) -> None:
    tool = load_tool()
    prime = 2**255 - 19
    neutral = (1).to_bytes(32, "little")
    order_two = (prime - 1).to_bytes(32, "little")
    above_prime = (prime + 5).to_bytes(32, "little")
    for raw in (neutral, order_two, above_prime):
        value = f'"{base64.b64encode(raw).decode("ascii")}"'
        assert tool.main(["--file", str(module_with(tmp_path, value))]) == 1
    for _ in range(50):
        raw = Ed25519PrivateKey.generate().public_key().public_bytes_raw()
        assert tool.is_valid_point(raw)


def test_a_private_key_marker_fails_without_being_echoed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seed = real_public_key()
    value = f'"ROADLAKE-LICENSE-PRIVATE-KEY-1:{seed}"'
    assert load_tool().main(["--file", str(module_with(tmp_path, value))]) == 1
    assert seed not in capsys.readouterr().err
