"""`.env.example` stays loadable: every key it names, active or commented out, is a live setting."""

import re
from pathlib import Path

import pytest

from sidekick.shared.config import Settings

pytestmark = pytest.mark.policy

ENV_EXAMPLE = Path(__file__).resolve().parents[3] / ".env.example"
KEY = re.compile(r"^#?\s*(SIDEKICK_[A-Z0-9_]+)=", re.MULTILINE)


def _keys() -> set[str]:
    return set(KEY.findall(ENV_EXAMPLE.read_text(encoding="utf-8")))


def test_every_key_in_the_example_is_a_declared_setting() -> None:
    declared = {f"SIDEKICK_{name}".upper() for name in Settings.model_fields}
    assert _keys()
    assert not _keys() - declared, sorted(_keys() - declared)


def test_the_example_does_not_claim_to_list_every_setting() -> None:
    assert "not the full list" in ENV_EXAMPLE.read_text(encoding="utf-8")
