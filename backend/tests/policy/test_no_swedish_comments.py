"""Comments and docstrings in backend code are English (language policy, 2026-11-10).

Swedish is for the user interface and data, which live in string literals and are not looked at
here. Only full-line `#` comments and docstrings are checked. Swedish names and data may appear
inside them: text in quotes or backticks, capitalized words (room and screen names such as
Inköp or Dagbok) and single letters are ignored. Any other word with å, ä or ö fails.
"""

import ast
import io
import re
import tokenize
from pathlib import Path

import pytest

pytestmark = pytest.mark.policy

BACKEND = Path(__file__).resolve().parents[2]
ROOTS = (BACKEND / "src", BACKEND / "tests")
QUOTED = re.compile(r'`[^`]*`|"[^"]*"|\u201c[^\u201d]*\u201d')
# Lowercase only: capitalized words are names.
SWEDISH_WORD = re.compile(r"\b(?=\w*[åäö])[a-zåäö]{2,}\b")


def _python_files() -> list[Path]:
    return sorted(
        path
        for root in ROOTS
        for path in root.rglob("*.py")
        if ".venv" not in path.parts and "__pycache__" not in path.parts
    )


def _comment_lines(source: str) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT and token.line.lstrip().startswith("#"):
            found.append((token.start[0], token.string))
    return found


def _docstring_lines(tree: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        body = node.body
        if not body or not isinstance(body[0], ast.Expr):
            continue
        value = body[0].value
        if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
            continue
        for offset, line in enumerate(value.value.splitlines()):
            found.append((value.lineno + offset, line))
    return found


def _has_swedish_word(text: str) -> bool:
    return SWEDISH_WORD.search(QUOTED.sub("", text)) is not None


def _swedish_hits(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    lines = _comment_lines(source) + _docstring_lines(ast.parse(source))
    relative = path.relative_to(BACKEND)
    return [
        f"{relative}:{number}: {text.strip()[:80]}"
        for number, text in sorted(lines)
        if _has_swedish_word(text)
    ]


def test_backend_comments_and_docstrings_are_english() -> None:
    hits = [hit for path in _python_files() for hit in _swedish_hits(path)]
    assert not hits, "Swedish comments or docstrings (write English):\n" + "\n".join(hits)


def test_the_check_finds_swedish_comments_and_docstrings_but_not_strings(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        '"""Modul på svenska."""\n'
        "LABEL = 'Köp licens'  # not a full-line comment\n"
        "# en kommentar på svenska\n"
        "def f() -> str:\n"
        '    """Returnerar ett värde."""\n'
        "    return 'på'\n",
        encoding="utf-8",
    )
    source = sample.read_text(encoding="utf-8")
    lines = _comment_lines(source) + _docstring_lines(ast.parse(source))
    flagged = sorted(n for n, text in lines if _has_swedish_word(text))
    assert flagged == [1, 3, 5]
