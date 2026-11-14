"""Repository paths named in comments, scripts and configuration point at files that exist.

A comment that says "see docs/<dir>/pagination.md" or a script that lists a compose file goes
stale silently when the file moves, is renamed, or is left out of the published copy of the
repository. This test finds repository-relative paths (`docs/`, `tools/`, `deploy/`, `backend/`,
`frontend/`, `contracts/`, `migrations/`, `website/`, `assets/`, `licenses/`) and requires each
one to exist.

Where it looks: the files of the published repository. That is the tracked files, narrowed by the
export allowlist and denylist with the export overlay on top in a checkout that has tools/export,
and all tracked files in the published copy itself. A path must exist there, not merely in the
working tree.
- Python: comments and docstrings only (test data may invent paths on purpose).
- TypeScript, JavaScript: comments only.
- Shell, YAML, INI, TOML, Gradle: every line.

A path counts when it ends in a file extension or a slash. Names with a wildcard or a template
character are skipped, and so are the locations in GENERATED, which only exist at run time or
after a build. The test passes in the working repository and in the published copy of it.
"""

import ast
import importlib.util
import io
import re
import subprocess
import sys
import tokenize
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.policy

ROOT = Path(__file__).resolve().parents[3]
EXPORT_CONFIG = ROOT / "tools" / "export"

# Locations created while the software runs or by a local build, and ignored files that hold local
# settings and secrets (any `*.env`): never part of the repository.
GENERATED = (
    "backend/.venv/",
    "deploy/work/work.",
    "deploy/work/secrets/",
    "deploy/work/backups/",
    "deploy/work/.work.lock",
    "frontend/android/app/build/",
)
LINE_SUFFIXES = {".sh", ".yaml", ".yml", ".ini", ".toml", ".gradle"}
COMMENT_SUFFIXES = {".ts", ".tsx", ".js", ".mjs"}
SKIPPED_PARTS = {"node_modules", "fixtures"}

PATH = re.compile(
    r"(?<![\w./@-])"
    r"((?:docs|tools|deploy|contracts|migrations|backend|frontend|website|assets|licenses)/"
    r"[\w./-]*[\w/-])"
    r"(?![\w*${<\[%])"
)
FILE_NAME = re.compile(r"[\w-]\.[A-Za-z0-9]{1,6}$")
SLASH_COMMENT = re.compile(r"(?://|^\s*/?\*)(.*)$")


def _export_filter() -> ModuleType | None:
    """The export's own select logic, or None in the published copy, which has no tools/export."""
    path = EXPORT_CONFIG / "export_filter.py"
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location("sidekick_export_filter", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


def _published_files() -> dict[str, Path]:
    """Repository path -> file on disk, for every file the published repository holds."""
    try:
        listing = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "-z"],
            capture_output=True,
            check=True,
            text=True,
            timeout=60,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        pytest.skip("not a git checkout, so there is no list of tracked files")
    names = [name for name in listing.split("\0") if name]
    export_filter = _export_filter()
    if export_filter is None:
        return {name: ROOT / name for name in names}
    allow = export_filter.load_patterns(EXPORT_CONFIG / "allowlist.txt")
    deny = export_filter.load_patterns(EXPORT_CONFIG / "denylist.txt")
    published = {
        name: ROOT / name
        for name in names
        if export_filter.matches(allow, name) and not export_filter.matches(deny, name)
    }
    overlay = EXPORT_CONFIG / "overlay"
    for file in overlay.rglob("*") if overlay.is_dir() else ():
        if file.is_file():
            published[file.relative_to(overlay).as_posix()] = file
    return published


def _exists(path: str, published: dict[str, Path]) -> bool:
    """A file of the published repository, or a directory that holds one."""
    if path.endswith("/"):
        return any(name.startswith(path) for name in published)
    return path in published or any(name.startswith(path + "/") for name in published)


def _python_comment_lines(text: str) -> Iterator[tuple[int, str]]:
    """Comments and docstrings of a Python module; every line when it does not parse."""
    try:
        tree = ast.parse(text)
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (SyntaxError, tokenize.TokenError):
        yield from enumerate(text.splitlines(), 1)
        return
    for token in tokens:
        if token.type == tokenize.COMMENT:
            yield token.start[0], token.string
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            first = node.body[0] if node.body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                for offset, line in enumerate(first.value.value.splitlines()):
                    yield first.value.lineno + offset, line


def _comment_lines(name: str, text: str) -> Iterator[tuple[int, str]]:
    suffix = Path(name).suffix
    if suffix == ".py":
        yield from _python_comment_lines(text)
    elif suffix in COMMENT_SUFFIXES:
        for number, line in enumerate(text.splitlines(), 1):
            comment = SLASH_COMMENT.search(line)
            if comment:
                yield number, comment.group(1)
    elif suffix in LINE_SUFFIXES:
        yield from enumerate(text.splitlines(), 1)


def _is_scanned(name: str) -> bool:
    suffix = Path(name).suffix
    return suffix == ".py" or suffix in COMMENT_SUFFIXES or suffix in LINE_SUFFIXES


def referenced_paths(name: str, text: str) -> list[tuple[int, str]]:
    """The repository paths a file names in the places that are scanned, as (line number, path)."""
    if not PATH.search(text):  # most files name no path at all: skip parsing them
        return []
    found: list[tuple[int, str]] = []
    for number, line in _comment_lines(name, text):
        for match in PATH.finditer(line):
            path = match.group(1)
            if ".." in path or path.startswith(GENERATED) or path.endswith(".env"):
                continue
            if path.endswith("/") or FILE_NAME.search(path):
                found.append((number, path))
    return sorted(found)


def test_paths_named_in_comments_scripts_and_config_exist() -> None:
    published = _published_files()
    dead: list[str] = []
    for name, file in sorted(published.items()):
        if SKIPPED_PARTS & set(Path(name).parts) or not _is_scanned(name):
            continue
        text = file.read_text(encoding="utf-8", errors="replace")
        for number, path in referenced_paths(name, text):
            if not _exists(path, published):
                dead.append(f"{name}:{number}: {path}")
    assert not dead, "paths that do not exist in the published repository:\n" + "\n".join(dead)


def test_finds_a_path_in_a_python_comment_and_a_docstring_but_not_in_data() -> None:
    source = '"""See docs/gone/a.md."""\n# and tools/gone/b.sh\nEXAMPLE = "deploy/gone/c.yaml"\n'
    assert referenced_paths("m.py", source) == [
        (1, "docs/gone/a.md"),
        (2, "tools/gone/b.sh"),
    ]


def test_finds_a_path_in_a_script_line_and_in_a_typescript_comment() -> None:
    assert referenced_paths("s.sh", "FILES=(deploy/gone/compose.yaml)\n") == [
        (1, "deploy/gone/compose.yaml")
    ]
    ts = 'const a = "docs/gone/a.md"; // see docs/gone/b.md\n'
    assert referenced_paths("a.ts", ts) == [(1, "docs/gone/b.md")]


def test_skips_wildcards_templates_generated_locations_and_bare_directories() -> None:
    text = (
        "# docs/*.md and deploy/${NAME}/x.yaml and deploy/work/work.env\n"
        "# tools/call and backend/.venv/bin/python\n"
    )
    assert referenced_paths("s.sh", text) == []
