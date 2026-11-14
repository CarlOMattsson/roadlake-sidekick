"""The encryption stage of the real ``Stack``: a plain container of the api image."""

from pathlib import Path

from tools.workctl.stack import KEY_VARIABLE, Stack

KEY = "B" * 43 + "="


def _stack(tmp_path: Path, environ: dict[str, str]) -> Stack:
    stack = Stack(tmp_path, project="p", lang="en", memory=True, environ=environ)
    stack.secrets.mkdir(parents=True)
    stack.selfhost.mkdir(parents=True)
    stack.backup_key_file.write_text(KEY + "\n", encoding="ascii")
    (stack.selfhost / "snapshot_crypto.py").write_text("print('crypto')\n", encoding="utf-8")
    stack.work_env.write_text(
        "SIDEKICK_WORK_API_IMAGE=registry.example/sidekick:1\n", encoding="utf-8"
    )
    return stack


def test_the_stage_runs_in_a_container_that_does_not_depend_on_the_api_service(
    tmp_path: Path,
) -> None:
    # The api service has a fixed address on its network: a one-off copy of it fails to start while
    # the api runs, which is the state of a restore's check of the backup set.
    stage = _stack(tmp_path, {}).crypto("decrypt")
    assert stage is not None
    assert stage.argv[:3] == ["docker", "run", "--rm"]
    assert "compose" not in stage.argv
    assert stage.argv[stage.argv.index("--network") + 1] == "none"
    assert stage.argv[stage.argv.index("--entrypoint") + 1] == "python"
    assert stage.argv[-5:] == [
        "registry.example/sidekick:1",
        "-I",
        "-c",
        "print('crypto')",
        "decrypt",
    ]


def test_the_key_reaches_the_container_through_the_environment_only(tmp_path: Path) -> None:
    stage = _stack(tmp_path, {}).crypto("encrypt")
    assert stage is not None
    assert stage.argv[stage.argv.index("-e") + 1] == KEY_VARIABLE
    assert not any(KEY in argument for argument in stage.argv)
    assert stage.env[KEY_VARIABLE] == KEY


def test_the_image_of_the_environment_wins_over_work_env(tmp_path: Path) -> None:
    stage = _stack(tmp_path, {"SIDEKICK_WORK_API_IMAGE": "other/image:2"}).crypto("decrypt")
    assert stage is not None
    assert "other/image:2" in stage.argv
    assert "registry.example/sidekick:1" not in stage.argv


def test_without_a_key_there_is_no_stage(tmp_path: Path) -> None:
    stack = _stack(tmp_path, {})
    stack.backup_key_file.write_text("\n", encoding="ascii")
    assert stack.crypto("decrypt") is None
