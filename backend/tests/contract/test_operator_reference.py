"""`docs/reference/cli.md` and `docs/reference/scopes.md` are rendered from code and may not drift.

Regenerate with:
    uv run --project backend python -m sidekick.export_reference
and verify without writing by adding `--check`.
"""

import argparse
import tomllib
from pathlib import Path

import pytest

from sidekick import export_reference as reference
from sidekick.export_reference import (
    CLI_PAGE,
    CLIS,
    MCP_SCOPE_DESCRIPTIONS,
    SCOPES_PAGE,
    render_pages,
    stale_problems,
)
from sidekick.shared.auth import COMPANION_SCOPES, MCP_SCOPES, OPT_IN_SCOPES

ROOT = Path(__file__).resolve().parents[3]
REFERENCE_DIR = ROOT / "docs" / "reference"
# Developer exports, not operator commands: they write contract files for review.
NOT_OPERATOR_COMMANDS = frozenset({"sidekick-openapi"})


def _parsers() -> list[tuple[str, argparse.ArgumentParser]]:
    return [(spec.command, reference._load_parser(spec)) for spec in CLIS]  # pyright: ignore[reportPrivateUsage]


def test_committed_operator_references_match_the_generator() -> None:
    assert stale_problems(render_pages(), REFERENCE_DIR) == []


def test_check_mode_fails_on_a_stale_directory_and_passes_after_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    arguments = ["--output-dir", str(tmp_path)]

    monkeypatch.setattr("sys.argv", ["export_reference", *arguments, "--check"])
    assert reference.main() == 1
    assert "missing" in capsys.readouterr().err

    monkeypatch.setattr("sys.argv", ["export_reference", *arguments])
    assert reference.main() == 0
    (tmp_path / CLI_PAGE).write_text("edited by hand\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["export_reference", *arguments, "--check"])
    assert reference.main() == 1
    assert "out of date" in capsys.readouterr().err

    monkeypatch.setattr("sys.argv", ["export_reference", *arguments])
    assert reference.main() == 0
    monkeypatch.setattr("sys.argv", ["export_reference", *arguments, "--check"])
    assert reference.main() == 0


def test_every_script_of_the_package_is_in_the_cli_reference() -> None:
    pyproject = tomllib.loads((ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = set(pyproject["project"]["scripts"]) - NOT_OPERATOR_COMMANDS

    assert scripts <= {spec.command for spec in CLIS}


def test_every_command_and_argument_has_a_help_text() -> None:
    missing: list[str] = []
    for command, parser in _parsers():
        sub = reference._subparsers(parser)  # pyright: ignore[reportPrivateUsage]
        children = {command: parser}
        if sub is not None:
            children = {f"{command} {name}": child for name, child in sub.choices.items()}
            missing += [
                f"{command} {action.dest}"
                for action in sub._choices_actions  # pyright: ignore[reportPrivateUsage]
                if not action.help
            ]
        for name, child in children.items():
            missing += [
                f"{name} {action.dest}"
                for action in reference._actions(child)  # pyright: ignore[reportPrivateUsage]
                if not isinstance(action, argparse._HelpAction)  # pyright: ignore[reportPrivateUsage]
                and not isinstance(action, argparse._SubParsersAction)  # pyright: ignore[reportPrivateUsage]
                and not action.help
            ]

    assert missing == []


def test_building_a_parser_needs_no_settings_or_database(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("SIDEKICK_DATABASE_URL", "DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)

    assert [command for command, _ in _parsers()] == [spec.command for spec in CLIS]


def test_every_mcp_scope_is_described_and_opt_in_scopes_are_marked() -> None:
    assert set(MCP_SCOPE_DESCRIPTIONS) == set(MCP_SCOPES)
    text = render_pages()[SCOPES_PAGE]

    for scope in MCP_SCOPES:
        row = next(line for line in text.splitlines() if line.startswith(f"| `{scope}` |"))
        assert ("off: opt-in" in row) == (scope in OPT_IN_SCOPES), scope


def test_every_companion_capability_is_listed_with_its_operations() -> None:
    text = render_pages()[SCOPES_PAGE]

    for scope in COMPANION_SCOPES:
        row = next(line for line in text.splitlines() if line.startswith(f"| `{scope}` |"))
        assert "none" not in row.split("|")[3], scope
    assert "`task.complete`" in text
    assert "in preset `app`" in text
