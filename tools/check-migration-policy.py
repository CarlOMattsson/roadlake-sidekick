#!/usr/bin/env python3
"""Flag contract-style statements in migrations that lack an explicit marker.

Policy: a release may only run expand migrations unless the migration file declares itself a
contract step with the comment

    # migration-class: contract

Flagged statements: DROP, RENAME, ALTER COLUMN ... TYPE, SET NOT NULL, REVOKE, TRUNCATE and
DELETE FROM without WHERE. The decision is a text scan of the whole file, with comments removed and
whitespace normalised, so SQL swapped in before step() (conditional or tuple assignment, shadowing,
`step(**{...})`) is still found. Left out of the scan is only what the updater never runs: the
rollback argument of ordinary step(...) calls when it is plain static text (full of DROP; Python
evaluates it when the step is created, so a walrus, call or lambda there is UNANALYSABLE), module
constants used by nothing else, and the module docstring. A constant is a name bound exactly once
in the whole file. A file that uses match/case, a walrus, exec/eval/compile, global/nonlocal, del
or an import other than yoyo, __future__ and typing is UNANALYSABLE as a whole. As an extra check
the apply argument of each step(...) is read with ast: it must be a string literal, a `+`
concatenation, or an f-string over literals and module-level string constants; anything else (a
call, a callable, `**kwargs`) is reported as UNANALYSABLE rather than assumed safe. The check is
deliberately conservative: a false positive is cleared by reading the migration and adding the
marker (or by review), a false negative is not acceptable.

Exemption: a REVOKE whose every target table is created by a CREATE TABLE in the same file is
least privilege for a table the migration itself creates, not a contract change, and is not
flagged. Any other REVOKE (an existing table, a schema-wide target, a statement that cannot be
parsed) is still flagged.

Usage:
    tools/check-migration-policy.py [--base REV]   # files added/changed since REV (default origin/main)
    tools/check-migration-policy.py --all          # every file in migrations/

Exit code 0 = clean, 1 = unmarked contract statements found, 2 = usage or git error.
Uses only the standard library and the git CLI; no database, no network.
"""

from __future__ import annotations

import argparse
import ast
import io
import re
import subprocess
import sys
import tokenize
from pathlib import Path

