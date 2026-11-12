"""The generated files of tools/workctl: the gateway configuration with one listener per allowed
address, the allowlist compose override, and build-info.json."""

import json
from pathlib import Path
from typing import Any

import pytest
from tools.workctl import generated

NOW = "2026-11-12T10:00:00Z"
OLD_UPDATE = "2026-10-01T08:00:00Z"
COMMIT_DATE = "2026-11-11T17:30:00+01:00"
GATEWAY_TEMPLATE = "global\n# @ALLOWLIST@\ndefaults\n"


def _block(index: int, host: str, port: int) -> str:
    """The frontend and backend pair that one allowlist entry renders to."""
    return (
        f"frontend allow_{index}\n"
        "    mode tcp\n"
        f"    bind :{port}\n"
        f"    default_backend allow_{index}_server\n"
        "\n"
        f"backend allow_{index}_server\n"
        "    mode tcp\n"
        f"    server upstream {host}:{port} resolvers docker init-addr libc,none\n"
    )


def _read_json(path: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def test_parse_allow_lines_reads_host_and_port_pairs() -> None:
    assert generated.parse_allow_lines("embed.a.lan 443\n\n x.b 8443 \n") == [
        ("embed.a.lan", 443),
        ("x.b", 8443),
    ]


def test_parse_allow_lines_of_nothing_is_empty() -> None:
    assert generated.parse_allow_lines("") == []


def test_render_gateway_renders_one_listener_pair_per_entry() -> None:
    rendered = generated.render_gateway(GATEWAY_TEMPLATE, [("embed.a.lan", 443)])
    assert rendered == "global\n" + _block(1, "embed.a.lan", 443) + "defaults\n"


def test_render_gateway_lists_the_exact_rows_of_one_entry() -> None:
    lines = [
        line.strip()
        for line in generated.render_gateway(GATEWAY_TEMPLATE, [("embed.a.lan", 443)]).splitlines()
    ]
    for row in (
        "frontend allow_1",
        "bind :443",
        "default_backend allow_1_server",
        "backend allow_1_server",
        "server upstream embed.a.lan:443 resolvers docker init-addr libc,none",
    ):
        assert row in lines


def test_render_gateway_joins_the_blocks_of_several_entries_with_a_newline() -> None:
    entries = [("embed.a.lan", 443), ("x.b", 8443)]
    rendered = generated.render_gateway(GATEWAY_TEMPLATE, entries)
    assert (
        rendered
        == "global\n" + _block(1, "embed.a.lan", 443) + "\n" + _block(2, "x.b", 8443) + "defaults\n"
    )
    assert "# @ALLOWLIST@" not in rendered


def test_render_gateway_without_entries_removes_the_marker() -> None:
    assert generated.render_gateway(GATEWAY_TEMPLATE, []) == "global\ndefaults\n"


@pytest.fixture(name="gateway_paths")
def _gateway_paths(tmp_path: Path) -> tuple[Path, Path]:
    """The template and an empty output directory for write_gateway_files."""
    template = tmp_path / "gateway.haproxy.cfg"
    template.write_text(GATEWAY_TEMPLATE, encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    return template, out_dir


def test_write_gateway_files_with_entries_writes_both_files(
    gateway_paths: tuple[Path, Path],
) -> None:
    template, out_dir = gateway_paths
    entries = [("embed.a.lan", 443), ("x.b", 8443)]
    generated.write_gateway_files(template, out_dir, entries)

    cfg = (out_dir / "gateway.haproxy.cfg").read_text(encoding="utf-8")
    assert cfg == generated.render_gateway(GATEWAY_TEMPLATE, entries)
    override = (out_dir / "allow.compose.yaml").read_text(encoding="utf-8")
    assert "aliases: [embed.a.lan, x.b]" in override


def test_write_gateway_files_without_entries_removes_an_old_override(
    gateway_paths: tuple[Path, Path],
) -> None:
    template, out_dir = gateway_paths
    (out_dir / "allow.compose.yaml").write_text("old\n", encoding="utf-8")
    generated.write_gateway_files(template, out_dir, [])

    assert not (out_dir / "allow.compose.yaml").exists()
    cfg = (out_dir / "gateway.haproxy.cfg").read_text(encoding="utf-8")
    assert cfg == "global\ndefaults\n"


def test_new_build_info_has_every_field(tmp_path: Path) -> None:
    path = tmp_path / "build-info.json"
    generated.write_build_info(path, "abc123", COMMIT_DATE, NOW, "", False)
    assert _read_json(path) == {
        "commit": "abc123",
        "commit_date": COMMIT_DATE,
        "built_at": NOW,
        "updated_at": NOW,
        "previous_commit": "",
    }


def test_build_info_file_is_json_with_indent_two_and_a_final_newline(tmp_path: Path) -> None:
    path = tmp_path / "build-info.json"
    generated.write_build_info(path, "abc123", COMMIT_DATE, NOW, "", False)
    expected = {
        "commit": "abc123",
        "commit_date": COMMIT_DATE,
        "built_at": NOW,
        "updated_at": NOW,
        "previous_commit": "",
    }
    assert path.read_text(encoding="utf-8") == json.dumps(expected, indent=2) + "\n"


def test_update_with_updated_sets_updated_at_to_now(tmp_path: Path) -> None:
    path = tmp_path / "build-info.json"
    path.write_text(
        json.dumps(
            {
                "commit": "old1",
                "commit_date": COMMIT_DATE,
                "built_at": OLD_UPDATE,
                "updated_at": OLD_UPDATE,
                "previous_commit": "",
            }
        ),
        encoding="utf-8",
    )
    generated.write_build_info(path, "new2", COMMIT_DATE, NOW, "old1", True)
    info = _read_json(path)
    assert info["updated_at"] == NOW
    assert info["built_at"] == NOW
    assert info["commit"] == "new2"
    assert info["previous_commit"] == "old1"


def test_update_without_updated_keeps_updated_at_and_previous_commit(tmp_path: Path) -> None:
    path = tmp_path / "build-info.json"
    path.write_text(
        json.dumps(
            {
                "commit": "old1",
                "commit_date": COMMIT_DATE,
                "built_at": OLD_UPDATE,
                "updated_at": OLD_UPDATE,
                "previous_commit": "prev0",
            }
        ),
        encoding="utf-8",
    )
    generated.write_build_info(path, "new2", COMMIT_DATE, NOW, "", False)
    info = _read_json(path)
    assert info["updated_at"] == OLD_UPDATE
    assert info["previous_commit"] == "prev0"
    assert info["built_at"] == NOW


@pytest.mark.parametrize("contents", ["{not json", "[1, 2]", "null"])
def test_a_damaged_build_info_file_is_ignored(tmp_path: Path, contents: str) -> None:
    path = tmp_path / "build-info.json"
    path.write_text(contents, encoding="utf-8")
    generated.write_build_info(path, "abc123", COMMIT_DATE, NOW, "", False)
    assert _read_json(path) == {
        "commit": "abc123",
        "commit_date": COMMIT_DATE,
        "built_at": NOW,
        "updated_at": NOW,
        "previous_commit": "",
    }
