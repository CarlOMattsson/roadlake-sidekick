"""The suite points itself at the test database.

Requiring three exported variables meant a run on a shell that did not have them skipped
every database-backed test and still reported success. These tests hold the defaulting to
the two properties that make it safe: it fills only what is absent, and it fills it with the
values the repository's own compose file and role script already fix.
"""

import os

import pytest

from conftest import (
    DEFAULT_TEST_DB_BIND,
    TEST_DATABASE_ROLES,
    TEST_ENVIRONMENT_VARIABLES,
    _default_test_database_urls,
    _per_worker_test_databases,
    _use_psycopg_driver,
)

EXPECTED = {
    "SIDEKICK_TEST_DATABASE_URL": (
        "postgresql+psycopg://sidekick_app:sidekick_app@127.0.0.1:55433/sidekick_test"
    ),
    "SIDEKICK_TEST_MIGRATION_DATABASE_URL": (
        "postgresql+psycopg://sidekick_migrator:sidekick_migrator@127.0.0.1:55433/sidekick_test"
    ),
    "SIDEKICK_TEST_ADMIN_DATABASE_URL": (
        "postgresql+psycopg://postgres:postgres@127.0.0.1:55433/sidekick_test"
    ),
}


def _clear(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in TEST_DATABASE_ROLES:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.delenv("SIDEKICK_TEST_DB_BIND", raising=False)


def test_absent_variables_default_to_the_reviewed_local_test_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact three URLs `QUICKSTART.md` used to require the operator to retype."""

    _clear(monkeypatch)

    _default_test_database_urls()

    import os

    assert {name: os.environ[name] for name in EXPECTED} == EXPECTED
    assert DEFAULT_TEST_DB_BIND == "127.0.0.1:55433"


def test_an_explicitly_configured_target_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    """Continuous integration exports all three, so nothing may be defaulted over them."""

    _clear(monkeypatch)
    explicit = "postgresql+psycopg://sidekick_app:sidekick_app@localhost:55433/sidekick_test"
    monkeypatch.setenv("SIDEKICK_TEST_DATABASE_URL", explicit)

    _default_test_database_urls()

    import os

    assert os.environ["SIDEKICK_TEST_DATABASE_URL"] == explicit
    assert (
        os.environ["SIDEKICK_TEST_ADMIN_DATABASE_URL"]
        == EXPECTED["SIDEKICK_TEST_ADMIN_DATABASE_URL"]
    )


def test_a_plain_postgresql_scheme_is_rewritten_to_psycopg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An older export of `postgresql://` keeps working: psycopg 3 is the only driver installed."""

    _clear(monkeypatch)
    plain = "postgresql://sidekick_migrator:sidekick_migrator@127.0.0.1:55433/sidekick_test"
    already = "postgresql+psycopg://postgres:postgres@127.0.0.1:55433/sidekick_test"
    monkeypatch.setenv("SIDEKICK_TEST_MIGRATION_DATABASE_URL", plain)
    monkeypatch.setenv("SIDEKICK_TEST_ADMIN_DATABASE_URL", already)

    _use_psycopg_driver()

    assert os.environ["SIDEKICK_TEST_MIGRATION_DATABASE_URL"] == plain.replace(
        "postgresql://", "postgresql+psycopg://"
    )
    assert os.environ["SIDEKICK_TEST_ADMIN_DATABASE_URL"] == already
    assert "SIDEKICK_TEST_DATABASE_URL" not in os.environ


def test_a_blank_value_is_treated_as_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("SIDEKICK_TEST_DATABASE_URL", "")

    _default_test_database_urls()

    import os

    assert os.environ["SIDEKICK_TEST_DATABASE_URL"] == EXPECTED["SIDEKICK_TEST_DATABASE_URL"]


def test_a_non_default_bind_stays_one_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    """`SIDEKICK_TEST_DB_BIND` already parameterises the compose bind, so it is honoured here."""

    _clear(monkeypatch)
    monkeypatch.setenv("SIDEKICK_TEST_DB_BIND", "127.0.0.1:65432")

    _default_test_database_urls()

    import os

    for name, expected in EXPECTED.items():
        assert os.environ[name] == expected.replace(":55433", ":65432")


def test_every_defaulted_variable_is_one_the_suite_is_allowed_to_inherit() -> None:
    assert set(TEST_DATABASE_ROLES) <= TEST_ENVIRONMENT_VARIABLES


def test_every_default_targets_the_dedicated_test_database_on_an_allowlisted_host() -> None:
    """The safety helpers refuse anything else, so a default that broke this would fail loudly."""

    from sqlalchemy.engine import make_url

    from tests.db import ALLOWED_TEST_HOSTS

    for url in EXPECTED.values():
        parsed = make_url(url)
        assert parsed.database == "sidekick_test"
        assert parsed.host in ALLOWED_TEST_HOSTS


def _set_test_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set through monkeypatch so the per-worker rewrite is undone after each test."""

    for name, value in EXPECTED.items():
        monkeypatch.setenv(name, value)


def test_without_xdist_the_test_urls_are_not_rewritten(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_test_urls(monkeypatch)
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)

    _per_worker_test_databases()

    assert {name: os.environ[name] for name in EXPECTED} == EXPECTED


@pytest.mark.parametrize(
    ("base", "worker", "expected_database"),
    [
        ("sidekick_test", "gw0", "sidekick_test_w0"),
        ("sidekick_test", "gw2", "sidekick_test_w2"),
        ("sidekick_test_3", "gw0", "sidekick_test_3_w0"),
        ("sidekick_test_3", "gw1", "sidekick_test_3_w1"),
        ("sidekick_test_12", "gw11", "sidekick_test_12_w11"),
    ],
)
def test_an_xdist_worker_uses_its_own_database_under_the_base(
    monkeypatch: pytest.MonkeyPatch, base: str, worker: str, expected_database: str
) -> None:
    """Worker `gwN` gets `<base>_wN`; `sidekick_test` is the base for CI and is not a slot.

    User, password and host stay as they were. A run on slot K therefore only ever
    touches `sidekick_test_K_w*`, never another slot's workers.
    """

    for name, expected in EXPECTED.items():
        monkeypatch.setenv(name, expected.replace("/sidekick_test", f"/{base}"))
    monkeypatch.setenv("PYTEST_XDIST_WORKER", worker)

    _per_worker_test_databases()

    for name, expected in EXPECTED.items():
        assert os.environ[name] == expected.replace("/sidekick_test", f"/{expected_database}")


def test_a_url_that_already_names_a_worker_database_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rewriting it would give every worker the same database and let them erase each other."""

    _set_test_urls(monkeypatch)
    monkeypatch.setenv(
        "SIDEKICK_TEST_DATABASE_URL",
        EXPECTED["SIDEKICK_TEST_DATABASE_URL"].replace("/sidekick_test", "/sidekick_test_7_w0"),
    )
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw1")

    with pytest.raises(RuntimeError, match="base database"):
        _per_worker_test_databases()


@pytest.mark.parametrize(
    "name",
    [
        "sidekick_test",
        "sidekick_test_1",
        "sidekick_test_20",
        "sidekick_test_w0",
        "sidekick_test_w12",
        "sidekick_test_7_w0",
        "sidekick_test_7_w12",
    ],
)
def test_the_guard_accepts_exactly_the_base_slot_and_worker_names(name: str) -> None:
    from tests.db_guard import SAFE_TEST_DATABASE_NAME as _SAFE_TEST_DATABASE_NAME

    assert _SAFE_TEST_DATABASE_NAME.fullmatch(name)


@pytest.mark.parametrize(
    "name",
    [
        "sidekick",
        "sidekick_test_",
        "sidekick_test_0",
        "sidekick_test_0_w0",
        "sidekick_test_07",
        "sidekick_test_100",
        "sidekick_test_w",
        "sidekick_test_w100",
        "sidekick_test_7_w",
        "sidekick_test_7_w123",
        "sidekick_test_7_w0_w1",
        "sidekick_test_7_x0",
        "ai_owned_testing_instance",
        "sidekick_test_w0_extra",
    ],
)
def test_the_guard_refuses_every_other_database_name(name: str) -> None:
    from tests.db_guard import SAFE_TEST_DATABASE_NAME as _SAFE_TEST_DATABASE_NAME

    assert _SAFE_TEST_DATABASE_NAME.fullmatch(name) is None


def test_the_conftest_and_the_guard_accept_the_same_names() -> None:
    from conftest import _POOL_DATABASE
    from tests.db_guard import SAFE_TEST_DATABASE_NAME as _SAFE_TEST_DATABASE_NAME

    assert _POOL_DATABASE.pattern == _SAFE_TEST_DATABASE_NAME.pattern


def test_the_latest_migration_id_is_the_highest_numbered_file() -> None:
    """The head the migration check compares with is the newest `NNN_name.py` in migrations/."""

    from tests.db import MIGRATIONS_PATH, latest_migration_id

    head = latest_migration_id()

    assert (MIGRATIONS_PATH / f"{head}.py").is_file()
    numbers = [
        int(path.stem.partition("_")[0])
        for path in MIGRATIONS_PATH.glob("*.py")
        if path.stem.partition("_")[0].isdigit()
    ]
    assert int(head.partition("_")[0]) == max(numbers)


def test_urls_on_another_port_or_database_are_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the test container's port and the sidekick_test pool names are ever rewritten."""

    other_port = "postgresql+psycopg://sidekick_app:sidekick_app@127.0.0.1:5432/sidekick_test"
    other_database = "postgresql://postgres:postgres@127.0.0.1:55433/ai_owned_testing_instance"
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw0")
    monkeypatch.setenv("SIDEKICK_TEST_DATABASE_URL", other_port)
    monkeypatch.setenv("SIDEKICK_TEST_MIGRATION_DATABASE_URL", other_port)
    monkeypatch.setenv("SIDEKICK_TEST_ADMIN_DATABASE_URL", other_database)

    _per_worker_test_databases()

    assert os.environ["SIDEKICK_TEST_DATABASE_URL"] == other_port
    assert os.environ["SIDEKICK_TEST_MIGRATION_DATABASE_URL"] == other_port
    assert os.environ["SIDEKICK_TEST_ADMIN_DATABASE_URL"] == other_database
