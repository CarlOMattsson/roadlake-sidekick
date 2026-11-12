"""Fail-closed guarantees for destructive PostgreSQL test helpers."""

import pytest

from tests import db as tests_db
from tests.db import assert_safe_test_database, require_test_database_url

SAFE_URL = "postgresql+psycopg://sidekick_app:sidekick_app@127.0.0.1:55433/sidekick_test"


def test_safe_test_database_accepts_explicit_local_test_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIDEKICK_ENVIRONMENT", "test")
    monkeypatch.setenv("SIDEKICK_TEST_DATABASE_URL", SAFE_URL)
    assert assert_safe_test_database(SAFE_URL).database == "sidekick_test"


def test_safe_test_database_accepts_a_numbered_pool_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slot = SAFE_URL.replace("sidekick_test", "sidekick_test_3")
    monkeypatch.setenv("SIDEKICK_ENVIRONMENT", "test")
    monkeypatch.setenv("SIDEKICK_TEST_DATABASE_URL", slot)
    assert assert_safe_test_database(slot).database == "sidekick_test_3"


@pytest.mark.parametrize(
    ("environment", "url", "message"),
    [
        ("development", SAFE_URL, "SIDEKICK_ENVIRONMENT=test"),
        ("test", SAFE_URL.replace("sidekick_test", "sidekick"), "sidekick_test"),
        ("test", SAFE_URL.replace("127.0.0.1", "remote.example"), "host"),
        ("test", SAFE_URL.replace("sidekick_test", "sidekick_test_0"), "sidekick_test"),
        ("test", SAFE_URL.replace("sidekick_test", "sidekick_test_prod"), "sidekick_test"),
        ("test", SAFE_URL.replace("sidekick_test", "sidekick_testing"), "sidekick_test"),
    ],
)
def test_safe_test_database_rejects_unsafe_targets(
    monkeypatch: pytest.MonkeyPatch, environment: str, url: str, message: str
) -> None:
    monkeypatch.setenv("SIDEKICK_ENVIRONMENT", environment)
    monkeypatch.setenv("SIDEKICK_TEST_DATABASE_URL", url)
    with pytest.raises(RuntimeError, match=message):
        assert_safe_test_database(url)


def test_missing_test_url_is_an_explicit_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIDEKICK_ENVIRONMENT", "test")
    monkeypatch.delenv("SIDEKICK_TEST_DATABASE_URL", raising=False)
    monkeypatch.delenv("CI", raising=False)
    # monkeypatch restores the run's own value, so a --full run keeps requiring the database.
    monkeypatch.setattr(tests_db, "_DATABASE_REQUIRED_BY_RUN", False)
    with pytest.raises(pytest.skip.Exception, match="SIDEKICK_TEST_DATABASE_URL"):
        require_test_database_url()
