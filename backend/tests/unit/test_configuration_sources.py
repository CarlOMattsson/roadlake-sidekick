"""Where a process took its configuration from, and what it is allowed to say about it.

The precedence itself is not under test and is not changing: a real environment variable
outranks the dotenv file, because CI and the packaged desktop configure the application
entirely through variables. What is under test is that the override stops being silent, and
that making it visible never puts a value in a log.
"""

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from sidekick.api.app import LOGGER, _log_configuration_sources
from sidekick.shared.config import (
    ConfigurationSources,
    Settings,
    configuration_sources,
    declared_variable_names,
    describe_configuration_sources,
    dotenv_variables,
)


class _Collector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture(name="records")
def _records() -> Iterator[_Collector]:
    collector = _Collector()
    LOGGER.addHandler(collector)
    previous = LOGGER.level
    LOGGER.setLevel(logging.INFO)
    try:
        yield collector
    finally:
        LOGGER.removeHandler(collector)
        LOGGER.setLevel(previous)


def test_the_declared_names_are_every_setting_and_nothing_else() -> None:
    names = declared_variable_names()

    assert "SIDEKICK_MEMORY_PROVIDER" in names
    assert "SIDEKICK_MEMORY_HINDSIGHT_BASE_URL" in names
    # A setting of a removed feature is tolerated but is no longer a declared one.
    assert "SIDEKICK_CHAT_MODEL_PROVIDER" not in names
    assert len(names) == len(Settings.model_fields)
    assert all(name.startswith("SIDEKICK_") and name.isupper() for name in names)
    # The test-database variables are not settings, so they are somebody else's variables.
    assert "SIDEKICK_TEST_DATABASE_URL" not in names


def test_a_variable_the_environment_sets_differently_is_a_disagreement() -> None:
    sources = configuration_sources(
        environ={"SIDEKICK_MEMORY_PROVIDER": "openrouter"},
        dotenv={"SIDEKICK_MEMORY_PROVIDER": "google_ai_studio"},
    )

    assert sources.disagreeing_with_the_file == ("SIDEKICK_MEMORY_PROVIDER",)
    assert sources.environment_only == ()
    assert sources.has_disagreement is True


def test_a_variable_the_file_does_not_mention_is_not_a_disagreement() -> None:
    sources = configuration_sources(
        environ={"SIDEKICK_MEMORY_PROVIDER": "google_ai_studio"},
        dotenv={},
    )

    assert sources.disagreeing_with_the_file == ()
    assert sources.environment_only == ("SIDEKICK_MEMORY_PROVIDER",)
    assert sources.has_disagreement is False


def test_agreement_reports_nothing() -> None:
    same = {"SIDEKICK_MEMORY_PROVIDER": "google_ai_studio", "SIDEKICK_OWNER_TIMEZONE": "m"}

    sources = configuration_sources(environ=same, dotenv=same)

    assert sources == ConfigurationSources()


def test_a_variable_only_the_file_sets_is_not_reported() -> None:
    sources = configuration_sources(
        environ={}, dotenv={"SIDEKICK_MEMORY_PROVIDER": "google_ai_studio"}
    )

    assert sources == ConfigurationSources()


def test_undeclared_variables_are_ignored() -> None:
    sources = configuration_sources(
        environ={"SIDEKICK_TEST_DATABASE_URL": "a", "PATH": "b"},
        dotenv={"SIDEKICK_TEST_DATABASE_URL": "c"},
    )

    assert sources == ConfigurationSources()


def test_names_are_ordered_so_the_record_is_stable() -> None:
    environ = {
        "SIDEKICK_TOKEN_PEPPER": "x",
        "SIDEKICK_OWNER_TIMEZONE": "y",
        "SIDEKICK_CURSOR_SIGNING_SECRET": "z",
    }
    dotenv = dict.fromkeys(environ, "different")

    first = configuration_sources(environ=environ, dotenv=dotenv)
    second = configuration_sources(environ=dict(reversed(list(environ.items()))), dotenv=dotenv)

    assert first.disagreeing_with_the_file == second.disagreeing_with_the_file
    assert first.disagreeing_with_the_file == (
        "SIDEKICK_CURSOR_SIGNING_SECRET",
        "SIDEKICK_OWNER_TIMEZONE",
        "SIDEKICK_TOKEN_PEPPER",
    )


def test_the_diagnostic_dotenv_read_handles_the_forms_a_dotenv_file_uses(
    tmp_path: Path,
) -> None:
    file = tmp_path / ".env"
    file.write_text(
        "\n".join(
            [
                "# a comment",
                "",
                "SIDEKICK_MEMORY_PROVIDER=custom_openai",
                'SIDEKICK_MCP_SERVER_NAME={"X-Title": "Sidekick"}',
                "SIDEKICK_OWNER_TIMEZONE=  spaced-out  ",
                "SIDEKICK_MEMORY_HINDSIGHT_BASE_URL='http://127.0.0.1:11434/v1'",
                'SIDEKICK_BUILD_COMMIT="sv"',
                "SIDEKICK_DATABASE_URL=postgresql://a:b@localhost:5432/c?x=1",
                "not-an-assignment",
            ]
        ),
        encoding="utf-8",
    )

    values = dotenv_variables(file)

    assert values["SIDEKICK_MEMORY_PROVIDER"] == "custom_openai"
    # An equals sign inside a value survives, because only the first one separates.
    assert values["SIDEKICK_MCP_SERVER_NAME"] == '{"X-Title": "Sidekick"}'
    assert values["SIDEKICK_DATABASE_URL"] == "postgresql://a:b@localhost:5432/c?x=1"
    assert values["SIDEKICK_OWNER_TIMEZONE"] == "spaced-out"
    assert values["SIDEKICK_MEMORY_HINDSIGHT_BASE_URL"] == "http://127.0.0.1:11434/v1"
    assert values["SIDEKICK_BUILD_COMMIT"] == "sv"
    assert "not-an-assignment" not in values
    assert len(values) == 6


