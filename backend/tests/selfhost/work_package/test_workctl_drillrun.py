"""The drill's sequence (tools/workctl/drillrun.py and its scenarios) against a stand-in host: the
options, the steps and what each failure does, the summary and the cleanup, without docker and
without starting a program."""

import os
import re
import signal
from pathlib import Path

import pytest
from tools.workctl import drillpolicy, drillrun
from tools.workctl.drillrun import Options, Refused, Usage

from tests.selfhost.work_package.fakehost import FakeHost, Healthy
from tests.selfhost.work_package.support import REPO_ROOT

DIGEST_FROM = "registry.example/sidekick@sha256:" + "a" * 64
DIGEST_TO = "registry.example/sidekick@sha256:" + "b" * 64
PINNED = ["--from-image", DIGEST_FROM, "--to-image", DIGEST_TO, "--cert-identity", "signer"]
SELFHOST_STEPS = [
    "install",
    "marker",
    "update",
    "verify-updated",
    "backup",
    "destroy-volumes",
    "key-fails-closed",
    "restore",
    "verify-restored",
]
WORK_STEPS = [
    "install",
    "marker",
    "update",
    "verify-updated",
    "backup",
    "destroy-volumes",
    "fresh-stack",
    "key-fails-closed",
    "restore",
    "verify-restored",
]


def options(*args: str, **environ: str) -> Options:
    return drillrun.parse_options(args, environ)


# -- the options ---


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["bogus"],
        ["selfhost", "--nonsense"],
        ["selfhost", "--from-image"],
        ["selfhost", "--log"],
        ["selfhost", "--project"],
    ],
)
def test_arguments_that_are_not_understood_print_the_usage(args: list[str]) -> None:
    with pytest.raises(Usage, match="Disposable-container drill"):
        options(*args)


def test_a_pinned_pair_and_a_signer_are_a_complete_selfhost_run() -> None:
    chosen = options("selfhost", *PINNED, "--allow-same-schema", "--log", "/x/log")
    assert (chosen.scenario, chosen.dry, chosen.local_images) == ("selfhost", False, False)
    assert (chosen.from_image, chosen.to_image, chosen.identity) == (
        DIGEST_FROM,
        DIGEST_TO,
        "signer",
    )
    assert chosen.allow_same_schema
    assert chosen.log == Path("/x/log")
    assert re.fullmatch(r"sk-drill-[0-9a-f]{8}", chosen.base_project)


def test_the_environment_supplies_what_an_option_does_not() -> None:
    chosen = options(
        "work",
        DRILL_FROM_IMAGE=DIGEST_FROM,
        DRILL_TO_IMAGE=DIGEST_TO,
        DRILL_CERT_IDENTITY="env-signer",
    )
    assert (chosen.from_image, chosen.to_image, chosen.identity) == (
        DIGEST_FROM,
        DIGEST_TO,
        "env-signer",
    )
    assert options("selfhost", *PINNED, DRILL_CERT_IDENTITY="env-signer").identity == "signer"


def test_a_dry_run_needs_no_images_and_no_signer() -> None:
    for chosen in (options("all", "--dry-run"), options("all", DRILL_FAKE_DOCKER="1")):
        assert chosen.dry
        assert chosen.from_image.endswith("a" * 64) and chosen.to_image.endswith("b" * 64)
        assert chosen.identity == "drill@example.invalid"


def test_local_images_stand_in_for_the_pair_and_accept_an_unmoved_schema() -> None:
    chosen = options("all", "--local-images")
    assert chosen.local_images and chosen.allow_same_schema
    assert chosen.identity == "drill@example.invalid"
    assert options("selfhost", "--local-images", "--cert-identity", "me").identity == "me"


@pytest.mark.parametrize(
    "extra", [["--dry-run"], ["--from-image", DIGEST_FROM], ["--to-image", DIGEST_TO]]
)
def test_local_images_cannot_be_combined_with_a_fake_docker_or_given_images(
    extra: list[str],
) -> None:
    with pytest.raises(Refused, match="--local-images builds and runs real images"):
        options("all", "--local-images", *extra)


