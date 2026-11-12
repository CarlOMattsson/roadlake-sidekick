"""The update reminder: where the age of the running code comes from, what the document declares.

`SIDEKICK_UPDATE_REMINDER_DAYS` is 14 by default and 0 switches it off. The age comes from the build
the Docker image carries, else the checkout's last commit, else it is unknown. The MCP side (the
resources on the wire) is in tests/mcp/test_update_reminder.py.
"""

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from sidekick.mcp.app_meta import with_app_context, with_update_reminder
from sidekick.shared import build_info
from sidekick.shared.build_info import (
    BuildInfo,
    UpdateReminder,
    parse_build_info,
    read_build_info_file,
    read_git_build_info,
    resolve_build_info,
    update_reminder,
)
from sidekick.shared.config import Settings

HTML = '<!doctype html><html><head><meta charset="utf-8"></head><body></body></html>'
COMMITTED = datetime(2026, 11, 9, 18, 38, 35, tzinfo=UTC)
FAR_BACK = "2020-01-02T03:04:05+00:00"


def make_checkout(path: Path, when: str) -> None:
    identity = ["-c", "user.name=t", "-c", "user.email=t@example.test"]
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(
        ["git", *identity, "-C", str(path), "commit", "-q", "--allow-empty", "-m", "x"],
        check=True,
        env={"GIT_COMMITTER_DATE": when, "GIT_AUTHOR_DATE": when, "PATH": "/usr/bin:/bin"},
    )


def no_checkout(repo: Path) -> None:
    return None


@pytest.fixture(autouse=True)
def fresh_build_cache() -> None:
    build_info.resolved_build_info.cache_clear()


def test_the_reminder_defaults_to_two_weeks_and_zero_turns_it_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert Settings().update_reminder_days == 14
    monkeypatch.setenv("SIDEKICK_UPDATE_REMINDER_DAYS", "0")
    assert Settings().update_reminder_days == 0
    monkeypatch.setenv("SIDEKICK_UPDATE_REMINDER_DAYS", "-1")
    with pytest.raises(ValidationError):
        Settings()


def test_the_build_variables_of_a_docker_image_do_not_stop_the_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIDEKICK_BUILD_COMMIT", "abc1234")
    monkeypatch.setenv("SIDEKICK_BUILD_DATE", "2026-11-09T19:38:35+01:00")
    settings = Settings()
    assert (settings.build_commit, settings.build_date) == ("abc1234", "2026-11-09T19:38:35+01:00")


def test_a_configured_build_is_a_short_hash_and_a_date_in_utc() -> None:
    build = parse_build_info("ABC1234DEF5678", "2026-11-09T19:38:35+01:00")
    assert build == BuildInfo("abc1234", COMMITTED)


@pytest.mark.parametrize(
    ("commit", "date"),
    [
        ("", "2026-11-09T19:38:35+01:00"),
        ("abc1234", ""),
        ("not-a-hash", "2026-11-09T19:38:35+01:00"),
        ("abc1234", "yesterday"),
        ("abc1234", "2026-11-09T19:38:35"),  # no timezone: the age would be a guess
    ],
)
def test_a_missing_or_malformed_build_is_unknown(commit: str, date: str) -> None:
    assert parse_build_info(commit, date) is None


def test_the_environment_wins_over_the_checkout(tmp_path: Path) -> None:
    make_checkout(tmp_path, FAR_BACK)
    build = resolve_build_info("", "abc1234", "2026-11-09T19:38:35+01:00", repo=tmp_path)
    assert build == BuildInfo("abc1234", COMMITTED)


