"""tools/drill_fake_docker.py: the fake docker of the dry-run drill, as update.sh calls it."""

import io
import json
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from tools import drill_fake_docker as fake

FROM = "registry.example/sidekick@sha256:" + "a" * 64
TO = "registry.example/sidekick@sha256:" + "b" * 64
PROJECT = "sk-drill-0123abcd-sh"

Call = Callable[..., tuple[int, str, str]]


@pytest.fixture
def call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> Call:
    """Run one call of the fake docker on a state file in ``tmp_path``: (status, stdout, stderr)."""

    def run(
        *argv: str,
        stdin: bytes = b"",
        fail: str = "",
        environ: dict[str, str] | None = None,
    ) -> tuple[int, str, str]:
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(stdin), encoding="utf-8"))
        capsys.readouterr()
        values = {
            "DRILL_FAKE_STATE": str(tmp_path / "state.json"),
            "DRILL_FAKE_LOG": str(tmp_path / "calls.log"),
            "DRILL_FAKE_FROM": FROM,
            "DRILL_FAKE_TO": TO,
            "DRILL_FAKE_FAIL": fail,
            **(environ or {}),
        }
        status = fake.FakeDocker.from_environ(values).run(argv)
        captured = capsys.readouterr()
        return status, captured.out, captured.err

    return run


def state_of(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))


def compose(*args: str, project: str = PROJECT) -> tuple[str, ...]:
    return ("compose", "-p", project, *args)


def test_every_call_is_logged_with_long_arguments_shortened(call: Call, tmp_path: Path) -> None:
    call("ps", "x" * 200)
    logged = [json.loads(line) for line in (tmp_path / "calls.log").read_text().splitlines()]
    assert logged == [{"argv": ["ps", "<200 chars>"]}]


def test_no_arguments_is_a_quiet_success(call: Call) -> None:
    assert call() == (0, "", "")


def test_a_project_that_is_not_a_drill_project_is_refused_with_99(call: Call) -> None:
    status, _, err = call(*compose("up", "-d", project="production"))
    assert status == 99
    assert "refusing project production" in err


def test_up_starts_the_default_services_and_the_api_moves_the_schema(
    call: Call, tmp_path: Path
) -> None:
    status, _, _ = call(*compose("up", "-d"), environ={"SIDEKICK_API_IMAGE": FROM})
    assert status == 0
    state = state_of(tmp_path)
    assert set(state["running"]) == {"postgres", "api", "automation-worker"}
    assert state["schema"] == fake.FROM_SCHEMA
    assert state["image"] == FROM
    call(*compose("up", "-d", "api"), environ={"SIDEKICK_API_IMAGE": TO})
    assert state_of(tmp_path)["schema"] == fake.TO_SCHEMA


def test_a_fake_failure_keeps_the_schema_where_it_was(call: Call, tmp_path: Path) -> None:
    call(*compose("up", "-d", "api"), environ={"SIDEKICK_API_IMAGE": TO}, fail="no-schema-move")
    assert state_of(tmp_path)["schema"] == fake.FROM_SCHEMA


def test_the_image_can_come_from_an_env_file(call: Call, tmp_path: Path) -> None:
    env_file = tmp_path / "stack.env"
    env_file.write_text(f"OTHER=1\nSIDEKICK_API_IMAGE={TO}\n", encoding="utf-8")
    call(*compose("--env-file", str(env_file), "up", "-d", "api"))
    assert state_of(tmp_path)["image"] == TO


def test_the_memory_profile_adds_hindsight_and_its_volume(call: Call, tmp_path: Path) -> None:
    call(*compose("--profile", "memory", "up", "-d"))
    state = state_of(tmp_path)
    assert {"memory-worker", "hindsight"} <= set(state["running"])
    assert list(state["volumes"]) == [PROJECT + "_hindsight_pg0"]
    status, out, _ = call(
        "volume", "ls", "-q", "--filter", f"label=com.docker.compose.project={PROJECT}"
    )
    assert (status, out) == (0, PROJECT + "_hindsight_pg0\n")


def test_ps_and_stop_follow_the_running_services(call: Call, tmp_path: Path) -> None:
    call(*compose("up", "-d"))
    assert call(*compose("ps", "-q", "api"))[1] == "cid-api\n"
    call(*compose("stop", "api"))
    assert state_of(tmp_path)["running"]["api"] is False
    assert call(*compose("ps", "-q", "api"))[1] == ""
    assert call("inspect", "-f", "{{.State.Health}}", "cid-api")[1] == "exited none\n"
    assert call("inspect", "-f", "{{.State.Status}}", "cid-postgres")[1] == "running no\n"


