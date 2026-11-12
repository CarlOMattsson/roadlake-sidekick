"""First installation under umask 077 and the failed-first-start hints."""

import stat
from pathlib import Path

import pytest

from tests.selfhost.work_package.support import (
    docker_calls,
    docker_calls_if_any,
    ready_repo,
    run_work,
)


def test_start_repairs_public_mount_permissions_under_umask_077(mini_repo: Path) -> None:
    work = ready_repo(mini_repo)
    roles = mini_repo / "deploy" / "selfhost" / "postgres-init.sh"
    roles.chmod(0o600)
    (work / "generated").chmod(0o700)
    result = run_work(mini_repo, "start", umask=0o077)
    assert result.returncode == 0, result.stderr
    assert stat.S_IMODE(roles.stat().st_mode) == 0o755
    assert stat.S_IMODE((work / "generated").stat().st_mode) == 0o755
    for name in ("gateway.haproxy.cfg", "build-info.json"):
        assert stat.S_IMODE((work / "generated" / name).stat().st_mode) == 0o644
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in (work / "secrets").iterdir())


@pytest.mark.parametrize("flags", [("--build", "--no-cache"), ("--no-cache", "--build")])
def test_start_passes_no_cache_only_to_the_explicit_build(
    mini_repo: Path, flags: tuple[str, ...]
) -> None:
    ready_repo(mini_repo)
    result = run_work(mini_repo, "start", *flags)
    assert result.returncode == 0, result.stderr
    assert " build --no-cache api\n" in docker_calls(mini_repo)
    assert " up -d --wait --wait-timeout 420\n" in docker_calls(mini_repo)


@pytest.mark.parametrize("flags", [("--no-cache",), ("--force",)])
def test_start_refuses_invalid_flags_before_docker(mini_repo: Path, flags: tuple[str, ...]) -> None:
    ready_repo(mini_repo)
    result = run_work(mini_repo, "start", *flags)
    assert result.returncode == 2
    assert not docker_calls_if_any(mini_repo)


@pytest.mark.parametrize("schema", ["absent", "_yoyo_migration"])
@pytest.mark.parametrize("evidence", ["migration", "postgres", "start"])
def test_failed_first_start_names_only_the_unmigrated_project_volume(
    mini_repo: Path, schema: str, evidence: str
) -> None:
    ready_repo(mini_repo)
    auth = 'password authentication failed for user "sidekick_migrator"'
    env = {
        "STUB_START_FAIL": auth if evidence == "start" else "start failed",
        "STUB_MIGRATION_LOG": auth if evidence == "migration" else "",
        "STUB_POSTGRES_LOG": (
            "/docker-entrypoint-initdb.d/10-sidekick-roles.sh: Permission denied"
            if evidence == "postgres"
            else ""
        ),
        "STUB_SCHEMA": schema,
        "SIDEKICK_WORK_PROJECT": "custom-work",
        "STUB_PG_VOLUME": "custom-work_pgdata",
    }
    result = run_work(mini_repo, "start", **env)
    assert result.returncode == 1
    assert "inga migreringar har tillämpats" in result.stderr
    assert "docker volume rm custom-work_pgdata" in result.stderr
    assert "SIDEKICK_WORK_PROJECT=custom-work bash tools/work.sh stop" in result.stderr
    assert "Behåll deploy/work/secrets/" in result.stderr
    calls = docker_calls(mini_repo)
    assert "label=com.docker.compose.project=custom-work" in calls
    assert "label=com.docker.compose.volume=pgdata" in calls
    assert "volume rm" not in calls and " down " not in calls and "down -v" not in calls


@pytest.mark.parametrize(
    "schema, count, evidence",
    [
        ("_yoyo_migration", "1", True),
        ("unknown", "0", True),
        ("", "0", True),
        ("absent", "0", False),
    ],
)
def test_first_start_does_not_suggest_volume_removal_for_existing_or_unknown_data(
    mini_repo: Path, schema: str, count: str, evidence: bool
) -> None:
    work = ready_repo(mini_repo)
    # Stale evidence in work.log from a previous run must not trigger the diagnosis.
    (work / "work.log").write_text(
        'password authentication failed for user "sidekick_migrator"\n', encoding="utf-8"
    )
    result = run_work(
        mini_repo,
        "start",
        STUB_START_FAIL="unrelated failure",
        STUB_MIGRATION_LOG='password authentication failed for user "sidekick_migrator"'
        if evidence
        else "",
        STUB_SCHEMA=schema,
        STUB_MIGRATIONS=count,
    )
    assert result.returncode == 1
    assert "docker volume rm" not in result.stderr
    assert "volume rm" not in docker_calls(mini_repo)