def test_without_a_configured_build_the_checkout_gives_hash_and_date(tmp_path: Path) -> None:
    make_checkout(tmp_path, FAR_BACK)
    build = resolve_build_info("", "", "", repo=tmp_path)
    assert build is not None
    assert build.committed_at == datetime(2020, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert len(build.commit) >= 7


def test_a_half_configured_build_falls_back_to_the_checkout(tmp_path: Path) -> None:
    make_checkout(tmp_path, FAR_BACK)
    build = resolve_build_info("", "abc1234", "", repo=tmp_path)
    assert build is not None
    assert build.committed_at.year == 2020


def test_a_folder_that_is_no_checkout_is_unknown_even_inside_another_repository(
    tmp_path: Path,
) -> None:
    make_checkout(tmp_path, FAR_BACK)
    inner = tmp_path / "installed"
    inner.mkdir()
    assert read_git_build_info(inner) is None
    assert resolve_build_info("", "", "", repo=inner) is None


def test_a_checkout_that_the_tool_cannot_read_is_unknown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".git").mkdir()  # not a repository: the tool answers with an error
    assert read_git_build_info(tmp_path) is None

    def missing_tool(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("git")

    monkeypatch.setattr(build_info.subprocess, "run", missing_tool)
    assert read_git_build_info(tmp_path) is None


def write_info(path: Path, content: str) -> str:
    path.write_text(content, encoding="utf-8")
    return str(path)


def test_the_build_file_gives_the_update_date_before_the_build_date(tmp_path: Path) -> None:
    info = write_info(
        tmp_path / "build-info.json",
        '{"commit": "0123456789abcdef", "built_at": "2026-10-01T08:00:00+00:00",'
        ' "updated_at": "2026-11-09T19:38:35+01:00"}',
    )
    assert read_build_info_file(info) == BuildInfo("0123456", COMMITTED)


def test_the_build_file_falls_back_to_the_build_date_without_an_update_date(
    tmp_path: Path,
) -> None:
    info = write_info(
        tmp_path / "build-info.json",
        '{"commit": "abc1234", "built_at": "2026-11-09T18:38:35Z", "updated_at": ""}',
    )
    assert read_build_info_file(info) == BuildInfo("abc1234", COMMITTED)


def test_the_build_file_is_the_first_source(tmp_path: Path) -> None:
    info = write_info(
        tmp_path / "build-info.json",
        '{"commit": "fedcba9", "updated_at": "2026-11-09T18:38:35Z"}',
    )
    build = resolve_build_info(info, "abc1234", "2020-01-02T03:04:05+00:00", repo=tmp_path)
    assert build == BuildInfo("fedcba9", COMMITTED)


@pytest.mark.parametrize(
    "content",
    [
        None,  # no such file
        "",
        "{not json",
        "[]",
        '{"commit": "abc1234"}',
        '{"built_at": "2026-11-09T18:38:35Z"}',
        '{"commit": 5, "built_at": "2026-11-09T18:38:35Z"}',
        '{"commit": "abc1234", "built_at": "2026-11-09T18:38:35"}',
    ],
)
def test_a_missing_or_broken_build_file_is_unknown_and_falls_through(
    tmp_path: Path, content: str | None
) -> None:
    info = (
        str(tmp_path / "absent.json")
        if content is None
        else write_info(tmp_path / "build-info.json", content)
    )
    assert read_build_info_file(info) is None
    fallback = resolve_build_info(info, "abc1234", "2026-11-09T19:38:35+01:00", repo=tmp_path)
    assert fallback == BuildInfo("abc1234", COMMITTED)
    assert resolve_build_info(info, "", "", repo=tmp_path) is None


def test_a_build_file_that_is_a_directory_or_unset_does_not_stop_anything(
    tmp_path: Path,
) -> None:
    assert read_build_info_file(str(tmp_path)) is None
    assert read_build_info_file("") is None


def test_the_build_file_setting_reaches_the_reminder(tmp_path: Path) -> None:
    info = write_info(
        tmp_path / "build-info.json",
        '{"commit": "abc1234", "updated_at": "2026-11-09T19:38:35+01:00"}',
    )
    settings = Settings(build_info_file=info)
    assert settings.update_reminder == UpdateReminder(BuildInfo("abc1234", COMMITTED), 14)


def test_a_build_file_setting_that_names_nothing_leaves_the_start_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SIDEKICK_BUILD_INFO_FILE", str(tmp_path / "absent.json"))
    monkeypatch.setattr(build_info, "read_git_build_info", no_checkout)
    assert Settings().update_reminder is None


def test_the_reminder_is_off_for_zero_days_and_for_an_unknown_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert update_reminder(0, "", "abc1234", "2026-11-09T19:38:35+01:00") is None
    monkeypatch.setattr(build_info, "read_git_build_info", no_checkout)
    assert update_reminder(14, "", "", "") is None


def test_the_reminder_carries_the_build_and_the_days() -> None:
    reminder = update_reminder(14, "", "abc1234", "2026-11-09T19:38:35+01:00")
    assert reminder == UpdateReminder(BuildInfo("abc1234", COMMITTED), 14)


def test_the_build_is_resolved_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def resolve(info_file: str, commit: str, committed_at: str) -> None:
        calls.append(commit)

    monkeypatch.setattr(build_info, "resolve_build_info", resolve)
    update_reminder(14, "", "", "")
    update_reminder(30, "", "", "")
    assert len(calls) == 1


def test_the_settings_give_the_reminder_from_their_build_values() -> None:
    settings = Settings(build_commit="abc1234", build_date="2026-11-09T19:38:35+01:00")
    assert settings.update_reminder == UpdateReminder(BuildInfo("abc1234", COMMITTED), 14)
    assert settings.model_copy(update={"update_reminder_days": 0}).update_reminder is None


def test_the_app_document_declares_the_build_and_the_days_once() -> None:
    declared = with_update_reminder(HTML, UpdateReminder(BuildInfo("abc1234", COMMITTED), 21))
    assert declared.count('name="sidekick-build-commit"') == 1
    assert (
        '<head><meta name="sidekick-build-commit" content="abc1234">'
        '<meta name="sidekick-build-date" content="2026-11-09T18:38:35+00:00">'
        '<meta name="sidekick-update-days" content="21"><meta charset="utf-8">'
    ) in declared


def test_an_off_or_unknown_reminder_leaves_the_document_alone() -> None:
    assert with_update_reminder(HTML, None) == HTML


def test_the_app_context_carries_locale_rooms_and_reminder() -> None:
    declared = with_app_context(
        HTML, "en", {"work"}, UpdateReminder(BuildInfo("abc1234", COMMITTED), 14)
    )
    assert 'name="sidekick-app-locale" content="en"' in declared
    assert 'name="sidekick-rooms" content="work"' in declared
    assert 'name="sidekick-build-commit" content="abc1234"' in declared
