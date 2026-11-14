"""tools/drill.sh in dry-run mode: a fake docker, so no container is started.

The drill installs, updates, backs up, destroys and restores a throw-away stack, for the self-hosted
installation (deploy/selfhost/update.sh) and for the work package (tools/work.sh). These tests run
the real scripts against the fake docker the drill writes into its own temp dir and read the log of
every docker call: the project names, the ports, what is removed at the end and what happens when a
step goes wrong.
"""

import json
import os
import re
import shutil
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
DRILL = REPO_ROOT / "tools" / "drill.sh"
RESERVED_PORTS = {55432, 55433, 55434, 55436, 8100, 8101}
DIGEST_FROM = "registry.example/sidekick@sha256:" + "a" * 64
DIGEST_TO = "registry.example/sidekick@sha256:" + "b" * 64


@dataclass
class Result:
    process: subprocess.CompletedProcess[str]
    calls: list[list[str]]
    log_text: str
    tmp_root: Path
    kept_dir: Path | None

    @property
    def stdout(self) -> str:
        return self.process.stdout

    @property
    def projects(self) -> set[str]:
        return set(re.findall(r"\bsk-drill-[a-z0-9-]+", self.stdout))


def run_drill(tmp_path: Path, *args: str, keep: bool = False, **env: str) -> Result:
    tmp_root = tmp_path / "tmp"
    tmp_root.mkdir(exist_ok=True)
    calls_file = tmp_path / "calls.log"
    log_file = tmp_path / "drill.log"
    inherited = {
        name: value
        for name, value in os.environ.items()
        if name
        not in {
            "DRILL_FROM_IMAGE",
            "DRILL_TO_IMAGE",
            "DRILL_CERT_IDENTITY",
            "DRILL_FAKE_DOCKER",
            "DRILL_FAKE_FAIL",
            "GITHUB_ACTIONS",
            "GITHUB_STEP_SUMMARY",
        }
    }
    environment = {
        **inherited,
        "TMPDIR": str(tmp_root),
        "DRILL_FAKE_LOG": str(calls_file),
        "DRILL_KEEP_TEMP": "1" if keep else "",
        **env,
    }
    process = subprocess.run(
        ["bash", str(DRILL), *args, "--log", str(log_file)],
        env=environment,
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )
    calls = (
        [json.loads(line)["argv"] for line in calls_file.read_text().splitlines()]
        if calls_file.exists()
        else []
    )
    kept = re.search(r"temp dir kept: (\S+)", process.stderr)
    return Result(
        process=process,
        calls=calls,
        log_text=log_file.read_text() if log_file.exists() else "",
        tmp_root=tmp_root,
        kept_dir=Path(kept.group(1)) if kept else None,
    )


def compose_project(argv: list[str]) -> str | None:
    if argv[:1] != ["compose"] or "-p" not in argv:
        return None
    return argv[argv.index("-p") + 1]


@pytest.fixture(scope="module", name="passing")
def _passing(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Result]:
    """One full dry run of both scenarios; the temp dir is kept so generated files can be read."""

    result = run_drill(tmp_path_factory.mktemp("drill"), "all", "--dry-run", keep=True)
    yield result
    if result.kept_dir is not None:
        shutil.rmtree(result.kept_dir, ignore_errors=True)


def test_all_dry_run_passes_every_step(passing: Result) -> None:
    assert passing.process.returncode == 0, passing.stdout + passing.process.stderr
    steps = re.findall(r"^(PASS|FAIL) (selfhost|work)/(\S+) \(\d+s\)$", passing.stdout, re.M)
    assert {status for status, _, _ in steps} == {"PASS"}
    names = {(scenario, name) for _, scenario, name in steps}
    for scenario in ("selfhost", "work"):
        for name in (
            "install",
            "marker",
            "update",
            "verify-updated",
            "backup",
            "destroy-volumes",
            "key-fails-closed",
            "restore",
            "verify-restored",
        ):
            assert (scenario, name) in names
    assert "SUMMARY: PASS" in passing.stdout
    assert "PASS selfhost/install" in passing.log_text


def test_every_step_reports_its_duration_and_a_table_follows_the_summary(passing: Result) -> None:
    table = passing.stdout.split("TIMINGS (seconds):", 1)[1]
    rows = re.findall(r"^  (PASS|FAIL) (\S+/\S+) (\d+)$", table, re.M)
    assert len(rows) == 19
    assert re.search(r"^  total \d+$", table, re.M)
    assert passing.stdout.index("SUMMARY: PASS") < passing.stdout.index("TIMINGS (seconds):")


