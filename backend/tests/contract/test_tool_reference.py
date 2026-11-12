"""`docs/reference/mcp/` is rendered from the generated MCP contract and may not drift from it.

Regenerate with:
    uv run --project backend python -m sidekick.mcp.export_tool_reference
and verify without writing by adding `--check`.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from sidekick.mcp import export_tool_reference as reference
from sidekick.mcp.export_tool_reference import AREAS, render_pages, stale_problems
from sidekick.mcp.reply_scopes import WRITE_REPLY_READ_SCOPES
from sidekick.mcp.tool_scopes import TOOL_SCOPES, describe
from sidekick.shared.auth import MCP_SCOPES

ROOT = Path(__file__).resolve().parents[3]
REFERENCE_DIR = ROOT / "docs" / "reference" / "mcp"


def _contract() -> list[dict[str, Any]]:
    return json.loads((ROOT / "contracts" / "mcp-tools.generated.json").read_text(encoding="utf-8"))


def _is_app_only(tool: dict[str, Any]) -> bool:
    return (tool.get("_meta") or {}).get("ui", {}).get("visibility") == ["app"]


def _read_only(tool: dict[str, Any]) -> bool:
    return bool((tool.get("annotations") or {}).get("readOnlyHint"))


def test_committed_tool_reference_matches_the_generator() -> None:
    assert stale_problems(render_pages(_contract()), REFERENCE_DIR) == []


def test_check_mode_fails_on_a_stale_directory_and_passes_after_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    contract = ROOT / "contracts" / "mcp-tools.generated.json"
    target = tmp_path / "mcp"
    arguments = ["--contract", str(contract), "--output-dir", str(target)]

    monkeypatch.setattr("sys.argv", ["export_tool_reference", *arguments, "--check"])
    assert reference.main() == 1
    assert "missing" in capsys.readouterr().err

    monkeypatch.setattr("sys.argv", ["export_tool_reference", *arguments])
    assert reference.main() == 0
    (target / "contacts.md").write_text("edited by hand\n", encoding="utf-8")
    (target / "gone.md").write_text(f"{reference.GENERATED_MARKER} -->\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["export_tool_reference", *arguments, "--check"])
    assert reference.main() == 1
    err = capsys.readouterr().err
    assert "out of date" in err
    assert "no longer generated" in err

    monkeypatch.setattr("sys.argv", ["export_tool_reference", *arguments])
    assert reference.main() == 0
    assert not (target / "gone.md").exists()
    monkeypatch.setattr("sys.argv", ["export_tool_reference", *arguments, "--check"])
    assert reference.main() == 0


def test_every_contract_tool_has_one_entry_on_the_page_of_its_visibility() -> None:
    pages = render_pages(_contract())
    app_only_page = pages["app-only.md"]
    model_pages = "\n".join(text for name, text in pages.items() if name != "app-only.md")

    for tool in _contract():
        heading = re.compile(rf"^#{{2,3}} `{tool['name']}`$", re.MULTILINE)
        on_app_only_page = len(heading.findall(app_only_page))
        on_model_pages = len(heading.findall(model_pages))
        assert (on_app_only_page, on_model_pages) == ((1, 0) if _is_app_only(tool) else (0, 1)), (
            tool["name"]
        )


def test_index_links_point_at_existing_pages_and_headings() -> None:
    pages = render_pages(_contract())
    links = re.findall(r"\]\(([a-z-]+\.md)(?:#([a-z_]+))?\)", "\n".join(pages.values()))

    assert links
    for page, anchor in links:
        assert page in pages, page
        if anchor:
            assert f"`{anchor}`\n" in pages[page], (page, anchor)


def test_the_reference_marks_read_and_write_access() -> None:
    text = "\n".join(render_pages(_contract()).values())

    assert "Access: read\n" in text
    assert "Access: write\n" in text
    assert "Access: write (destructive)\n" in text


def test_object_arrays_show_the_shape_of_their_items() -> None:
    pages = render_pages(_contract())

    assert "| `refs[].kind` | string | yes |" in pages["overview.md"]
    assert "| `refs[].id` | uuid | yes |" in pages["overview.md"]
    # Several shapes in one list are told apart by the `type` constant they carry.
    assert "`task_proposals[type=create_task].title`" in pages["app-only.md"]


def test_every_tool_names_its_output_and_no_notes_cell_is_empty() -> None:
    text = "\n".join(render_pages(_contract()).values())

    assert text.count("\nReturns: ") == len(_contract())
    assert "|  |" not in text
    assert "| |" not in text


def test_scopes_come_from_the_table_the_server_enforces() -> None:
    text = "\n".join(render_pages(_contract()).values())

    assert text.count("\nScopes: ") == len(_contract())
    # The reply scope of a write tool is not typed in tool_scopes.py; it flows in from reply_scopes.
    assert "Scopes: requires `tasks:read`, `tasks:write`." in text
    for name, reply_scope in WRITE_REPLY_READ_SCOPES.items():
        assert reply_scope in TOOL_SCOPES[name].requires, name


def test_the_scope_table_covers_exactly_the_contract_and_only_real_scopes() -> None:
    names = {tool["name"] for tool in _contract()}

    assert set(TOOL_SCOPES) == names
    for name, scopes in TOOL_SCOPES.items():
        assert scopes.everything() <= set(MCP_SCOPES), name
        assert describe(scopes) != "none", name


def test_write_tools_name_a_write_scope_and_read_tools_none() -> None:
    for tool in _contract():
        scopes = TOOL_SCOPES[tool["name"]]
        named_write = any(s.endswith(":write") for s in (*scopes.requires, *scopes.any_of))
        if _read_only(tool):
            assert not named_write, tool["name"]
        else:
            assert named_write, tool["name"]


def test_a_tool_in_no_area_is_an_error() -> None:
    tools = [*_contract(), {"name": "brand_new_tool", "description": "x.", "inputSchema": {}}]

    with pytest.raises(ValueError, match="brand_new_tool"):
        render_pages(tools)


def test_an_area_naming_a_removed_tool_is_an_error() -> None:
    gone = AREAS[0].tools[0]

    with pytest.raises(ValueError, match=gone):
        render_pages([tool for tool in _contract() if tool["name"] != gone])


def test_a_tool_without_a_scope_entry_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    gone = AREAS[0].tools[0]
    monkeypatch.setattr(
        reference, "TOOL_SCOPES", {k: v for k, v in TOOL_SCOPES.items() if k != gone}
    )

    with pytest.raises(ValueError, match=gone):
        render_pages(_contract())
