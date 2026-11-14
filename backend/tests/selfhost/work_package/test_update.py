"""`tools/work.sh update`: backup first, rollback, migrations, writers held until ready."""

import shutil
from pathlib import Path
from typing import Any

import pytest
from tools.workctl import backupflow

from tests.selfhost.work_package.support import (
    MIGRATE,
    READINESS_CALL,
    RESTART_WRITERS,
    STOP_WRITERS,
    STUB_IMAGE_ID,
    docker_calls,
    git,
    make_clone,
    ready_repo,
    run_work,
)


def test_update_after_a_failed_restart_names_the_commit_the_way_back_and_the_backups(
    mini_repo: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """The code is pulled when the restart fails: say where we were, and roll nothing back."""

    before = make_clone(mini_repo, tmp_path_factory.mktemp("origin"))
    work = ready_repo(mini_repo)

    result = run_work(mini_repo, "update", STUB_FAIL="recreate")

    assert result.returncode == 1
    assert "omstarten misslyckades" in result.stderr
    way_back = f"git -C {mini_repo} checkout {before} && bash tools/work.sh start --build"
    assert way_back in result.stderr
    assert f"git -C {mini_repo} checkout main" in result.stderr
    assert str(work / "backups") in result.stderr
    assert "inget har rullats tillbaka automatiskt" in result.stderr
    assert git(mini_repo, "rev-parse", "HEAD") == before, "the script never moves it back"
    assert list((work / "backups").glob("sidekick-*.sql.enc")), "the backup from before is kept"


def _update_calls(repo: Path) -> str:
    """The docker calls of `update` from the stop of the writers on (the backup follows)."""

    calls = docker_calls(repo)
    return calls[calls.index(STOP_WRITERS) :]


def test_update_stops_the_writers_before_the_backup_and_holds_them_until_the_new_version_is_ready(
    mini_repo: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    make_clone(mini_repo, tmp_path_factory.mktemp("origin"))
    ready_repo(mini_repo)
    result = run_work(mini_repo, "update")
    assert result.returncode == 0, result.stderr
    calls = docker_calls(mini_repo)
    assert calls.count(STOP_WRITERS) == 1
    # build (touches no data) -> stop -> backup (database, then memory) -> migrate -> start.
    assert calls.index(" build api") < calls.index(STOP_WRITERS) < calls.index("pg_dump")
    assert calls.index("pg_dump") < calls.index("--network none") < calls.index(MIGRATE)
    assert calls.index(MIGRATE) < calls.index("--force-recreate")
    # The writers are never resumed between the stop and the new version.
    assert RESTART_WRITERS not in calls
    # The api alone is started and checked first; the workers follow the check.
    lines = calls.splitlines()
    recreates = [i for i, line in enumerate(lines) if "--force-recreate" in line]
    starts = [i for i, line in enumerate(lines) if line.endswith("--wait-timeout 420")]
    readiness = [i for i, line in enumerate(lines) if f"{READINESS_CALL} import importlib" in line]
    assert len(recreates) == 1 and lines[recreates[0]].endswith("--force-recreate api")
    assert len(starts) == 1 and len(readiness) == 2, (
        "the api is restarted once, the workers after its check"
    )
    assert recreates[0] < readiness[0] < starts[0] < readiness[1]
    assert "sidekick.shared.readiness" in calls


def test_update_keeps_the_previous_image_under_a_tag_before_it_builds(
    mini_repo: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    make_clone(mini_repo, tmp_path_factory.mktemp("origin"))
    ready_repo(mini_repo)
    result = run_work(mini_repo, "update")
    assert result.returncode == 0, result.stderr
    calls = docker_calls(mini_repo)
    keep = f"tag {STUB_IMAGE_ID} roadlake-sidekick:previous"
    assert keep in calls
    assert calls.index(keep) < calls.index(" build api") < calls.index(STOP_WRITERS)
    assert "roadlake-sidekick:previous" in result.stdout


@pytest.mark.parametrize(
    "failing", ["migrate", "recreate", "notready", "term_recreate", "recreate_all"]
)
def test_update_leaves_the_writers_stopped_and_restores_nothing_once_the_migration_has_begun(
    mini_repo: Path, tmp_path_factory: pytest.TempPathFactory, failing: str
) -> None:
    make_clone(mini_repo, tmp_path_factory.mktemp("origin"))
    work = ready_repo(mini_repo)
    result = run_work(
        mini_repo,
        "update",
        STUB_FAIL=failing,
        SIDEKICK_WORK_READY_TIMEOUT="1",
        SIDEKICK_WORK_READY_POLL="1",
    )
    assert result.returncode != 0
    calls = _update_calls(mini_repo)
    assert calls.index(STOP_WRITERS) < calls.index(MIGRATE)
    # No automatic start of the writers, no automatic restore, no switch back to the old image.
    assert RESTART_WRITERS not in calls
    assert "ALTER DATABASE" not in calls and "DROP DATABASE" not in calls
    assert f"tag {STUB_IMAGE_ID} roadlake-sidekick:work" not in calls
    # The stop is repeated after the failing step, so that nothing the step started goes on writing.
    assert calls.rindex(STOP_WRITERS) > calls.index(MIGRATE)
    if failing == "migrate":
        assert "--force-recreate" not in calls, "nothing is recreated on a failed migration"
        assert "migreringen misslyckades" in result.stderr
        assert "docs/operate/work-laptop/backup-and-update.sv.md" in result.stderr
    if failing == "notready":
        assert "inte redo" in result.stderr
    if failing != "term_recreate":
        # Where the backup is and how to look at it first (a dry run of restore); never a restore.
        stamp = next((work / "backups").glob("sidekick-*.sql.enc")).name[
            len("sidekick-") : -len(".sql.enc")
        ]
        assert "lämnas stoppade" in result.stderr
        assert f"bash tools/work.sh restore {stamp} (först utan --apply)" in result.stderr
        assert str(work / "backups") in result.stderr
        assert "inget har rullats tillbaka automatiskt" in result.stderr
    assert not (work / "backups").exists() or list((work / "backups").glob("sidekick-*.sql.enc"))


def test_update_warns_and_does_not_claim_the_old_version_runs_when_the_retag_fails(
    mini_repo: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """The name could not be moved back (for example a repo@sha256 reference): say so, plainly."""

    make_clone(mini_repo, tmp_path_factory.mktemp("origin"))
    ready_repo(mini_repo)
    result = run_work(mini_repo, "update", STUB_FAIL="database", STUB_RETAG_FAIL="1")
    assert result.returncode == 1
    assert "VARNING: avbildningsnamnet roadlake-sidekick:work kunde inte sättas tillbaka" in (
        result.stderr
    )
    assert "föregående version körs INTE" in result.stderr
    assert "roadlake-sidekick:previous" in result.stderr
    assert "föregående version körs igen" not in result.stdout + result.stderr


def test_update_aborts_cleanly_without_stopping_anything_when_the_build_fails(
    mini_repo: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    make_clone(mini_repo, tmp_path_factory.mktemp("origin"))
    ready_repo(mini_repo)
    result = run_work(mini_repo, "update", STUB_FAIL="build")
    assert result.returncode == 1
    calls = docker_calls(mini_repo)
    # Nothing was stopped, backed up or migrated, so there is nothing to start again.
    assert STOP_WRITERS not in calls and RESTART_WRITERS not in calls
    assert "pg_dump" not in calls and MIGRATE not in calls
    assert "bygget misslyckades" in result.stderr
    assert "föregående version körs vidare" in result.stderr


def test_update_starts_the_previous_version_again_when_it_is_interrupted_after_the_stop(
    mini_repo: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """A TERM during the backup: the code, the image name and the writers all go back."""

    before = make_clone(mini_repo, tmp_path_factory.mktemp("origin"))
    ready_repo(mini_repo)
    _publish_migration(mini_repo, tmp_path_factory.mktemp("other"), EXPAND_MIGRATION)
    result = run_work(mini_repo, "update", STUB_FAIL="interrupt")
    assert result.returncode == 143
    calls = docker_calls(mini_repo)
    assert MIGRATE not in calls
    back = f"tag {STUB_IMAGE_ID} roadlake-sidekick:work"
    assert calls.index(" build api") < calls.index(STOP_WRITERS) < calls.index(back)
    assert calls.index(back) < calls.rindex(RESTART_WRITERS)
    assert git(mini_repo, "rev-parse", "HEAD") == before, "the pulled code is put back too"
    assert "föregående version körs igen" in result.stderr + result.stdout


def test_update_starts_the_writers_again_when_the_backup_fails(
    mini_repo: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """A failed backup ends the hold: code, image name and writers go back; nothing is migrated."""

    before = make_clone(mini_repo, tmp_path_factory.mktemp("origin"))
    ready_repo(mini_repo)
    _publish_migration(mini_repo, tmp_path_factory.mktemp("other"), EXPAND_MIGRATION)
    result = run_work(mini_repo, "update", STUB_FAIL="database")
    assert result.returncode == 1
    calls = docker_calls(mini_repo)
    assert calls.index(STOP_WRITERS) < calls.rindex(RESTART_WRITERS)
    assert MIGRATE not in calls
    assert git(mini_repo, "rev-parse", "HEAD") == before, "the pulled code is put back"


def test_update_stops_every_sidekick_worker_of_the_stack(overlay: dict[str, Any]) -> None:
    """A new service on the api image must be added to WRITERS, or update leaves it writing."""

    api_image = overlay["services"]["api"]["image"]
    on_api_image = {
        name
        for name, service in overlay["services"].items()
        if service.get("image") == api_image and name != "migrate"
    }
    assert set(backupflow.WRITERS) == on_api_image


EXPAND_MIGRATION = """from yoyo import step

steps = [step("CREATE TABLE sidekick.t (id uuid)", "DROP TABLE sidekick.t")]
"""


CONTRACT_MIGRATION = """from yoyo import step

steps = [step("ALTER TABLE sidekick.t DROP COLUMN old", "SELECT 1")]
"""


def _publish_migration(repo: Path, work_dir: Path, source: str) -> str:
    """A second clone of the stand-in's origin pushes one new migration; returns its commit."""

    origin = git(repo, "remote", "get-url", "origin")
    other = work_dir / "other"
    git(work_dir, "clone", origin, str(other))
    (other / "migrations").mkdir(exist_ok=True)
    (other / "migrations" / "200_new.py").write_text(source, encoding="utf-8")
    git(other, "add", "migrations")
    git(other, "commit", "-m", "new migration")
    git(other, "push", "origin", "main")
    return git(other, "rev-parse", "HEAD")


def test_update_takes_a_new_expand_only_migration(
    mini_repo: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    make_clone(mini_repo, tmp_path_factory.mktemp("origin"))
    ready_repo(mini_repo)
    new = _publish_migration(mini_repo, tmp_path_factory.mktemp("other"), EXPAND_MIGRATION)

    result = run_work(mini_repo, "update")

    assert result.returncode == 0, result.stderr
    assert git(mini_repo, "rev-parse", "HEAD") == new
    assert MIGRATE in docker_calls(mini_repo)


def test_update_refuses_a_contract_migration_and_puts_the_code_back(
    mini_repo: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """The way back from DROP/RENAME is a restore, so it needs --allow-breaking-migration."""

    before = make_clone(mini_repo, tmp_path_factory.mktemp("origin"))
    work = ready_repo(mini_repo)
    _publish_migration(mini_repo, tmp_path_factory.mktemp("other"), CONTRACT_MIGRATION)

    result = run_work(mini_repo, "update")

    assert result.returncode == 1
    assert "200_new.py" in result.stderr
    assert "--allow-breaking-migration" in result.stderr
    assert git(mini_repo, "rev-parse", "HEAD") == before, "the code is put back"
    assert not (mini_repo / "migrations" / "200_new.py").exists()
    assert not list((work / "backups").glob("*")), (
        "no backup is taken for an update that is refused"
    )
    calls = docker_calls(mini_repo)
    # Nothing was stopped, backed up, built, migrated or recreated: the check comes first.
    assert STOP_WRITERS not in calls and "pg_dump" not in calls
    assert " build api" not in calls and MIGRATE not in calls and "--force-recreate" not in calls


def test_update_takes_a_contract_migration_when_it_is_allowed(
    mini_repo: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    make_clone(mini_repo, tmp_path_factory.mktemp("origin"))
    ready_repo(mini_repo)
    new = _publish_migration(mini_repo, tmp_path_factory.mktemp("other"), CONTRACT_MIGRATION)

    result = run_work(mini_repo, "update", "--allow-breaking-migration")

    assert result.returncode == 0, result.stderr
    assert git(mini_repo, "rev-parse", "HEAD") == new
    assert MIGRATE in docker_calls(mini_repo)


def test_update_names_the_command_when_the_code_cannot_be_put_back(
    mini_repo: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    before = make_clone(mini_repo, tmp_path_factory.mktemp("origin"))
    ready_repo(mini_repo)
    _publish_migration(mini_repo, tmp_path_factory.mktemp("other"), CONTRACT_MIGRATION)
    # A stand-in that cannot move the checkout back and does everything else as usual.
    real = shutil.which("git")
    assert real is not None
    wrapper = mini_repo / "bin" / "git"
    wrapper.write_text(
        f'#!/bin/sh\ncase " $* " in *" reset "*) exit 1 ;; esac\nexec {real} "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)

    result = run_work(mini_repo, "update")

    assert result.returncode == 1
    assert f"git -C {mini_repo} reset --keep {before}" in result.stderr


def test_update_refuses_an_unknown_option_before_anything_runs(mini_repo: Path) -> None:
    ready_repo(mini_repo)

    result = run_work(mini_repo, "update", "--force")

    assert result.returncode == 2
    assert "användning:" in result.stderr
    assert not (mini_repo / "docker-calls.txt").exists(), "docker was never called"


def test_update_refuses_a_checkout_that_is_not_a_git_clone(mini_repo: Path) -> None:
    work = ready_repo(mini_repo)
    result = run_work(mini_repo, "update", GIT_CEILING_DIRECTORIES=str(mini_repo.parent))
    assert result.returncode == 1
    assert "klonat med git" in result.stderr
    assert not (work / "backups").exists(), "refused before the backup"
    assert not (mini_repo / "docker-calls.txt").exists(), "docker was never called"


def test_stop_purge_deletes_nothing_without_a_yes(mini_repo: Path) -> None:
    work = ready_repo(mini_repo)
    assert run_work(mini_repo, "backup").returncode == 0
    for answer in ("nej\n", "yes\n", "\n", ""):
        result = run_work(mini_repo, "stop", "--purge", stdin=answer)
        assert result.returncode == 1, answer
    assert (work / "secrets" / "db.env").exists()
    assert list((work / "backups").glob("sidekick-*.sql.enc"))
    assert "down -v" not in docker_calls(mini_repo)


def test_stop_purge_with_a_yes_deletes_data_secrets_and_backups_but_keeps_work_env(
    mini_repo: Path,
) -> None:
    work = ready_repo(mini_repo)
    assert run_work(mini_repo, "backup").returncode == 0
    result = run_work(mini_repo, "stop", "--purge", stdin="ja\n")
    assert result.returncode == 0, result.stderr
    assert "Raderat" in result.stdout
    assert "down -v" in docker_calls(mini_repo)
    assert not (work / "secrets").exists()
    assert not (work / "backups").exists()
    assert (work / "work.env").exists()


def test_stop_without_purge_keeps_everything(mini_repo: Path) -> None:
    work = ready_repo(mini_repo)
    result = run_work(mini_repo, "stop")
    assert result.returncode == 0, result.stderr
    calls = docker_calls(mini_repo)
    assert "down" in calls and "down -v" not in calls
    assert (work / "secrets" / "db.env").exists()
