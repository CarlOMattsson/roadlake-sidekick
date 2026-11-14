"""The failed-first-start decisions of tools/workctl: log evidence, table state, volume, hint."""

import pytest
from tools.workctl import diagnose, messages

AUTH = 'FATAL: password authentication failed for user "sidekick_migrator"'


@pytest.mark.parametrize(
    "evidence",
    [
        AUTH,
        'FATAL:  role "sidekick_migrator" does not exist',
        "sidekick_migrator: authentication failed",
        "line one\n" + AUTH.upper() + "\nline three",
    ],
)
def test_migrator_failures_are_evidence(evidence: str) -> None:
    assert diagnose.has_failure_evidence(evidence, "")


@pytest.mark.parametrize(
    "evidence",
    [
        "",
        "start failed",
        'password authentication failed for user "someone_else"',
        # The two halves of a pattern on different lines are not a match.
        "password authentication failed\nfor sidekick_migrator",
    ],
)
def test_other_output_is_not_evidence(evidence: str) -> None:
    assert not diagnose.has_failure_evidence(evidence, "")


def test_a_denied_init_script_in_the_postgres_log_is_evidence() -> None:
    log = "sh: /docker-entrypoint-initdb.d/10-sidekick-roles.sh: Permission denied"
    assert diagnose.has_failure_evidence("", log)
    assert not diagnose.has_failure_evidence(log, "")


@pytest.mark.parametrize(
    ("table", "count", "applied"),
    [
        ("absent", "", True),
        ("_yoyo_migration", "0", True),
        ("public._yoyo_migration", "0", True),
        ("_yoyo_migration", "1", False),
        ("_yoyo_migration", "", False),
        ("unknown", "0", False),
        ("", "0", False),
    ],
)
def test_only_an_absent_or_empty_table_means_nothing_was_applied(
    table: str, count: str, applied: bool
) -> None:
    assert diagnose.nothing_applied(table, count) is applied


@pytest.mark.parametrize(
    ("table", "needed"),
    [("absent", False), ("_yoyo_migration", True), ("public._yoyo_migration", True), ("x", False)],
)
def test_the_count_is_asked_for_only_when_the_table_exists(table: str, needed: bool) -> None:
    assert diagnose.count_needed(table) is needed


def test_the_hint_names_the_volume_and_the_quoted_commands() -> None:
    hint = diagnose.volume_hint("en", "my work", "my-work_pgdata", "absent", "")
    assert "Volume my-work_pgdata must be removed" in hint
    assert "\n  SIDEKICK_WORK_PROJECT='my work' bash tools/work.sh stop\n" in hint
    assert "\n  docker volume rm my-work_pgdata\n" in hint
    assert hint.endswith("Then start with: bash tools/work.sh start --build")
    assert "\\n" not in hint


def test_the_hint_is_in_the_asked_language() -> None:
    hint = diagnose.volume_hint("sv", "p", "p_pgdata", "_yoyo_migration", "0")
    assert "inga migreringar har tillämpats" in hint
    assert hint == messages.render(
        "sv",
        "first_start_volume",
        "p_pgdata",
        "SIDEKICK_WORK_PROJECT=p bash tools/work.sh stop",
        "docker volume rm p_pgdata",
    )


@pytest.mark.parametrize("volume", ["", "a\nb", "-x", "a b", "a;rm -rf /", "$(x)", "a\n"])
def test_an_unsafe_volume_name_gets_no_hint(volume: str) -> None:
    assert diagnose.volume_hint("en", "p", volume, "absent", "") == ""


def test_data_in_the_table_gets_no_hint() -> None:
    assert diagnose.volume_hint("en", "p", "p_pgdata", "_yoyo_migration", "3") == ""