MARKER = re.compile(
    r"^\s*#\s*migration-class:\s*contract\b", re.IGNORECASE | re.MULTILINE
)
RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("DROP", re.compile(r"\bDROP\b(?!\s+(?:NOT\s+NULL|DEFAULT)\b)", re.IGNORECASE)),
    ("RENAME", re.compile(r"\bRENAME\b", re.IGNORECASE)),
    (
        "ALTER COLUMN ... TYPE",
        re.compile(r"\bALTER\s+COLUMN\s+\S+\s+(?:SET\s+DATA\s+)?TYPE\b", re.IGNORECASE),
    ),
    ("SET NOT NULL", re.compile(r"\bSET\s+NOT\s+NULL\b", re.IGNORECASE)),
    ("REVOKE", re.compile(r"\bREVOKE\b", re.IGNORECASE)),
    ("TRUNCATE", re.compile(r"\bTRUNCATE\b", re.IGNORECASE)),
    (
        "DELETE FROM without WHERE",
        # The statement ends at ';' or at the closing quote of the SQL string.
        re.compile(r"\bDELETE\s+FROM\b(?![^;\"']*\bWHERE\b)", re.IGNORECASE),
    ),
)
CREATE_TABLE = re.compile(
    r"\bCREATE\s+(?:(?:UNLOGGED|TEMP|TEMPORARY)\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([\w\".]+)",
    re.IGNORECASE,
)
REVOKE_TARGETS = re.compile(
    r"\bREVOKE\b.+?\bON\s+(?:TABLE\s+)?(?P<targets>.+?)\s+FROM\s+\S", re.IGNORECASE
)


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def git(*args: str, root: Path | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root or repo_root(),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(f"git {' '.join(args)} failed: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(2)
    return result.stdout


def changed_files(base: str, root: Path | None = None) -> list[Path]:
    """Migration files added or modified since `base`, including working-tree changes.

    `root` defaults to this repository; tools/check-release-migration-class.py passes its own.
    """
    top = root or repo_root()
    names = set(
        git(
            "diff",
            "--name-only",
            "--diff-filter=AM",
            base,
            "--",
            "migrations",
            root=top,
        ).splitlines()
    )
    names |= set(
        git(
            "ls-files", "--others", "--exclude-standard", "--", "migrations", root=top
        ).splitlines()
    )
    return sorted(top / n for n in names if n.endswith(".py"))


def declares_contract(path: Path) -> bool:
    """True when the migration file carries the `# migration-class: contract` marker."""
    return MARKER.search(path.read_text(encoding="utf-8")) is not None


def strip_comments(line: str) -> str:
    stripped = line.lstrip()
    if stripped.startswith("#") or stripped.startswith("--"):
        return ""
    return re.sub(r"\s--.*$", "", line)  # trailing SQL comment


def table_key(name: str) -> str:
    """Bare name for unqualified or sidekick-qualified tables; other schemas keep their prefix."""
    parts = [part.strip().strip('"').lower() for part in name.split(".")]
    if len(parts) == 1 or (len(parts) == 2 and parts[0] == "sidekick"):
        return parts[-1]
    return ".".join(parts)


def created_tables(sql: str) -> set[str]:
    """Tables created by CREATE TABLE in one normalised apply argument."""
    return {table_key(match) for match in CREATE_TABLE.findall(sql)}


def revoke_only_on_created(statement: str, created: set[str]) -> bool:
    """True when a REVOKE statement targets only tables this apply argument creates."""
    match = REVOKE_TARGETS.search(statement)
    if match is None:
        return False
    targets = [table_key(target) for target in match.group("targets").split(",")]
    return all(target in created for target in targets)


def literal_sql(node: ast.expr, constants: dict[str, str] | None = None) -> str | None:
    """The text of a string literal, a `+` concatenation of literals, or an f-string whose parts
    are literals or module-level names bound once to such text; None for anything else.

    A call, `%`/`.format`, callable, starred argument or an unresolvable name cannot be read
    statically, so the caller reports it instead of guessing that it is harmless.
    """
    known = constants or {}
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return known.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = literal_sql(node.left, known), literal_sql(node.right, known)
        if left is not None and right is not None:
            return left + right
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.FormattedValue):
                if value.conversion != -1 or value.format_spec is not None:
                    return None
                part = literal_sql(value.value, known)
            else:
                part = literal_sql(value, known)
            if part is None:
                return None
            parts.append(part)
        return "".join(parts)
    return None


def binding_counts(tree: ast.AST) -> dict[str, int]:
    """How often each name is bound anywhere in the module: assignments in any scope or branch,
    tuple targets, walrus, loop and `with` targets, imports, definitions, parameters, handlers."""
    counts: dict[str, int] = {}

    def bind(name: str) -> None:
        counts[name] = counts.get(name, 0) + 1

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bind(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bind(node.name)
        elif isinstance(node, ast.arg):
            bind(node.arg)
        elif isinstance(node, ast.alias):
            bind((node.asname or node.name).split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bind(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            for name in node.names:
                bind(name)
    return counts


def module_assignments(tree: ast.Module) -> dict[str, ast.Assign]:
    """Module-level `NAME = value` statements whose name is bound exactly once in the whole file."""
    counts = binding_counts(tree)
    return {
        statement.targets[0].id: statement
        for statement in tree.body
        if isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
        and counts.get(statement.targets[0].id) == 1
    }


def module_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level string constants: a name bound exactly once, to a string literal text."""
    constants: dict[str, str] = {}
    for name, statement in module_assignments(tree).items():
        text = literal_sql(statement.value, constants)
        if text is not None:
            constants[name] = text
    return constants


def is_step_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (isinstance(func, ast.Name) and func.id == "step") or (
        isinstance(func, ast.Attribute) and func.attr == "step"
    )


def plain_step_call(node: ast.Call) -> bool:
    """A step(...) call with ordinary arguments: no `*args` and no `**kwargs` unpacking."""
    return not any(isinstance(arg, ast.Starred) for arg in node.args) and not any(
        keyword.arg is None for keyword in node.keywords
    )


def step_calls(tree: ast.AST) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and is_step_call(node)
    ]


def argument(node: ast.Call, position: int, name: str) -> ast.expr | None:
    found = node.args[position] if len(node.args) > position else None
    for keyword in node.keywords:
        if keyword.arg == name:
            found = keyword.value
    return found


def static_rollback(call: ast.Call, constants: dict[str, str]) -> ast.expr | None:
    """The rollback argument of an ordinary step(...) call if it is plainly static text: a string
    literal, a `+` concatenation or f-string of literals, or a once-bound module constant. Python
    evaluates the rollback when the step is created, so anything else (a walrus, a call, a
    subscript, a lambda) can run code and is not set aside."""
    if not plain_step_call(call):
        return None
    rollback = argument(call, 1, "rollback")
    if rollback is None or literal_sql(rollback, constants) is None:
        return None
    return rollback


def rollback_only_nodes(tree: ast.Module, constants: dict[str, str]) -> list[ast.AST]:
    """Nodes whose text the updater never runs: the static rollback argument of every ordinary
    step(...) call, plus module-level constants (`_DOWN = "..."`) used by nothing but such
    rollbacks, and the module docstring."""
    region: set[int] = set()
    nodes: list[ast.AST] = []
    for call in step_calls(tree):
        rollback = static_rollback(call, constants)
        if rollback is not None:
            nodes.append(rollback)
            region.update(id(inner) for inner in ast.walk(rollback))
    docstring = tree.body[0] if tree.body else None
    if (
        isinstance(docstring, ast.Expr)
        and isinstance(docstring.value, ast.Constant)
        and isinstance(docstring.value.value, str)
    ):
        nodes.append(docstring)  # prose, not SQL
    assignments = module_assignments(tree)
    loads = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
    ]
    changed = True
    while changed:
        changed = False
        for name, statement in assignments.items():
            if name not in constants or id(statement) in region:
                continue
            uses = [n for n in loads if n.id == name]
            if uses and all(id(use) in region for use in uses):
                nodes.append(statement)
                region.update(id(inner) for inner in ast.walk(statement))
                changed = True
    return nodes


def blank(text: str, nodes: list[ast.AST]) -> str:
    """`text` with the source of `nodes` replaced by spaces; line breaks and line numbers stay."""
    data = text.encode("utf-8")
    starts = [0]
    for line in data.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    buffer = bytearray(data)
    for node in nodes:
        end_lineno = getattr(node, "end_lineno", None)
        end_col = getattr(node, "end_col_offset", None)
        if end_lineno is None or end_col is None:
            continue
        begin = starts[node.lineno - 1] + node.col_offset  # type: ignore[attr-defined]
        end = starts[end_lineno - 1] + end_col
        for index in range(begin, end):
            if buffer[index] not in b"\r\n":
                buffer[index] = 0x20
    return buffer.decode("utf-8", errors="replace")


def blank_python_comments(text: str) -> str:
    """`text` without Python '#' comments (tokenizer based, so a '#' inside SQL text stays)."""
    lines = text.splitlines(keepends=True)
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.COMMENT:
                row, column = token.start
                line = lines[row - 1]
                lines[row - 1] = (
                    line[:column]
                    + " " * len(token.string)
                    + line[column + len(token.string) :]
                )
    except (tokenize.TokenError, IndentationError):
        return text
    return "".join(lines)


def scan_sql(sql: str, first_line: int) -> list[tuple[int, str, str]]:
    """Rule hits in one SQL text, matched over whitespace-normalised text so line breaks in a
    statement (`ALTER COLUMN x\n TYPE ...`) do not hide it. Line numbers point at the line
    where the match starts."""
    pieces: list[tuple[int, str]] = []
    for offset, raw in enumerate(sql.splitlines()):
        # A "\n" escape in a Python string is a line break in the SQL it holds.
        line = " ".join(re.sub(r"\\[nrt]", " ", strip_comments(raw)).split())
        if line:
            pieces.append((first_line + offset, line))
    normalised = " ".join(line for _, line in pieces)
    starts: list[tuple[int, int]] = []
    position = 0
    for number, line in pieces:
        starts.append((position, number))
        position += len(line) + 1
    created = created_tables(normalised)
    hits: list[tuple[int, str, str]] = []
    for label, pattern in RULES:
        for match in pattern.finditer(normalised):
            if label == "REVOKE":
                begin = normalised.rfind(";", 0, match.start()) + 1
                end = normalised.find(";", match.start())
                statement = normalised[begin : end if end != -1 else None]
                if revoke_only_on_created(statement, created):
                    continue
            number = max(n for start, n in starts if start <= match.start())
            excerpt = normalised[match.start() :].split(";")[0]
            hits.append((number, label, excerpt[:100]))
    return sorted(hits)


ALLOWED_IMPORTS = frozenset({"yoyo", "__future__", "typing"})
DYNAMIC_BUILTINS = frozenset({"exec", "eval", "compile", "__import__"})


def unanalysable_constructs(tree: ast.AST) -> list[tuple[int, str]]:
    """Constructs that can change which SQL reaches step() in ways the scan does not follow.

    A coarse rule on purpose: a migration holding any of them is UNANALYSABLE as a whole and must
    declare its class with the marker. Applying SQL is plain data; nothing here is needed for that.
    """
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 1)
        if isinstance(node, ast.Match):
            found.append((line, "match/case"))
        elif isinstance(node, ast.NamedExpr):
            found.append((line, "walrus (:=)"))
        elif isinstance(node, ast.Name) and node.id in DYNAMIC_BUILTINS:
            found.append((line, f"{node.id}()"))
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            found.append((line, type(node).__name__.lower()))
        elif isinstance(node, ast.Delete):
            found.append((line, "del"))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in ALLOWED_IMPORTS:
                    found.append((line, f"import {alias.name}"))
        elif isinstance(node, ast.ImportFrom) and (
            node.level or (node.module or "").split(".")[0] not in ALLOWED_IMPORTS
        ):
            found.append((line, f"import from {'.' * node.level}{node.module or ''}"))
    return found


def unanalysable(line: int) -> tuple[int, str, str]:
    return (
        line,
        "UNANALYSABLE",
        "step argument is not static text; cannot analyse, declare '# migration-class: contract'",
    )


def scan(path: Path) -> list[tuple[int, str, str]]:
    """Hits for one migration file.

    The text scan decides: every destructive pattern anywhere in the file text (comments removed,
    whitespace normalised) counts, except the rollback argument of ordinary step(...) calls and
    constants used only there, which the updater never runs. An assignment that swaps the SQL
    before step() (`if ...: sql = "DROP ..."`, tuple assignment, shadowing, `step(**{...})`) still
    leaves the pattern in the text and is found. The ast pass is an extra check: the evaluated apply
    text is scanned too (a keyword split over adjacent literals), and an apply argument that is not
    readable as a literal is reported as UNANALYSABLE.
    """
    text = path.read_text(encoding="utf-8")
    if MARKER.search(text):
        return []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return scan_sql(
            blank_python_comments(text), 1
        )  # unparsable: scan the whole file
    constants = module_constants(tree)
    risky = unanalysable_constructs(tree)
    scanned = blank_python_comments(blank(text, rollback_only_nodes(tree, constants)))
    hits = scan_sql(scanned, 1)
    for call in step_calls(tree):
        if not plain_step_call(call):
            hits.append(unanalysable(call.lineno))
            continue
        rollback = argument(call, 1, "rollback")
        if rollback is not None and static_rollback(call, constants) is None:
            hits.append(unanalysable(rollback.lineno))
        apply_arg = argument(call, 0, "apply")
        if apply_arg is None:
            continue
        sql = literal_sql(apply_arg, constants)
        if sql is None:
            hits.append(unanalysable(apply_arg.lineno))
        else:  # the evaluated text also catches a keyword split over adjacent literals
            hits.extend(scan_sql(sql, apply_arg.lineno))
    for line, construct in risky:
        hits.append(
            (
                line,
                "UNANALYSABLE",
                f"{construct}: cannot analyse a migration that uses it, "
                "declare '# migration-class: contract'",
            )
        )
    seen: set[tuple[str, str]] = set()
    unique: list[tuple[int, str, str]] = []
    for hit in sorted(hits):
        if (hit[1], hit[2]) not in seen:
            seen.add((hit[1], hit[2]))
            unique.append(hit)
    return unique


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--base", default="origin/main", help="git revision to compare with"
    )
    group.add_argument("--all", action="store_true", help="scan every migration file")
    args = parser.parse_args()

    if args.all:
        files = sorted((repo_root() / "migrations").glob("[0-9]*.py"))
    else:
        files = changed_files(args.base)

    flagged = 0
    for path in files:
        hits = scan(path)
        if hits:
            flagged += 1
            print(
                f"{path.relative_to(repo_root())}: {len(hits)} unmarked contract statement(s)"
            )
            for number, label, text in hits:
                print(f"  line {number}: {label}: {text}")
    scope = "all migrations" if args.all else f"migrations changed since {args.base}"
    print(
        f"checked {len(files)} file(s) ({scope}); {flagged} need '# migration-class: contract'"
    )
    return 1 if flagged else 0


if __name__ == "__main__":
    sys.exit(main())
