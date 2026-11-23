"""Shared test helpers moved out of `tests/api/test_auth_health.py`."""

import atexit
import shutil
import tempfile
from pathlib import Path

from sidekick.shared.config import Settings
from tests.db import DATABASE_URL

# Photo files written by a test go to one scratch directory that is removed when the run ends, never
# to a directory under the working tree.
MEDIA_DIRECTORY = Path(tempfile.mkdtemp(prefix="sidekick-test-media-"))
atexit.register(shutil.rmtree, MEDIA_DIRECTORY, ignore_errors=True)


def make_settings() -> Settings:
    return Settings(
        environment="test",
        database_url=DATABASE_URL,
        cursor_signing_secret="session-secret-for-tests-only-123456",
        token_pepper="token-pepper-for-tests-only-12345678",
        media_directory=MEDIA_DIRECTORY,
    )