def test_the_self_hosted_drill_runs_the_memory_profile_and_archives_hindsight_as_the_guide_does(
    passing: Result,
) -> None:
    flat = [" ".join(argv) for argv in passing.calls]
    selfhost = [line for line in flat if "-sh " in line and line.startswith("compose")]
    assert any(
        "--profile memory" in line and " up " in line and "hindsight" in line for line in selfhost
    )
    # Compose owns the volume; Hindsight is stopped for the archive, then started.
    assert not [argv for argv in passing.calls if argv[:2] == ["volume", "create"]]
    stop = next(i for i, line in enumerate(flat) if " stop hindsight" in line)
    tar = next(i for i, line in enumerate(flat) if "--entrypoint tar" in line)
    start = next(
        i for i, line in enumerate(flat[tar:], tar) if " up " in line and "hindsight" in line
    )
    assert stop < tar < start
    assert passing.kept_dir is not None
    hindsight_env = (
        passing.kept_dir / "selfhost" / "deploy" / "selfhost" / "hindsight.env"
    ).read_text()
    assert "HINDSIGHT_API_LLM_BASE_URL=http://model.drill.invalid" in hindsight_env


def test_each_scenario_has_its_own_sk_drill_project(passing: Result) -> None:
    assert len(passing.projects) == 2
    assert all(name.startswith("sk-drill-") for name in passing.projects)
    used = {compose_project(argv) for argv in passing.calls} - {None}
    assert used == passing.projects
    suffixes = {name.rsplit("-", 1)[1] for name in passing.projects}
    assert suffixes == {"sh", "wk"}


def test_every_compose_call_names_a_drill_project(passing: Result) -> None:
    compose_calls = [argv for argv in passing.calls if argv[:1] == ["compose"]]
    assert compose_calls
    for argv in compose_calls:
        project = compose_project(argv)
        assert project is not None, argv
        assert project.startswith("sk-drill-"), argv


def test_only_drill_volumes_are_created_removed_or_mounted(passing: Result) -> None:
    touched = []
    for argv in passing.calls:
        if argv[:2] in (["volume", "create"], ["volume", "rm"]):
            touched.append(argv[-1])
        if argv[:1] == ["run"] and "-v" in argv:
            touched.append(argv[argv.index("-v") + 1].split(":")[0])
    assert touched
    assert all(name.startswith("sk-drill-") for name in touched)
    # Nothing is ever asked about the volumes or containers of other projects.
    for argv in passing.calls:
        for item in argv:
            if item.startswith("label=com.docker.compose.project="):
                assert item.split("=", 2)[2].startswith("sk-drill-"), argv


def test_cleanup_runs_down_v_for_the_drill_projects_only(passing: Result) -> None:
    downs = [argv for argv in passing.calls if argv[:1] == ["compose"] and "down" in argv]
    assert downs
    for argv in downs:
        assert "-v" in argv and "--remove-orphans" in argv, argv
        assert compose_project(argv) in passing.projects, argv
    # The cleanup trap's own calls are the bare form: project name only, no compose file.
    cleanup = [argv for argv in downs if "-f" not in argv]
    assert {compose_project(argv) for argv in cleanup} == passing.projects
    # Nothing removes anything else.
    assert not [argv for argv in passing.calls if argv[:2] in (["rm", "-f"], ["system", "prune"])]


def test_ports_are_random_loopback_and_never_forbidden(passing: Result) -> None:
    ports = [int(port) for port in re.findall(r"on 127\.0\.0\.1:(\d+)", passing.stdout)]
    assert len(ports) == 2
    assert len(set(ports)) == 2
    assert not set(ports) & RESERVED_PORTS
    assert all(20000 <= port < 40000 for port in ports)
    assert passing.kept_dir is not None
    override = (
        passing.kept_dir / "selfhost" / "deploy" / "selfhost" / "drill.override.yaml"
    ).read_text()
    published = re.findall(r'"([^"]+):8000"', override)
    assert published == [f"127.0.0.1:{ports[0]}"]


