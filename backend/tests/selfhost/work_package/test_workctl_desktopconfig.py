"""The Claude Desktop configuration of tools/workctl: the entry file written by start, the guarded
merge into the user's own file, and the model id list."""

import io
import json
import stat
from pathlib import Path
from typing import Any

import pytest
from tools.workctl import desktopconfig

ENTRY = {"command": "/usr/bin/docker", "args": ["exec", "-i", "api"]}


def _source(tmp_path: Path, entry: Any = ENTRY) -> Path:
    path = tmp_path / "entry.json"
    path.write_text(json.dumps({"mcpServers": {"sidekick-work": entry}}), encoding="utf-8")
    return path


def _merge(source: Path, target: Path, answer: str = "y", lang: str = "en") -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = desktopconfig.merge_into_claude_config(source, target, lang, lambda: answer, out, err)
    return code, out.getvalue(), err.getvalue()


def test_desktop_config_runs_the_stdio_server_in_the_container() -> None:
    config = desktopconfig.desktop_config("/usr/bin/docker", "sidekick-work-api-1", "user-1")
    assert config == {
        "mcpServers": {
            "sidekick-work": {
                "command": "/usr/bin/docker",
                "args": [
                    "exec",
                    "-i",
                    "-e",
                    "SIDEKICK_MCP_STDIO_OWNER_ID=user-1",
                    "sidekick-work-api-1",
                    "python",
                    "-m",
                    "sidekick.mcp.stdio",
                ],
            }
        }
    }


def test_write_desktop_config_writes_json_with_a_trailing_newline_and_mode_600(
    tmp_path: Path,
) -> None:
    out_file = tmp_path / "claude_desktop_config.json"
    desktopconfig.write_desktop_config(out_file, "/usr/bin/docker", "api-1", "user-1")
    text = out_file.read_text(encoding="utf-8")
    assert text.endswith("}\n")
    assert json.loads(text) == desktopconfig.desktop_config("/usr/bin/docker", "api-1", "user-1")
    assert stat.S_IMODE(out_file.stat().st_mode) == 0o600


def test_write_desktop_config_tightens_the_mode_of_an_existing_file(tmp_path: Path) -> None:
    out_file = tmp_path / "claude_desktop_config.json"
    out_file.write_text("old", encoding="utf-8")
    out_file.chmod(0o644)
    desktopconfig.write_desktop_config(out_file, "/usr/bin/docker", "api-1", "user-1")
    assert stat.S_IMODE(out_file.stat().st_mode) == 0o600
    assert "old" not in out_file.read_text(encoding="utf-8")


def test_parse_model_ids_returns_the_ids_in_order() -> None:
    body = json.dumps({"data": [{"id": "a"}, {"id": "b/c"}, {"object": "x"}, "text"]})
    assert desktopconfig.parse_model_ids(body) == ["a", "b/c"]


def test_parse_model_ids_without_data_is_empty() -> None:
    assert desktopconfig.parse_model_ids("{}") == []


@pytest.mark.parametrize("body", ["", "not json", "[]", '{"data": 5}', "null"])
def test_parse_model_ids_rejects_something_that_is_not_a_model_list(body: str) -> None:
    with pytest.raises(ValueError):
        desktopconfig.parse_model_ids(body)


def test_merge_adds_the_entry_to_a_new_file_without_a_backup(tmp_path: Path) -> None:
    target = tmp_path / "claude" / "config.json"
    code, out, err = _merge(_source(tmp_path), target)
    assert code == 0 and err == "Save the change? (y/N): "
    assert json.loads(target.read_text(encoding="utf-8")) == {
        "mcpServers": {"sidekick-work": ENTRY}
    }
    assert "add mcpServers.sidekick-work" in out
    assert out.endswith(f"Saved: {target}. Restart Claude Desktop completely.\n")
    assert list(target.parent.glob("*.bak.*")) == []


def test_merge_keeps_other_entries_and_backs_up_the_original_bytes(tmp_path: Path) -> None:
    target = tmp_path / "config.json"
    original = (
        b'{"mcpServers":{"other":{"command":"keep"},"sidekick-work":{"command":"old"}},'
        b'"theme":"dark"}\n'
    )
    target.write_bytes(original)
    code, out, _ = _merge(_source(tmp_path), target, lang="sv", answer="Ja")
    assert code == 0
    assert "ersätt mcpServers.sidekick-work" in out
    merged = json.loads(target.read_bytes())
    assert merged["mcpServers"] == {"other": {"command": "keep"}, "sidekick-work": ENTRY}
    assert merged["theme"] == "dark"
    (backup,) = target.parent.glob("*.bak.*")
    assert backup.read_bytes() == original
    assert f"Säkerhetskopia: {backup}" in out
    assert list(target.parent.glob(".claude-config-*")) == []


