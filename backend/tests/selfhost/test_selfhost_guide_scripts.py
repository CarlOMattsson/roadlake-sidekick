"""The self-hosting guide runs scripts as `./name.sh`; each of them must be executable."""

import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SELFHOST = ROOT / "deploy" / "selfhost"
# The self-hosting guides: the first start and the operating pages under docs/, in both languages.
GUIDES = tuple(
    sorted(
        path.relative_to(ROOT).as_posix()
        for pattern in ("docs/start/self-hosted-server*.md", "docs/operate/*.md")
        for path in ROOT.glob(pattern)
    )
)


def _scripts_run_directly(guide: str) -> set[str]:
    text = (ROOT / guide).read_text(encoding="utf-8")
    return set(re.findall(r"(?<![\w/.])\./([\w-]+\.sh)\b", text))


def test_the_guides_name_the_update_and_restore_scripts() -> None:
    english = [guide for guide in GUIDES if not guide.endswith(".sv.md")]
    named = set().union(*(_scripts_run_directly(guide) for guide in english))
    assert {"update.sh", "restore.sh"} <= named


@pytest.mark.parametrize("guide", GUIDES)
def test_every_script_the_guide_runs_directly_is_executable(guide: str) -> None:
    for name in sorted(_scripts_run_directly(guide)):
        script = SELFHOST / name
        assert script.is_file(), f"{guide} runs ./{name}, which does not exist"
        assert os.access(script, os.X_OK), f"{guide} runs ./{name}, which is not executable"
