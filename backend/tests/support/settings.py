"""Shared test helpers moved out of `tests/api/test_auth_health.py`."""

from sidekick.shared.config import Settings
from tests.db import DATABASE_URL


def make_settings() -> Settings:
    return Settings(
        environment="test",
        database_url=DATABASE_URL,
        cursor_signing_secret="session-secret-for-tests-only-123456",
        token_pepper="token-pepper-for-tests-only-12345678",
    )