def test_down_forgets_everything(call: Call, tmp_path: Path) -> None:
    call(*compose("--profile", "memory", "up", "-d"))
    call(*compose("down", "-v", "--remove-orphans"))
    state = state_of(tmp_path)
    assert state["running"] == {} and state["volumes"] == {} and state["schema"] == 0


def test_the_marker_row_survives_a_dump_and_a_restore(call: Call) -> None:
    call(*compose("up", "-d"))
    sql = (
        "CREATE TABLE public.drill_marker (t int); INSERT INTO public.drill_marker VALUES ('tok-1')"
    )
    call(*compose("exec", "-T", "postgres", "psql", "-c", sql))
    assert (
        call(
            *compose(
                "exec", "-T", "postgres", "psql", "-c", "select token from public.drill_marker"
            )
        )[1]
        == "tok-1\n"
    )
    dump = call(*compose("exec", "-T", "postgres", "pg_dump"))[1]
    assert dump.splitlines()[:2] == ["MARKER=tok-1", "SCHEMA=0"]
    call(*compose("down", "-v"))
    call(*compose("up", "-d"))
    status, _, err = call(
        *compose("exec", "-T", "postgres", "psql", "-c", "select token from public.drill_marker")
    )
    assert status == 1 and "drill_marker" in err
    call(*compose("exec", "-T", "postgres", "psql", "--single-transaction"), stdin=dump.encode())
    assert (
        call(
            *compose(
                "exec", "-T", "postgres", "psql", "-c", "select token from public.drill_marker"
            )
        )[1]
        == "tok-1\n"
    )


def test_pg_restore_lists_the_table_only_when_the_dump_has_a_marker(call: Call) -> None:
    def listing(data: bytes) -> str:
        return call(*compose("exec", "-T", "postgres", "pg_restore", "-l"), stdin=data)[1]

    assert listing(b"MARKER=tok\nSCHEMA=1\n") == "TABLE public drill_marker\n"
    assert listing(b"MARKER=\nSCHEMA=1\n") == ""


def test_the_lose_marker_failure_never_stores_the_marker(call: Call) -> None:
    sql = (
        "CREATE TABLE public.drill_marker (t text); INSERT INTO public.drill_marker VALUES ('tok');"
    )
    call(*compose("exec", "-T", "postgres", "psql", "-c", sql), fail="lose-marker")
    assert (
        call(*compose("exec", "-T", "postgres", "psql", "-c", "select * from public.drill_marker"))[
            0
        ]
        == 1
    )


def test_the_schema_queries_answer_from_the_state(call: Call) -> None:
    call(*compose("up", "-d", "api"), environ={"SIDEKICK_API_IMAGE": TO})
    count = call(
        *compose("exec", "-T", "postgres", "psql", "-c", "select count(*) from _yoyo_migration")
    )
    head = call(
        *compose("exec", "-T", "postgres", "psql", "-c", "select migration_id from _yoyo_migration")
    )
    assert (count[1], head[1]) == ("12\n", "012_head\n")


def test_the_user_is_created_once_and_counted(call: Call) -> None:
    count = ("psql", "-c", "select count(*) from sidekick.users where username = 'jobb'")
    assert call(*compose("exec", "-T", "api", *count))[1] == "0\n"
    created = call(*compose("exec", "-T", "api", "sidekick-admin", "create-user", "jobb"))[1]
    assert created == fake.USER_ID + "\n"
    assert call(*compose("exec", "-T", "api", *count))[1] == "1\n"


def run_crypto(  # the backup crypto as update.sh runs it: key from the environment
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    data: bytes,
    mode: str,
    key: str,
    fail: str = "",
) -> tuple[int, bytes, str]:
    stdout = io.BytesIO()
    stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(data), encoding="utf-8"))
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(stdout, encoding="utf-8"))
    monkeypatch.setattr(sys, "stderr", stderr)
    environ = {
        "DRILL_FAKE_STATE": str(tmp_path / "state.json"),
        "DRILL_FAKE_LOG": str(tmp_path / "calls.log"),
        "DRILL_FAKE_FROM": FROM,
        "DRILL_FAKE_TO": TO,
        "DRILL_FAKE_FAIL": fail,
        "SIDEKICK_BACKUP_ENCRYPTION_KEY": key,
    }
    status = fake.FakeDocker.from_environ(environ).run(
        (
            *compose("run", "--rm", "-T", "-e", "SIDEKICK_BACKUP_ENCRYPTION_KEY", "api"),
            "python",
            "-I",
            "-c",
            "code",
            mode,
        )
    )
    sys.stdout.flush()
    return status, stdout.getvalue(), stderr.getvalue()


