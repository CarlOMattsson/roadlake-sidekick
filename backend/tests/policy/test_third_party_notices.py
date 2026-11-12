"""THIRD_PARTY_NOTICES.md must follow the lock files (tools/third_party_notices.py --check)."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.policy

TOOL = Path(__file__).resolve().parents[3] / "tools" / "third_party_notices.py"


def load_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("third_party_notices", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_notices_file_matches_the_lock_files() -> None:
    assert load_tool().check() == []


def test_every_flagged_license_has_a_reviewed_note() -> None:
    tool = load_tool()
    text = tool.OUTPUT.read_text()
    assert "UNREVIEWED" not in text
    assert "UNKNOWN" not in text


def test_a_stale_file_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tool = load_tool()
    stale = tmp_path / "THIRD_PARTY_NOTICES.md"
    stale.write_text(tool.OUTPUT.read_text().replace("| anyio |", "| anyio-gone |", 1))
    monkeypatch.setattr(tool, "OUTPUT", stale)
    problems = tool.check()
    assert any("anyio" in problem for problem in problems)


def test_the_android_license_asset_is_fresh_and_names_the_notices() -> None:
    tool = load_tool()
    assert tool.ANDROID_LICENSES.exists()
    text = tool.ANDROID_LICENSES.read_text()
    assert text == tool.render_android_licenses()
    needles = ("react ", "@capacitor/core", "Apache License", "Kotlin Compiler", "protobuf-java")
    assert all(needle in text for needle in needles)


def test_a_stale_android_license_asset_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = load_tool()
    stale = tmp_path / "third-party-licenses.txt"
    stale.write_text(tool.ANDROID_LICENSES.read_text() + "\nstale\n")
    monkeypatch.setattr(tool, "ANDROID_LICENSES", stale)
    assert any("lags the lock files" in problem for problem in tool.check())


def test_the_glance_protobuf_runtime_is_bsd_and_the_postgres_container_is_flagged() -> None:
    tool = load_tool()
    glance = tool.gradle_license("androidx.glance:glance-appwidget-external-protobuf")
    assert glance is not None and glance[0] == "BSD-3-Clause"
    assert "| container | postgres |" in tool.OUTPUT.read_text()


def test_the_files_the_image_copies_exist() -> None:
    assert all(path.exists() for path in load_tool().IMAGE_LICENSE_FILES)


def test_the_web_bundles_keep_their_mit_notices() -> None:
    repo = Path(__file__).resolve().parents[3]
    mcp_app = (repo / "backend" / "src" / "sidekick" / "mcp" / "apps" / "sidekick.html").read_text()
    assert "Copyright (c) 2015-present Jason Miller" in mcp_app
    assert "Permission is hereby granted, free of charge" in mcp_app
    assert "THIRD_PARTY_NOTICES.md" in mcp_app
