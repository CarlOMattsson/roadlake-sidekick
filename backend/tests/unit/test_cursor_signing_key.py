"""Pagination cursors are signed with a configured or per-process key, never a source constant."""

import inspect
import re
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

import sidekick
from sidekick.shared.config import Settings
from sidekick.shared.errors import InvalidInputError
from sidekick.shared.types import CursorCodec
from sidekick.work.application.service import ContextService

ACTOR = UUID(int=7)


def test_production_without_a_configured_secret_does_not_start() -> None:
    with pytest.raises(ValidationError, match="cursor signing secret must be configured"):
        Settings(_env_file=None, environment="production")


def test_configured_secret_signs_cursors() -> None:
    settings = Settings(_env_file=None, cursor_signing_secret="s" * 40)
    assert settings.cursor_signing_key == "s" * 40


def test_placeholder_secret_never_becomes_the_signing_key() -> None:
    settings = Settings(_env_file=None)
    assert settings.cursor_signing_secret.startswith("development-")
    assert settings.cursor_signing_key != settings.cursor_signing_secret
    assert len(settings.cursor_signing_key) >= 32


def test_cursor_from_another_key_is_rejected_as_invalid() -> None:
    issued = CursorCodec("a" * 40).encode(ACTOR, 25, "tasks")
    with pytest.raises(InvalidInputError, match="invalid pagination cursor"):
        CursorCodec("b" * 40).decode(ACTOR, issued, "tasks")


def test_cursor_codec_is_a_required_service_dependency() -> None:
    parameter = inspect.signature(ContextService.__init__).parameters["cursor_codec"]
    assert parameter.default is inspect.Parameter.empty
    assert "None" not in str(parameter.annotation)


@pytest.mark.policy
def test_no_constant_cursor_secret_in_source() -> None:
    root = Path(sidekick.__file__).parent
    offenders = [
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if re.search(r"CursorCodec\(\s*[\"']", path.read_text())
        or "application-test-cursor-secret" in path.read_text()
    ]
    assert offenders == []
