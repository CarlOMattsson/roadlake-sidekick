"""work.sh and workctl together: a failing render must not damage what is already on disk."""

import shutil
from pathlib import Path

from tests.selfhost.work_package.support import run_work


def test_a_failing_autostart_render_keeps_the_existing_file(mini_repo: Path) -> None:
    unit = mini_repo / "autostart" / "sidekick-work.service"
    assert run_work(mini_repo, "autostart", "on").returncode == 0
    before = unit.read_text(encoding="utf-8")
    assert before
    (mini_repo / "tools" / "workctl" / "autostart.py").write_text(
        "def render_systemd(script):\n    raise RuntimeError('boom')\n"
        "def render_launchd(label, script, log):\n    raise RuntimeError('boom')\n",
        encoding="utf-8",
    )
    result = run_work(mini_repo, "autostart", "on")
    assert result.returncode != 0
    assert unit.read_text(encoding="utf-8") == before


def test_work_sh_without_python3_says_so_in_both_languages_and_does_nothing(
    mini_repo: Path, tmp_path: Path
) -> None:
    bare_path = tmp_path / "bare-path"
    bare_path.mkdir()
    for tool in ("bash", "dirname"):
        found = shutil.which(tool)
        assert found is not None
        (bare_path / tool).symlink_to(found)
    result = run_work(mini_repo, "status", PATH=str(bare_path))
    assert result.returncode == 1
    assert result.stdout == ""
    assert "python3 (3.9 or newer) is required / python3 (3.9 eller nyare) behövs." in result.stderr
    assert not (mini_repo / "docker-calls.txt").exists()