def test_temp_dir_is_removed_by_default(tmp_path: Path) -> None:
    result = run_drill(tmp_path, "selfhost", "--dry-run")
    assert result.process.returncode == 0, result.stdout + result.process.stderr
    assert result.kept_dir is None
    assert not list(result.tmp_root.glob("sk-drill.*"))
    assert len(result.projects) == 1


def drill_sources() -> dict[str, str]:
    """The text of the drill: the shell around it and the modules of its sequence."""
    files = [DRILL, *sorted((REPO_ROOT / "tools" / "workctl").glob("drill*.py"))]
    return {path.name: path.read_text() for path in files}


def test_script_text_has_no_unscoped_removal_and_only_forbids_the_known_ports() -> None:
    sources = drill_sources()
    removals = [
        (name, line.strip())
        for name, text in sources.items()
        for line in text.splitlines()
        if '"down"' in line
    ]
    assert removals
    for name, stripped in removals:
        # Every removal names its project: the cleanup and the work scenario pass `-p`; the
        # self-hosted one goes through its compose helper, which always does.
        assert '"-p"' in stripped or "self.compose(" in stripped, (name, stripped)
    all_text = "\n".join(sources.values())
    assert "system prune" not in all_text
    assert "docker rm" not in all_text.replace("docker volume rm", "")
    assert '"rm", "-f"' not in all_text
    for port in RESERVED_PORTS:
        occurrences = [
            line for text in sources.values() for line in text.splitlines() if str(port) in line
        ]
        assert all(
            line.strip().startswith("#") or "RESERVED_PORTS" in line for line in occurrences
        ), occurrences


@pytest.mark.parametrize(
    "name", ["evil", "my-drill-x", "SK-DRILL-x", "sk-drill-", "sk-drill-a b", "sk-drill-../x"]
)
def test_a_project_name_without_the_drill_prefix_is_refused(tmp_path: Path, name: str) -> None:
    result = run_drill(tmp_path, "all", "--dry-run", "--project", name)
    assert result.process.returncode == 2
    assert "must start with sk-drill-" in result.process.stderr
    assert result.calls == []
    assert not list(result.tmp_root.glob("sk-drill.*"))


def test_a_drill_project_name_is_accepted(tmp_path: Path) -> None:
    result = run_drill(tmp_path, "selfhost", "--dry-run", "--project", "sk-drill-fixed1")
    assert result.process.returncode == 0, result.stdout + result.process.stderr
    assert result.projects == {"sk-drill-fixed1-sh"}


@pytest.mark.parametrize(
    ("fault", "scenario", "failed_step"),
    [
        ("lose-marker", "selfhost", "marker"),
        ("no-schema-move", "selfhost", "verify-updated"),
        ("wrong-key-accepted", "selfhost", "key-fails-closed"),
        ("lose-hindsight", "selfhost", "verify-restored"),
    ],
)
def test_a_failing_step_fails_the_drill_and_still_cleans_up(
    tmp_path: Path, fault: str, scenario: str, failed_step: str
) -> None:
    result = run_drill(tmp_path, "all", "--dry-run", DRILL_FAKE_FAIL=fault)
    assert result.process.returncode == 1, result.stdout
    assert f"FAIL {scenario}/{failed_step}" in result.stdout
    assert "SUMMARY: FAIL" in result.stdout
    # The other scenario still ran, and both projects were removed.
    assert re.search(r"^(PASS|FAIL) work/install \(\d+s\)$", result.stdout, re.M)
    downs = {
        compose_project(argv)
        for argv in result.calls
        if argv[:1] == ["compose"] and "down" in argv and "-f" not in argv
    }
    assert downs == result.projects
    assert not list(result.tmp_root.glob("sk-drill.*"))


def test_a_failed_step_is_annotated_and_the_timings_go_to_the_job_summary(tmp_path: Path) -> None:
    summary = tmp_path / "summary.md"
    result = run_drill(
        tmp_path,
        "selfhost",
        "--dry-run",
        DRILL_FAKE_FAIL="lose-marker",
        GITHUB_ACTIONS="true",
        GITHUB_STEP_SUMMARY=str(summary),
    )
    assert result.process.returncode == 1
    assert "::error title=drill selfhost/marker failed::" in result.stdout
    table = summary.read_text()
    assert "| selfhost/install | PASS |" in table
    assert "| selfhost/marker | FAIL |" in table


