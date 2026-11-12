"""A database that cannot be reached is an error in `--full` and in CI, a skip in a quick run."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests import db as tests_db
from tests.db import configure_database_requirement, skip_or_fail_without_database

_CONFTEST = """
import pytest
from tests import db as tests_db
from tests.db import configure_database_requirement


def pytest_addoption(parser):
    parser.addoption("--full", action="store_true", default=False)


def pytest_configure(config):
    # Same call as backend/tests/conftest.py makes, with the same meaning of `--full`.
    configure_database_requirement(bool(config.getoption("--full")))
"""

_TEST = """
from tests.db import skip_or_fail_without_database


def test_needs_database():
    skip_or_fail_without_database("PostgreSQL integration database unavailable: refused")
"""


@pytest.fixture(autouse=True, scope="module")
def _requirement_is_left_unchanged() -> Iterator[None]:
    """Error out if this file leaks a changed requirement flag into the rest of a --full run."""

    before = tests_db._DATABASE_REQUIRED_BY_RUN
    yield
    assert tests_db._DATABASE_REQUIRED_BY_RUN is before


def _nested(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, *args: str, ci: bool):
    monkeypatch.delenv("SIDEKICK_FULL_TESTS", raising=False)
    if ci:
        monkeypatch.setenv("CI", "true")
    else:
        monkeypatch.delenv("CI", raising=False)
    backend = Path(__file__).resolve().parents[2]
    paths = [str(backend), str(backend / "src"), os.environ.get("PYTHONPATH", "")]
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(path for path in paths if path))
    pytester.makeconftest(_CONFTEST)
    pytester.makepyfile(test_nested=_TEST)
    return pytester.runpytest_subprocess(*args)


def test_quick_run_skips_when_the_database_is_missing(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _nested(pytester, monkeypatch, ci=False)
    assert result.ret == pytest.ExitCode.OK
    result.assert_outcomes(skipped=1)


def test_full_run_fails_when_the_database_is_missing(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _nested(pytester, monkeypatch, "--full", ci=False)
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*requires the test database*"])


def test_ci_run_fails_when_the_database_is_missing(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _nested(pytester, monkeypatch, ci=True)
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    result.assert_outcomes(failed=1)


def test_helper_in_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    # monkeypatch puts the run's own value back afterwards, whatever this test sets.
    monkeypatch.setattr(tests_db, "_DATABASE_REQUIRED_BY_RUN", False)
    with pytest.raises(pytest.skip.Exception):
        skip_or_fail_without_database("unavailable")
    configure_database_requirement(True)
    with pytest.raises(pytest.fail.Exception, match="unavailable"):
        skip_or_fail_without_database("unavailable")