def test_a_missing_dotenv_file_is_not_an_error(tmp_path: Path) -> None:
    assert dotenv_variables(tmp_path / "absent") == {}
    assert dotenv_variables(tmp_path) == {}


def test_the_suite_itself_reports_nothing_whatever_the_machine_holds() -> None:
    """`conftest` sets `env_file=None`, so there is no file for anything to disagree with."""

    assert Settings.model_config.get("env_file") is None
    assert describe_configuration_sources() == ConfigurationSources()
    assert describe_configuration_sources({"SIDEKICK_OWNER_TIMEZONE": "ambient"}) == (
        ConfigurationSources()
    )


def test_a_disagreement_is_recorded_at_warning_with_names_and_no_values(
    records: _Collector,
) -> None:
    _log_configuration_sources(
        ConfigurationSources(
            disagreeing_with_the_file=("SIDEKICK_MEMORY_HINDSIGHT_API_TOKEN",),
            environment_only=("SIDEKICK_CURSOR_SIGNING_SECRET",),
            dotenv_file_found=True,
        )
    )

    record = records.records[-1]
    fields = vars(record)
    assert record.levelno == logging.WARNING
    assert fields["config_environment_disagreements"] == "SIDEKICK_MEMORY_HINDSIGHT_API_TOKEN"
    assert fields["config_environment_only"] == "SIDEKICK_CURSOR_SIGNING_SECRET"
    assert fields["config_dotenv_file"] == "found"


def test_no_disagreement_stays_informational(records: _Collector) -> None:
    _log_configuration_sources(ConfigurationSources())

    record = records.records[-1]
    assert record.levelno == logging.INFO
    assert vars(record)["config_environment_disagreements"] == "(none)"
    assert vars(record)["config_environment_only"] == "(none)"
    assert vars(record)["config_dotenv_file"] == "(unknown)"


def test_variables_only_in_a_container_environment_are_not_reported_as_absent(
    records: _Collector,
) -> None:
    """A container with `env_file` has no `.env` in it, so every variable is environment-only.

    That must read as the normal case it is: informational, named as set in the environment,
    and the missing file stated plainly rather than presented as a list of absent settings.
    """

    _log_configuration_sources(
        ConfigurationSources(
            environment_only=("SIDEKICK_MEMORY_PROVIDER", "SIDEKICK_CURSOR_SIGNING_SECRET"),
            dotenv_file_found=False,
        )
    )

    record = records.records[-1]
    fields = vars(record)
    assert record.levelno == logging.INFO
    assert fields["config_environment_only"] == (
        "SIDEKICK_MEMORY_PROVIDER,SIDEKICK_CURSOR_SIGNING_SECRET"
    )
    assert fields["config_dotenv_file"] == "missing"
    assert "config_absent_from_the_file" not in fields


def test_the_described_sources_say_whether_the_file_was_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`describe_configuration_sources` reads the real `env_file` path, so the flag is honest."""

    present = tmp_path / "present.env"
    present.write_text("SIDEKICK_MEMORY_PROVIDER=fake\n", encoding="utf-8")
    absent = tmp_path / "absent.env"
    environ = {"SIDEKICK_MEMORY_PROVIDER": "fake", "SIDEKICK_CURSOR_SIGNING_SECRET": "x"}
    monkeypatch.setitem(Settings.model_config, "env_file", str(present))

    found = describe_configuration_sources(environ)
    monkeypatch.setitem(Settings.model_config, "env_file", str(absent))
    missing = describe_configuration_sources(environ)

    assert found.dotenv_file_found is True
    assert found.environment_only == ("SIDEKICK_CURSOR_SIGNING_SECRET",)
    assert missing.dotenv_file_found is False
    assert missing.environment_only == (
        "SIDEKICK_CURSOR_SIGNING_SECRET",
        "SIDEKICK_MEMORY_PROVIDER",
    )
    assert missing.disagreeing_with_the_file == ()


def test_the_record_can_carry_a_credential_name_but_never_its_value(
    records: _Collector,
) -> None:
    """Naming the variable is the point; the key itself is never read into the record."""

    sources = configuration_sources(
        environ={"SIDEKICK_MEMORY_HINDSIGHT_API_TOKEN": "ENVIRONMENT_SENTINEL"},
        dotenv={"SIDEKICK_MEMORY_HINDSIGHT_API_TOKEN": "FILE_SENTINEL"},
    )
    assert sources.disagreeing_with_the_file == ("SIDEKICK_MEMORY_HINDSIGHT_API_TOKEN",)
    assert "SENTINEL" not in str(sources)

    _log_configuration_sources(sources)

    rendered = str(vars(records.records[-1]))
    assert "SIDEKICK_MEMORY_HINDSIGHT_API_TOKEN" in rendered
    assert "SENTINEL" not in rendered