def test_a_work_package_fault_is_noticed_too(tmp_path: Path) -> None:
    result = run_drill(tmp_path, "work", "--dry-run", DRILL_FAKE_FAIL="wrong-key-accepted")
    assert result.process.returncode == 1
    assert "FAIL work/key-fails-closed" in result.stdout
    assert "restore accepted a wrong key" in result.stdout


def test_an_update_without_a_schema_move_can_be_accepted_explicitly(tmp_path: Path) -> None:
    result = run_drill(
        tmp_path, "all", "--dry-run", "--allow-same-schema", DRILL_FAKE_FAIL="no-schema-move"
    )
    assert result.process.returncode == 0, result.stdout
    assert "accepted by --allow-same-schema" in result.log_text


def test_the_work_scenario_uses_the_encrypted_backup_files_and_the_restore_command(
    passing: Result,
) -> None:
    flat = [" ".join(argv) for argv in passing.calls]
    assert any("pg_restore" in line for line in flat), "selfhost restore"
    # tools/work.sh restores through psql in one transaction, from a dump decrypted in memory
    assert any("--single-transaction" in line and "psql" in line for line in flat)
    assert "SIDEKICK_BACKUP_ENCRYPTION_KEY" in " ".join(" ".join(a) for a in passing.calls)
    assert re.search(r"work/key-fails-closed", passing.stdout)
    # an update goes through the real update.sh: signature check, snapshot, migrate, in that order
    assert "update.sh: 7/7 done" in passing.log_text
    assert "updated to " + DIGEST_TO in passing.log_text


@pytest.mark.parametrize(
    "args",
    [
        ["--dry-run"],
        ["--from-image", DIGEST_FROM],
        ["--to-image", DIGEST_TO],
    ],
)
def test_local_images_cannot_be_combined_with_a_fake_docker_or_given_images(
    tmp_path: Path, args: list[str]
) -> None:
    result = run_drill(tmp_path, "all", "--local-images", *args)
    assert result.process.returncode == 2, result.stdout + result.process.stderr
    assert "--local-images builds and runs real images" in result.process.stderr
    assert result.calls == []
    assert not list(result.tmp_root.glob("sk-drill.*"))


def test_the_drill_removes_only_the_images_it_built_by_exact_reference() -> None:
    sources = drill_sources()
    removals = [
        line.strip()
        for text in sources.values()
        for line in text.splitlines()
        if '"image", "rm"' in line
    ]
    assert len(removals) == 1
    images = sources["drillimages.py"]
    assert r"127\.0\.0\.1:[0-9]+/sidekick[:@]" in images
    assert "registry:2@sha256:" in images


@pytest.mark.parametrize(
    "args",
    [
        ["selfhost"],
        ["selfhost", "--from-image", DIGEST_FROM],
        ["selfhost", "--from-image", "registry.example/sidekick:1.0", "--to-image", DIGEST_TO],
        ["selfhost", "--from-image", DIGEST_FROM, "--to-image", DIGEST_FROM],
        ["selfhost", "--from-image", DIGEST_FROM, "--to-image", DIGEST_TO],
        ["bogus"],
    ],
)
def test_a_real_run_refuses_missing_or_unpinned_inputs_before_touching_docker(
    tmp_path: Path, args: list[str]
) -> None:
    result = run_drill(tmp_path, *args)
    assert result.process.returncode == 2, result.stdout + result.process.stderr
    assert result.calls == []
    assert not list(result.tmp_root.glob("sk-drill.*"))


@pytest.mark.parametrize("value", ["abc", "70000", "0", "9000\n9001", "55436,x"])
def test_a_malformed_reserved_ports_value_is_refused(tmp_path: Path, value: str) -> None:
    result = run_drill(tmp_path, "selfhost", "--dry-run", SIDEKICK_RESERVED_PORTS=value)
    assert result.process.returncode == 2
    assert "SIDEKICK_RESERVED_PORTS" in result.process.stderr
    assert result.calls == []


def test_extra_reserved_ports_are_normalised_to_decimal(tmp_path: Path) -> None:
    result = run_drill(tmp_path, "selfhost", "--dry-run", SIDEKICK_RESERVED_PORTS=" 030000, 9000")
    assert result.process.returncode == 0, result.stdout + result.process.stderr
    reserved = re.search(r"reserved ports: (.*)", result.stdout + result.process.stderr)
    assert reserved is not None
    assert {"30000", "9000", "8100"} <= set(reserved.group(1).split())