def test_the_backup_crypto_round_trips_with_the_same_key_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    status, sealed, _ = run_crypto(tmp_path, monkeypatch, b"payload", "encrypt", "key-one")
    assert status == 0 and sealed.startswith(fake.MAGIC)
    assert run_crypto(tmp_path, monkeypatch, sealed, "decrypt", "key-one")[1] == b"payload"
    status, _, err = run_crypto(tmp_path, monkeypatch, sealed, "decrypt", "key-two")
    assert status == 1 and "InvalidToken" in err
    status, plain, _ = run_crypto(
        tmp_path, monkeypatch, sealed, "decrypt", "key-two", "wrong-key-accepted"
    )
    assert (status, plain) == (0, b"payload")


def test_the_backup_crypto_refuses_nothing_to_encrypt_and_unsealed_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert run_crypto(tmp_path, monkeypatch, b"", "encrypt", "k")[0] == 1
    status, _, err = run_crypto(tmp_path, monkeypatch, b"plain", "decrypt", "k")
    assert status == 1 and "decrypt failed" in err


def test_hindsight_files_move_through_the_volume_carrier(call: Call, tmp_path: Path) -> None:
    call(*compose("--profile", "memory", "up", "-d"))
    volume = PROJECT + "_hindsight_pg0"
    write = (
        "run",
        "--rm",
        "--network",
        "none",
        "-v",
        f"{volume}:/dst",
        "--entrypoint",
        "sh",
        "img",
        "-c",
    )
    call(*write, "printf '%s' 'tok-9' > /dst/drill-marker.txt")
    read = (
        "run",
        "--rm",
        "--network",
        "none",
        "-v",
        f"{volume}:/src:ro",
        "--entrypoint",
        "cat",
        "img",
    )
    assert call(*read, "/src/drill-marker.txt")[1] == "tok-9"
    assert call(*read, "/src/missing.txt")[0] == 1
    # tar out and extract in again, into a volume that lost its files
    packed = fake.tar_of(state_of(tmp_path)["volumes"][volume]["files"])
    call(*write, "tar -C /dst -xzf -", stdin=packed, fail="lose-hindsight")
    assert call(*read, "/src/drill-marker.txt")[0] == 1


def test_a_volume_that_is_not_a_drill_volume_is_refused_with_99(call: Call) -> None:
    status, _, err = call(
        "run", "--rm", "-v", "production_data:/src:ro", "--entrypoint", "cat", "img", "/src/x"
    )
    assert status == 99 and "refusing volume production_data" in err
    assert call("volume", "create", "production_data")[0] == 99
    assert call("volume", "rm", "production_data")[0] == 99
    assert call("ps", "-q", "--filter", "label=com.docker.compose.project=production")[0] == 99


def test_a_missing_volume_is_reported(call: Call) -> None:
    status, _, err = call(
        "run", "--rm", "-v", "sk-drill-none:/src", "--entrypoint", "cat", "img", "/src/x"
    )
    assert (status, err) == (1, "no such volume\n")


def test_volumes_are_created_with_their_labels(call: Call, tmp_path: Path) -> None:
    call("volume", "create", "--label", "com.docker.compose.project=sk-drill-x", "sk-drill-x_data")
    assert state_of(tmp_path)["volumes"] == {
        "sk-drill-x_data": {"com.docker.compose.project": "sk-drill-x"}
    }
    call("volume", "rm", "sk-drill-x_data")
    assert state_of(tmp_path)["volumes"] == {}


def test_image_inspect_answers_the_release_facts(call: Call) -> None:
    def inspect(fmt: str, ref: str) -> str:
        return call("image", "inspect", "-f", fmt, ref)[1]

    assert inspect('{{index .Config.Labels "min-upgrade-from"}}', TO) == "0.1.0\n"
    assert inspect("image.version", TO) == "0.2.0\n"
    assert inspect("image.version", FROM) == "0.1.0\n"
    assert inspect("migration-class", TO) == "expand\n"


def test_compose_config_lists_the_images(call: Call) -> None:
    out = call(*compose("config", "--images"))[1].splitlines()
    assert out[0] == "postgres:18.4-alpine"
    assert out[1].startswith("ghcr.io/vectorize-io/hindsight@sha256:")


def test_services_of_skips_flags_and_their_values() -> None:
    assert fake.services_of(
        ["-d", "--wait-timeout", "120", "api", "--pull", "never", "postgres"]
    ) == ["api", "postgres"]