def test_merge_preview_never_shows_other_connectors(tmp_path: Path) -> None:
    target = tmp_path / "config.json"
    target.write_text(
        json.dumps({"mcpServers": {"other": {"env": {"TOKEN": "secret-xyz"}}}}), encoding="utf-8"
    )
    _, out, err = _merge(_source(tmp_path), target, answer="n")
    assert "secret-xyz" not in out + err


@pytest.mark.parametrize("answer", ["", "n", "no", "nej", "maybe"])
def test_merge_without_an_explicit_yes_changes_nothing(tmp_path: Path, answer: str) -> None:
    target = tmp_path / "config.json"
    target.write_text("{}", encoding="utf-8")
    code, out, _ = _merge(_source(tmp_path), target, answer=answer)
    assert code == 0 and out.endswith("Aborted, nothing changed.\n")
    assert target.read_text(encoding="utf-8") == "{}"
    assert list(tmp_path.glob("*.bak.*")) == []


def test_merge_of_an_entry_that_is_already_current_asks_nothing(tmp_path: Path) -> None:
    target = tmp_path / "config.json"
    target.write_text(json.dumps({"mcpServers": {"sidekick-work": ENTRY}}), encoding="utf-8")
    code, out, err = _merge(_source(tmp_path), target)
    assert code == 0
    assert out == "The Sidekick entry is already current. Nothing changed.\n"
    assert err == ""


@pytest.mark.parametrize("bad", ['{"broken":', "[]", '{"mcpServers":[]}', '{"mcpServers":null}'])
def test_merge_refuses_an_unreadable_target(tmp_path: Path, bad: str) -> None:
    target = tmp_path / "config.json"
    target.write_text(bad, encoding="utf-8")
    code, out, err = _merge(_source(tmp_path), target)
    assert code == 1 and out == ""
    assert (
        err
        == "Could not read the configuration as a JSON object with mcpServers. Nothing changed.\n"
    )
    assert target.read_text(encoding="utf-8") == bad


def test_merge_refuses_a_symlinked_target(tmp_path: Path) -> None:
    real = tmp_path / "real.json"
    real.write_text("{}", encoding="utf-8")
    link = tmp_path / "config.json"
    link.symlink_to(real)
    code, _, err = _merge(_source(tmp_path), link)
    assert code == 1 and "Nothing changed" in err
    assert real.read_text(encoding="utf-8") == "{}"


def test_merge_refuses_an_entry_that_is_not_an_object(tmp_path: Path) -> None:
    code, _, err = _merge(_source(tmp_path, entry="text"), tmp_path / "config.json")
    assert code == 1 and "Nothing changed" in err


def test_merge_without_the_entry_file_points_at_start(tmp_path: Path) -> None:
    code, out, err = _merge(tmp_path / "missing.json", tmp_path / "config.json", lang="sv")
    assert code == 1 and out == ""
    assert err == "Sidekick-posten saknas. Kör först: bash tools/work.sh start\n"
    assert not (tmp_path / "config.json").exists()


def test_merge_does_not_overwrite_an_edit_made_during_the_confirmation(tmp_path: Path) -> None:
    target = tmp_path / "config.json"
    target.write_text('{"mcpServers":{}}', encoding="utf-8")
    edited = '{"mcpServers":{"new-connector":{"command":"keep"}}}'

    def answer_after_an_edit() -> str:
        target.write_text(edited, encoding="utf-8")
        return "y"

    out, err = io.StringIO(), io.StringIO()
    code = desktopconfig.merge_into_claude_config(
        _source(tmp_path), target, "en", answer_after_an_edit, out, err
    )
    assert code == 1
    assert err.getvalue().endswith(
        "The configuration changed after the preview. Run the command again. Nothing changed.\n"
    )
    assert target.read_text(encoding="utf-8") == edited
    assert list(tmp_path.glob("*.bak.*")) == []


def test_merge_keeps_the_original_when_the_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "config.json"
    target.write_text("{}", encoding="utf-8")

    def failing_replace(*_args: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(desktopconfig.os, "replace", failing_replace)
    code, _, err = _merge(_source(tmp_path), target)
    assert code == 1
    assert err.endswith("any backup is next to the file.\n")
    assert target.read_text(encoding="utf-8") == "{}"
    assert list(tmp_path.glob(".claude-config-*")) == []
