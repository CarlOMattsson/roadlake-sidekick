"""How work.sh was called and what docker reports, as plain functions and as shell commands."""

from pathlib import Path

import pytest
from tools.workctl import cli, desktopconfig, invocation, stackstate


def _options(command: str, *args: str) -> dict[str, str]:
    return dict(invocation.parse_options(command, args).values)


def test_start_options_default_to_off() -> None:
    assert _options("start") == {"BUILD": "0", "NO_CACHE": "0", "WAIT_DOCKER": "0"}


def test_start_options_accept_every_known_flag_in_any_order() -> None:
    options = _options("start", "--wait-docker", "--no-cache", "--build")
    assert options == {"BUILD": "1", "NO_CACHE": "1", "WAIT_DOCKER": "1"}


@pytest.mark.parametrize("args", [("--no-cache",), ("--build", "extra"), ("--nope",), ("",)])
def test_start_refuses_an_unknown_flag_and_no_cache_without_build(args: tuple[str, ...]) -> None:
    with pytest.raises(invocation.UsageError) as refused:
        invocation.parse_options("start", args)
    assert refused.value.key == "usage"


def test_update_options() -> None:
    assert _options("update") == {"ALLOW_BREAKING": "0"}
    assert _options("update", "--allow-breaking-migration") == {"ALLOW_BREAKING": "1"}
    with pytest.raises(invocation.UsageError):
        invocation.parse_options("update", ("--force",))


@pytest.mark.parametrize(
    ("args", "apply", "reference"),
    [
        ((), "0", ""),
        (("20260101-120000",), "0", "20260101-120000"),
        (("--apply", "20260101-120000"), "1", "20260101-120000"),
        (("20260101-120000", "--apply"), "1", "20260101-120000"),
        (("--apply",), "1", ""),
    ],
)
def test_restore_options(args: tuple[str, ...], apply: str, reference: str) -> None:
    assert _options("restore", *args) == {"APPLY": apply, "REFERENCE": reference}


@pytest.mark.parametrize("args", [("-x",), ("a", "b"), ("--apply", "a", "b")])
def test_restore_refuses_an_option_it_does_not_know_and_a_second_reference(
    args: tuple[str, ...],
) -> None:
    with pytest.raises(invocation.UsageError) as refused:
        invocation.parse_options("restore", args)
    assert refused.value.key == "rs_usage"


@pytest.mark.parametrize("command", ["setup", "init", "start", "stop", "backup", "update"])
def test_the_commands_that_change_the_stack_take_the_lock_under_their_name(command: str) -> None:
    assert invocation.lock_command(command, ["--whatever"]) == command


@pytest.mark.parametrize(
    ("command", "args", "name"),
    [
        ("restore", ["--apply"], "restore --apply"),
        ("restore", ["2026", "--apply"], "restore --apply"),
        ("restore", ["2026"], ""),
        ("status", [], ""),
        ("autostart", ["on"], ""),
        ("claude-config", [], ""),
        ("", [], ""),
        ("nonsense", ["--apply"], ""),
    ],
)
def test_the_other_commands_take_no_lock_except_restore_apply(
    command: str, args: list[str], name: str
) -> None:
    assert invocation.lock_command(command, args) == name


def test_the_api_image_is_the_environment_then_work_env_then_the_default(tmp_path: Path) -> None:
    env_file = tmp_path / "work.env"
    assert invocation.api_image(env_file, {}) == "roadlake-sidekick:work"
    env_file.write_text(
        "SIDEKICK_WORK_API_IMAGE=registry.company.lan/sidekick:1.2\n", encoding="utf-8"
    )
    assert invocation.api_image(env_file, {}) == "registry.company.lan/sidekick:1.2"
    assert invocation.api_image(env_file, {"SIDEKICK_WORK_API_IMAGE": "mine:x"}) == "mine:x"
    assert (
        invocation.api_image(env_file, {"SIDEKICK_WORK_API_IMAGE": ""})
        == "registry.company.lan/sidekick:1.2"
    )


@pytest.mark.parametrize(
    ("image", "tag"),
    [
        ("roadlake-sidekick:work", "roadlake-sidekick:previous"),
        ("roadlake-sidekick", "roadlake-sidekick:previous"),
        ("host:5000/app", "host:5000/app:previous"),
        ("host:5000/app:1.2", "host:5000/app:previous"),
        ("repo/app:1.2@sha256:abc", "repo/app:previous"),
        ("repo/app@sha256:abc", "repo/app:previous"),
    ],
)
def test_the_previous_image_tag_drops_the_tag_and_the_digest(image: str, tag: str) -> None:
    assert stackstate.previous_image_tag(image) == tag


def test_the_database_set_aside_by_a_restore_is_named_after_the_backup_stamp() -> None:
    assert (
        stackstate.old_database_name("20260101-120000") == "sidekick_before_restore_20260101_120000"
    )


def test_claude_desktop_keeps_its_configuration_in_the_platforms_own_place(tmp_path: Path) -> None:
    linux = desktopconfig.claude_config_target("Linux", "", tmp_path)
    assert linux == tmp_path / ".config" / "Claude" / "claude_desktop_config.json"
    mac = desktopconfig.claude_config_target("Darwin", "", tmp_path)
    assert (
        mac
        == tmp_path / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    )
    assert desktopconfig.claude_config_target("Darwin", "/x/own.json", tmp_path) == Path(
        "/x/own.json"
    )


def test_parse_args_prints_name_value_lines(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["parse-args", "--", "start", "--build", "--no-cache"]) == 0
    assert capsys.readouterr().out == "BUILD=1\nNO_CACHE=1\nWAIT_DOCKER=0\n"


@pytest.mark.parametrize(
    ("lang", "command", "args", "text"),
    [
        ("en", "start", ["--no-cache"], "Usage"),
        ("sv", "restore", ["-x"], "restore"),
    ],
)
def test_parse_args_refuses_with_the_usage_text_on_stderr_and_exit_2(
    capsys: pytest.CaptureFixture[str], lang: str, command: str, args: list[str], text: str
) -> None:
    assert cli.main(["parse-args", "--lang", lang, "--", command, *args]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert text.lower() in captured.err.lower()


def test_the_small_commands_print_one_answer(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert cli.main(["lock-command", "--", "restore", "--apply"]) == 0
    assert capsys.readouterr().out == "restore --apply\n"
    assert cli.main(["previous-image-tag", "--", "a/b:1"]) == 0
    assert capsys.readouterr().out == "a/b:previous\n"
    assert cli.main(["restore-old-name", "--", "20260101-120000"]) == 0
    assert capsys.readouterr().out == "sidekick_before_restore_20260101_120000\n"
    monkeypatch.delenv("SIDEKICK_WORK_API_IMAGE", raising=False)
    capsys.readouterr()
    assert cli.main(["api-image", "--env-file", str(tmp_path / "none.env")]) == 0
    assert capsys.readouterr().out == "roadlake-sidekick:work\n"