@pytest.mark.parametrize(
    "args",
    [
        ["selfhost"],
        ["selfhost", "--from-image", DIGEST_FROM],
        ["selfhost", "--from-image", "registry.example/sidekick:1.0", "--to-image", DIGEST_TO],
        ["selfhost", "--from-image", DIGEST_FROM, "--to-image", DIGEST_FROM],
        ["selfhost", "--from-image", DIGEST_FROM, "--to-image", DIGEST_TO],
    ],
)
def test_a_real_run_refuses_missing_unpinned_or_equal_images_and_a_missing_signer(
    args: list[str],
) -> None:
    with pytest.raises(Refused):
        options(*args)


def test_the_work_package_needs_no_signer() -> None:
    assert options("work", "--from-image", DIGEST_FROM, "--to-image", DIGEST_TO).identity == ""


@pytest.mark.parametrize("name", ["evil", "my-drill-x", "SK-DRILL-x", "sk-drill-", "sk-drill-../x"])
def test_a_project_name_without_the_drill_prefix_is_refused(name: str) -> None:
    with pytest.raises(Refused, match="must start with sk-drill-"):
        options("all", "--dry-run", "--project", name)


def test_main_exits_2_for_a_malformed_reserved_ports_value_before_anything_is_made(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    environ = {"SIDEKICK_RESERVED_PORTS": "9000\n9001", "TMPDIR": str(tmp_path)}
    assert drillrun.main(["selfhost", "--dry-run"], environ) == 2
    assert "SIDEKICK_RESERVED_PORTS" in capsys.readouterr().err
    assert not list(tmp_path.iterdir())


def test_main_prints_the_usage_and_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert drillrun.main(["bogus"], {}) == 2
    assert capsys.readouterr().err.startswith("Disposable-container drill")


# -- a run ---


class Result:
    def __init__(
        self, code: int, out: str, err: str, host: FakeHost, tmp_root: Path, log: Path
    ) -> None:
        self.code = code
        self.out = out
        self.err = err
        self.host = host
        self.tmp_root = tmp_root
        self.log = log.read_text() if log.exists() else ""


def drill(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    *args: str,
    answer: object | None = None,
    **environ: str,
) -> Result:
    tmp_root = tmp_path / "tmp"
    tmp_root.mkdir(exist_ok=True)
    log = tmp_path / "drill.log"
    host = FakeHost(answer if answer is not None else Healthy())  # type: ignore[arg-type]
    env = {"PATH": os.environ["PATH"], "TMPDIR": str(tmp_root), **environ}
    chosen = drillrun.parse_options([*args, "--log", str(log)], env)
    code = drillrun.Drill(chosen, environ=env, host=host, repo=REPO_ROOT).run()
    captured = capsys.readouterr()
    return Result(code, captured.out, captured.err, host, tmp_root, log)


def with_fault(*faults: str) -> Healthy:
    return Healthy(*faults)


def statuses(result: Result, scenario: str) -> dict[str, str]:
    found = re.findall(rf"^(PASS|FAIL) {scenario}/(\S+) ", result.out, re.M)
    return {name: status for status, name in found}


def test_both_scenarios_pass_every_step_in_order_and_the_summary_and_timings_follow(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = drill(tmp_path, capsys, "all", "--dry-run")
    assert result.code == 0, result.out + result.err
    assert list(statuses(result, "selfhost")) == SELFHOST_STEPS
    assert list(statuses(result, "work")) == WORK_STEPS
    assert set(statuses(result, "selfhost").values()) | set(statuses(result, "work").values()) == {
        "PASS"
    }
    assert "SUMMARY: PASS (19 steps; scenarios: selfhost work)" in result.out
    table = result.out.split("TIMINGS (seconds):", 1)[1]
    assert re.findall(r"^  (PASS) (\S+) (\d+)$", table, re.M)[0] == (
        "PASS",
        "selfhost/install",
        "1",
    )
    assert re.search(r"^  total 19$", table, re.M)
    assert result.out.index("SUMMARY") < result.out.index("TIMINGS")
    assert "--- selfhost/install (exit 0, 1s)" in result.log
    assert "installed " + DIGEST_FROM in result.log
    assert "schema moved: 10 -> 12 migrations (0010_head -> 0012_head)" in result.log


def test_each_scenario_gets_its_own_project_and_a_random_port_that_is_never_reserved(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = drill(tmp_path, capsys, "all", "--dry-run", "--project", "sk-drill-t1")
    assert re.findall(r"^(selfhost|work): project (\S+),", result.out, re.M) == [
        ("selfhost", "sk-drill-t1-sh"),
        ("work", "sk-drill-t1-wk"),
    ]
    assert "reserved ports: 55432 55433 55434 55436 8100 8101" in result.out
    assert "api on 127.0.0.1:30001" in result.out and "gateway on 127.0.0.1:30002" in result.out
    projects = {
        call.split()[call.split().index("-p") + 1]
        for call in result.host.calls
        if call.startswith("docker compose -p ")
    }
    assert projects == {"sk-drill-t1-sh", "sk-drill-t1-wk"}


def test_extra_reserved_ports_are_added_to_the_default_ones(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    environ = {
        "PATH": os.environ["PATH"],
        "TMPDIR": str(tmp_path),
        "SIDEKICK_RESERVED_PORTS": " 030000, 9000",
    }
    monkeypatch.setattr(drillrun, "Host", FakeHost)
    assert drillrun.main(["selfhost", "--dry-run", "--log", str(tmp_path / "log")], environ) == 1
    assert "reserved ports: 55432 55433 55434 55436 8100 8101 30000 9000" in capsys.readouterr().out


def test_the_self_hosted_backup_stops_hindsight_for_the_copy_and_starts_it_again(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = drill(tmp_path, capsys, "selfhost", "--dry-run")
    calls = result.host.calls
    stop = next(i for i, call in enumerate(calls) if call.endswith(" stop hindsight"))
    tar = next(i for i, call in enumerate(calls) if "--entrypoint tar" in call)
    start = next(
        i
        for i, call in enumerate(calls[tar:], tar)
        if " up " in call and call.endswith("hindsight")
    )
    assert stop < tar < start
    assert all("--profile memory" in call for call in calls if " exec -T postgres" in call)


def test_a_real_run_pulls_both_images_a_dry_run_pulls_none(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dry = drill(tmp_path, capsys, "work", "--dry-run")
    assert not [call for call in dry.host.calls if call.startswith("docker pull")]
    (tmp_path / "real").mkdir()
    real = drill(tmp_path / "real", capsys, "work", *PINNED)
    pulls = [call for call in real.host.calls if call.startswith("docker pull")]
    assert pulls == [f"docker pull {DIGEST_FROM}", f"docker pull {DIGEST_TO}"]


@pytest.mark.parametrize(
    ("fault", "scenario", "failed", "message"),
    [
        ("lose-marker", "selfhost", "marker", "marker row"),
        ("no-schema-move", "selfhost", "verify-updated", "schema did not move"),
        ("wrong-key-accepted", "selfhost", "key-fails-closed", "a wrong key decrypted the backup"),
        ("lose-hindsight", "selfhost", "verify-restored", "Hindsight volume file after restore"),
        ("wrong-key-accepted", "work", "key-fails-closed", "restore accepted a wrong key"),
        ("lose-hindsight", "work", "verify-restored", "Hindsight volume file after restore"),
    ],
)
def test_a_misbehaving_stack_fails_that_step_and_the_ones_after_it_do_not_run(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fault: str,
    scenario: str,
    failed: str,
    message: str,
) -> None:
    result = drill(tmp_path, capsys, scenario, "--dry-run", answer=with_fault(fault))
    assert result.code == 1
    steps = list(statuses(result, scenario).items())
    assert steps[-1] == (failed, "FAIL")
    assert {status for _, status in steps[:-1]} == {"PASS"}
    assert message in result.out
    assert f"SUMMARY: FAIL (failed scenarios: {scenario}; passed: none)" in result.out
    assert f"FAIL {scenario}/{failed} (exit 1, 1s)" in result.out


def test_a_failing_scenario_does_not_stop_the_other_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    healthy = Healthy()

    def answer(call: str, stdin: bytes | None, env: dict[str, str]) -> object:
        return 1 if "sidekick-admin" in call else healthy(call, stdin, env)

    result = drill(tmp_path, capsys, "all", "--dry-run", answer=answer)
    assert result.code == 1
    assert statuses(result, "selfhost") == {"install": "FAIL"}
    assert set(statuses(result, "work").values()) == {"PASS"}
    assert "failed scenarios: selfhost; passed: work" in result.out


def test_an_unmoved_schema_passes_only_when_it_is_allowed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = drill(
        tmp_path,
        capsys,
        "all",
        "--dry-run",
        "--allow-same-schema",
        answer=with_fault("no-schema-move"),
    )
    assert result.code == 0, result.out
    assert result.log.count("accepted by --allow-same-schema") == 2


def test_a_failed_step_is_annotated_and_the_timings_go_to_the_job_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    summary = tmp_path / "summary.md"
    result = drill(
        tmp_path,
        capsys,
        "selfhost",
        "--dry-run",
        answer=with_fault("lose-marker"),
        GITHUB_ACTIONS="true",
        GITHUB_STEP_SUMMARY=str(summary),
    )
    assert (
        "::error title=drill selfhost/marker failed::exit 1 after 1s, see the drill log artifact"
        in result.out
    )
    table = summary.read_text()
    assert table.startswith("### Drill steps")
    assert "| selfhost/install | PASS | 1 |" in table and "| selfhost/marker | FAIL | 1 |" in table


def test_no_annotation_outside_github_actions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = drill(tmp_path, capsys, "selfhost", "--dry-run", answer=with_fault("lose-marker"))
    assert "::error" not in result.out
    assert re.search(r"^    marker row: expected '.+', got ''$", result.out, re.M)


def test_a_failed_program_fails_the_step_with_its_own_status_and_its_error_in_the_log(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    healthy = Healthy()

    def answer(call: str, stdin: bytes | None, env: dict[str, str]) -> object:
        if "create-user" in call:
            return 99
        return healthy(call, stdin, env)

    result = drill(tmp_path, capsys, "selfhost", "--dry-run", answer=answer)
    assert "FAIL selfhost/install (exit 99, 1s)" in result.out
    assert "docker compose exited 99" in result.log and "failed" in result.log
    assert list(statuses(result, "selfhost")) == ["install"]


def test_a_step_that_raises_something_unexpected_fails_that_step(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    healthy = Healthy()

    def answer(call: str, stdin: bytes | None, env: dict[str, str]) -> object:
        if "sidekick-admin" in call:
            raise ValueError("boom")
        return healthy(call, stdin, env)

    result = drill(tmp_path, capsys, "selfhost", "--dry-run", answer=answer)
    assert result.code == 1
    assert "ValueError: boom" in result.log


# -- the cleanup ---


def test_the_cleanup_removes_the_projects_of_the_run_and_the_temp_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = drill(tmp_path, capsys, "all", "--dry-run", "--project", "sk-drill-t2")
    downs = [
        call
        for call in result.host.calls
        if call.endswith(" down -v --remove-orphans") and " -f " not in call
    ]
    # The work scenario's own destroy step runs one too; the cleanup's come last, one per project.
    assert downs[-2:] == [
        "docker compose -p sk-drill-t2-sh down -v --remove-orphans",
        "docker compose -p sk-drill-t2-wk down -v --remove-orphans",
    ]
    assert not list(result.tmp_root.glob("sk-drill.*"))
    assert f"drill: log: {tmp_path / 'drill.log'}" in result.err


def test_the_temp_dir_is_kept_on_request(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = drill(tmp_path, capsys, "selfhost", "--dry-run", DRILL_KEEP_TEMP="1")
    assert re.search(r"drill: temp dir kept: \S+/sk-drill\.\w+", result.err)
    assert len(list(result.tmp_root.glob("sk-drill.*"))) == 1


def test_the_cleanup_removes_leftover_volumes_of_its_projects_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    healthy = Healthy()

    def answer(call: str, stdin: bytes | None, env: dict[str, str]) -> object:
        if call.startswith("docker volume ls -q --filter label=com.docker.compose.project="):
            return "sk-drill-t3-sh_data\nother_data\nsk-drill-t3-shdata\n"
        return healthy(call, stdin, env)

    result = drill(
        tmp_path, capsys, "selfhost", "--dry-run", "--project", "sk-drill-t3", answer=answer
    )
    removed = [call for call in result.host.calls if call.startswith("docker volume rm")]
    assert removed == ["docker volume rm sk-drill-t3-sh_data"] * len(removed)
    assert removed


def test_a_project_that_is_not_a_drill_project_is_never_passed_to_docker(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    host = FakeHost()
    drill_run = drillrun.Drill(
        options("selfhost", "--dry-run", "--log", str(tmp_path / "log")),
        environ={"TMPDIR": str(tmp_path)},
        host=host,
        repo=REPO_ROOT,
    )
    drill_run.tmp = tmp_path
    drill_run.log = tmp_path / "log"
    drill_run.shared = drillrun.Run(
        REPO_ROOT, tmp_path, host, {}, True, DIGEST_FROM, DIGEST_TO, "x", False
    )
    drill_run.projects = ["production", "sk-drill-ok-sh", "sk-drill-"]
    drill_run.cleanup()
    capsys.readouterr()
    assert [call for call in host.calls if "down" in call] == [
        "docker compose -p sk-drill-ok-sh down -v --remove-orphans"
    ]


def test_an_interrupt_ends_the_run_with_130_and_the_cleanup_still_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    healthy = Healthy()
    before = signal.getsignal(signal.SIGTERM)

    def answer(call: str, stdin: bytes | None, env: dict[str, str]) -> object:
        if "sidekick-admin" in call:
            os.kill(os.getpid(), signal.SIGINT)
        return healthy(call, stdin, env)

    result = drill(
        tmp_path, capsys, "selfhost", "--dry-run", "--project", "sk-drill-t4", answer=answer
    )
    assert result.code == 130
    assert "docker compose -p sk-drill-t4-sh down -v --remove-orphans" in result.host.calls
    assert not list(result.tmp_root.glob("sk-drill.*"))
    assert signal.getsignal(signal.SIGTERM) == before


# -- a real run's own checks ---


@pytest.fixture(name="installed")
def _installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(drillrun.shutil, "which", lambda name, path=None: f"/bin/{name}")


@pytest.mark.parametrize(
    ("missing", "message"),
    [
        ("docker", "drill: docker is required"),
        ("cosign", "drill: cosign is required (update.sh verifies the signature, fail closed)"),
    ],
)
def test_a_missing_tool_stops_a_real_run_with_exit_2_before_anything_starts(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    missing: str,
    message: str,
) -> None:
    monkeypatch.setattr(
        drillrun.shutil,
        "which",
        lambda name, path=None: None if name == missing else f"/bin/{name}",
    )
    result = drill(tmp_path, capsys, "selfhost", *PINNED)
    assert result.code == 2
    assert message in result.err
    assert result.host.calls == []
    assert not list(result.tmp_root.glob("sk-drill.*"))


def test_the_work_package_needs_openssl_and_no_cosign(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        drillrun.shutil,
        "which",
        lambda name, path=None: None if name == "cosign" else f"/bin/{name}",
    )
    assert drill(tmp_path, capsys, "work", *PINNED).code == 0
    monkeypatch.setattr(
        drillrun.shutil,
        "which",
        lambda name, path=None: None if name == "openssl" else f"/bin/{name}",
    )
    (tmp_path / "again").mkdir()
    result = drill(tmp_path / "again", capsys, "work", *PINNED)
    assert result.code == 2
    assert "drill: openssl is required (tools/work.sh)" in result.err


def test_docker_compose_v2_is_required(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], installed: None
) -> None:
    result = drill(
        tmp_path,
        capsys,
        "work",
        *PINNED,
        answer=lambda call, _stdin, _env: 1 if "compose version" in call else None,
    )
    assert result.code == 2
    assert "drill: docker compose v2 is required" in result.err


def test_without_a_free_port_the_run_ends_with_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tmp_root = tmp_path / "tmp"
    tmp_root.mkdir()
    host = FakeHost()
    host.ports = iter(())
    env = {"PATH": os.environ["PATH"], "TMPDIR": str(tmp_root)}
    chosen = drillrun.parse_options(["work", "--dry-run", "--log", str(tmp_path / "log")], env)
    assert drillrun.Drill(chosen, environ=env, host=host, repo=REPO_ROOT).run() == 1
    assert "drill: no free port found" in capsys.readouterr().err


# -- --local-images ---


def test_local_images_are_built_pushed_and_drilled_with_their_digests(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], installed: None
) -> None:
    result = drill(tmp_path, capsys, "selfhost", "--local-images", "--project", "sk-drill-t5")
    assert result.code == 0, result.out + result.err
    assert "drill: --local-images: the signature is NOT verified" in result.out
    assert statuses(result, "setup") == {"local-images": "PASS"}
    assert "built 127.0.0.1:30001/sidekick:from as version " in result.log
    registry_up = next(
        i
        for i, call in enumerate(result.host.calls)
        if "sk-drill-t5-reg" in call and " up " in call
    )
    first_build = next(
        i for i, call in enumerate(result.host.calls) if call.startswith("docker build")
    )
    assert registry_up < first_build
    digest_from, digest_to = "sha256:" + "1" * 64, "sha256:" + "2" * 64
    assert f"docker pull 127.0.0.1:30001/sidekick@{digest_from}" in result.host.calls
    assert f"docker pull 127.0.0.1:30001/sidekick@{digest_to}" in result.host.calls
    # The fake moves the schema, as a real pair of images would.
    assert "accepted by --allow-same-schema" not in result.log
    # The registry's own project is cleaned up too; each image made is removed by exact reference.
    assert "docker compose -p sk-drill-t5-reg down -v --remove-orphans" in result.host.calls
    removed = [call for call in result.host.calls if call.startswith("docker image rm")]
    assert removed == [
        "docker image rm 127.0.0.1:30001/sidekick:from",
        f"docker image rm 127.0.0.1:30001/sidekick@{digest_from}",
        "docker image rm 127.0.0.1:30001/sidekick:to",
        f"docker image rm 127.0.0.1:30001/sidekick@{digest_to}",
    ]


def test_local_images_use_a_cosign_that_only_checks_the_shape_of_the_call(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], installed: None
) -> None:
    result = drill(
        tmp_path, capsys, "selfhost", "--local-images", "--cert-identity", "me", DRILL_KEEP_TEMP="1"
    )
    assert result.code == 0
    kept = next(result.tmp_root.glob("sk-drill.*")) / "bin" / "cosign"
    text = kept.read_text()
    assert (
        '"${2:-}" = "me"' in text and r"^127\.0\.0\.1:[0-9]+/sidekick@sha256:[0-9a-f]{64}$" in text
    )
    assert kept.stat().st_mode & 0o111


@pytest.mark.parametrize(("fault", "message"), [("no-digest", "no digest from the push of")])
def test_a_build_that_yields_no_digest_stops_the_run_and_the_images_are_still_removed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], installed: None, fault: str, message: str
) -> None:
    result = drill(tmp_path, capsys, "all", "--local-images", answer=with_fault(fault))
    assert result.code == 1
    assert "SUMMARY: FAIL (the local images could not be built)" in result.out
    assert message in result.log
    assert statuses(result, "selfhost") == {}
    assert "docker image rm 127.0.0.1:30001/sidekick:from" in result.host.calls


def test_two_builds_with_one_digest_are_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], installed: None
) -> None:
    healthy = Healthy()

    def answer(call: str, stdin: bytes | None, env: dict[str, str]) -> object:
        if " push " in call:
            return ("digest: sha256:" + "7" * 64 + " size: 1\n").encode()
        return healthy(call, stdin, env)

    result = drill(tmp_path, capsys, "selfhost", "--local-images", answer=answer)
    assert result.code == 1
    assert "both builds have the same digest" in result.log


def test_the_images_the_drill_may_remove_are_the_ones_of_its_own_registry() -> None:
    from tools.workctl import drillimages

    assert drillimages.is_local_reference("127.0.0.1:30001/sidekick:from")
    assert drillimages.is_local_reference("127.0.0.1:30001/sidekick@sha256:" + "a" * 64)
    for other in (
        "sidekick:from",
        "127.0.0.1:30001/other:from",
        "ghcr.io/x/sidekick@sha256:" + "a" * 64,
        "127.0.0.1:1/sidekick;rm",
    ):
        assert not drillimages.is_local_reference(other)


def test_the_reserved_ports_are_never_picked(monkeypatch: pytest.MonkeyPatch) -> None:
    picked = iter([55432, 20001])
    monkeypatch.setattr(drillpolicy.random, "randint", lambda *_range: next(picked))
    assert drillpolicy.pick_port(drillpolicy.RESERVED_PORTS, [], lambda _port: False) == 20001
