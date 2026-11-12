"""tools/check-release-migration-class.py: the declared release class must cover the migrations."""

import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

TOOL = Path(__file__).resolve().parents[3] / "tools" / "check-release-migration-class.py"

EXPAND = """from yoyo import step

steps = [step("CREATE TABLE sidekick.{name} (id uuid PRIMARY KEY)", "DROP TABLE sidekick.{name}")]
"""
DROP_COLUMN = """from yoyo import step

steps = [step("ALTER TABLE sidekick.notes DROP COLUMN legacy", "SELECT 1")]
"""
RENAME_COLUMN = """from yoyo import step

steps = [step("ALTER TABLE sidekick.notes RENAME COLUMN a TO b", "SELECT 1")]
"""
MARKED = """# migration-class: contract
from yoyo import step

steps = [step("SELECT 1", "SELECT 1")]
"""


def load_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_release_migration_class", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "tag.gpgsign=false",
            *args,
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def tag(repo: Path, name: str, ref: str = "HEAD") -> None:
    """An annotated tag, as the release process requires."""
    git(repo, "tag", "-a", name, "-m", name, ref)


def commit(repo: Path, message: str) -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-m", message)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository with one expand migration, released as v0.1.0."""
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "migrations").mkdir()
    (tmp_path / "migrations" / "001_notes.py").write_text(EXPAND.format(name="notes"))
    commit(tmp_path, "first")
    tag(tmp_path, "v0.1.0")
    return tmp_path


def add_migration(repo: Path, name: str, source: str) -> None:
    (repo / "migrations" / name).write_text(source)
    commit(repo, name)


def run(repo: Path, *args: str) -> int:
    return load_tool().main(list(args), root=repo)


def test_the_first_release_of_this_repository_must_be_breaking() -> None:
    """The 0.1.0 baseline declares the contract class, so the first release (`--base none`, every
    migration reviewed) can only be declared breaking."""

    tool = load_tool()
    policy = tool.load_policy()
    root = TOOL.parents[1]

    offenders = {path.name for path in tool.contract_files(root, policy, None)}

    assert "100_schema_baseline_0_1_0.py" in offenders


def test_expand_only_migrations_accept_expand(repo: Path) -> None:
    add_migration(repo, "002_more.py", EXPAND.format(name="more"))

    assert run(repo, "--release-class", "expand") == 0


def test_no_new_migrations_accept_expand(repo: Path) -> None:
    (repo / "README.md").write_text("changed\n")
    commit(repo, "docs only")

    assert run(repo, "--release-class", "expand") == 0


@pytest.mark.parametrize("source", [DROP_COLUMN, RENAME_COLUMN, MARKED])
def test_a_contract_migration_refuses_expand(
    repo: Path, source: str, capsys: pytest.CaptureFixture[str]
) -> None:
    add_migration(repo, "002_contract.py", source)

    assert run(repo, "--release-class", "expand") == 1
    assert "002_contract.py" in capsys.readouterr().out


@pytest.mark.parametrize("source", [DROP_COLUMN, RENAME_COLUMN, MARKED])
def test_a_contract_migration_accepts_breaking(repo: Path, source: str) -> None:
    add_migration(repo, "002_contract.py", source)

    assert run(repo, "--release-class", "breaking") == 0


def test_an_older_contract_migration_before_the_previous_release_is_ignored(repo: Path) -> None:
    add_migration(repo, "002_contract.py", DROP_COLUMN)
    tag(repo, "v0.2.0")
    add_migration(repo, "003_more.py", EXPAND.format(name="more"))

    assert run(repo, "--release-class", "expand") == 0
    assert run(repo, "--release-class", "expand", "--base", "v0.1.0") == 1


def test_the_newest_release_tag_is_the_base_by_version_not_by_name(repo: Path) -> None:
    add_migration(repo, "002_contract.py", DROP_COLUMN)
    tag(repo, "v0.10.0")
    tag(repo, "v0.9.0", "HEAD~1")
    tag(repo, "desktop-v9.0.0", "HEAD~1")
    add_migration(repo, "003_more.py", EXPAND.format(name="more"))

    # v0.10.0 is newer than v0.9.0; since it only an expand migration was added.
    assert run(repo, "--release-class", "expand") == 0


def test_without_a_release_tag_the_check_refuses_instead_of_guessing(repo: Path) -> None:
    git(repo, "tag", "-d", "v0.1.0")
    add_migration(repo, "002_contract.py", DROP_COLUMN)

    assert run(repo, "--release-class", "expand") == 2


def test_the_first_release_reviews_every_migration_against_the_class(repo: Path) -> None:
    git(repo, "tag", "-d", "v0.1.0")
    add_migration(repo, "002_contract.py", DROP_COLUMN)

    assert run(repo, "--release-class", "expand", "--base", "none") == 1
    assert run(repo, "--release-class", "breaking", "--base", "none") == 0


def test_the_first_release_accepts_expand_when_every_migration_is_expand_only(repo: Path) -> None:
    git(repo, "tag", "-d", "v0.1.0")

    assert run(repo, "--release-class", "expand", "--base", "none") == 0


def test_none_is_refused_once_a_release_tag_exists(repo: Path) -> None:
    add_migration(repo, "002_contract.py", DROP_COLUMN)

    assert run(repo, "--release-class", "expand", "--base", "none") == 2


def test_none_is_refused_when_a_release_tag_exists_on_another_branch(repo: Path) -> None:
    git(repo, "tag", "-d", "v0.1.0")
    git(repo, "checkout", "-q", "-b", "other")
    add_migration(repo, "002_other.py", EXPAND.format(name="other"))
    tag(repo, "v0.2.0")
    git(repo, "checkout", "-q", "main")
    add_migration(repo, "003_contract.py", DROP_COLUMN)

    assert run(repo, "--release-class", "expand", "--base", "none") == 2


def test_a_base_tag_on_head_would_compare_nothing_and_is_refused(repo: Path) -> None:
    add_migration(repo, "002_contract.py", DROP_COLUMN)
    tag(repo, "v0.2.0")

    assert run(repo, "--release-class", "expand", "--base", "v0.2.0") == 2
    # Without --base the newest tag is HEAD itself, which is refused too.
    assert run(repo, "--release-class", "expand") == 2


@pytest.mark.parametrize(
    "base", ["HEAD", "main", "HEAD~1", "v9.9.9", "--output=x", "v0.1", "0.1.0"]
)
def test_a_base_that_is_not_an_existing_release_tag_is_refused(repo: Path, base: str) -> None:
    add_migration(repo, "002_contract.py", DROP_COLUMN)

    assert run(repo, "--release-class", "expand", f"--base={base}") == 2


def test_a_lightweight_release_tag_is_refused(repo: Path) -> None:
    git(repo, "tag", "-d", "v0.1.0")
    git(repo, "tag", "v0.1.0")
    add_migration(repo, "002_more.py", EXPAND.format(name="more"))

    assert run(repo, "--release-class", "expand") == 2
    assert run(repo, "--release-class", "expand", "--base=v0.1.0") == 2


def test_a_commit_hash_is_not_accepted_as_base(repo: Path) -> None:
    add_migration(repo, "002_contract.py", DROP_COLUMN)
    first = subprocess.run(
        ["git", "rev-parse", "HEAD~1"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()

    assert run(repo, "--release-class", "expand", "--base", first) == 2


def test_a_tag_that_is_not_an_ancestor_of_head_is_refused(repo: Path) -> None:
    git(repo, "checkout", "-q", "-b", "other")
    add_migration(repo, "002_other.py", EXPAND.format(name="other"))
    tag(repo, "v0.2.0")
    git(repo, "checkout", "-q", "main")
    add_migration(repo, "003_contract.py", DROP_COLUMN)

    assert run(repo, "--release-class", "expand", "--base", "v0.2.0") == 2


def head(repo: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def test_installed_commit_checks_only_what_changed_since_it(repo: Path) -> None:
    add_migration(repo, "002_contract.py", DROP_COLUMN)
    installed = head(repo)
    add_migration(repo, "003_more.py", EXPAND.format(name="more"))

    # The contract migration is already installed; only the expand migration is new.
    assert run(repo, "--release-class", "expand", "--installed", installed) == 0
    assert run(repo, "--release-class", "expand", "--installed", "HEAD~2") == 1


@pytest.mark.parametrize("source", [DROP_COLUMN, RENAME_COLUMN, MARKED])
def test_installed_commit_refuses_a_new_contract_migration_unless_breaking(
    repo: Path, source: str, capsys: pytest.CaptureFixture[str]
) -> None:
    installed = head(repo)
    add_migration(repo, "002_contract.py", source)

    assert run(repo, "--release-class", "expand", "--installed", installed) == 1
    assert "002_contract.py" in capsys.readouterr().out
    assert run(repo, "--release-class", "breaking", "--installed", installed) == 0


def test_installed_commit_equal_to_head_compares_only_the_working_tree(repo: Path) -> None:
    installed = head(repo)

    assert run(repo, "--release-class", "expand", "--installed", installed) == 0
    (repo / "migrations" / "002_pending.py").write_text(DROP_COLUMN)
    assert run(repo, "--release-class", "expand", "--installed", installed) == 1


def test_installed_commit_must_be_an_ancestor_of_head(repo: Path) -> None:
    git(repo, "checkout", "-q", "-b", "other")
    add_migration(repo, "002_other.py", EXPAND.format(name="other"))
    other = head(repo)
    git(repo, "checkout", "-q", "main")
    add_migration(repo, "003_more.py", EXPAND.format(name="more"))

    assert run(repo, "--release-class", "expand", "--installed", other) == 2
    # An unknown commit stops in the helper that runs the version control tool, with the same code.
    with pytest.raises(SystemExit) as error:
        run(repo, "--release-class", "expand", "--installed", "no-such-commit")
    assert error.value.code == 2


def test_installed_and_base_cannot_be_combined(repo: Path) -> None:
    arguments = ("--release-class", "expand", "--installed", head(repo), "--base", "v0.1.0")

    assert run(repo, *arguments) == 2


def test_an_unknown_class_is_a_usage_error(repo: Path) -> None:
    with pytest.raises(SystemExit) as error:
        run(repo, "--release-class", "contract")

    assert error.value.code == 2


# tools/check-migration-policy.py must not let a contract statement hide from the scan.
HIDDEN_BY_VARIABLE = """from yoyo import step

sql = "ALTER TABLE sidekick.notes DROP COLUMN legacy"
steps = [step(sql, "SELECT 1")]
"""
HIDDEN_BY_CALL = """from yoyo import step

steps = [step("ALTER TABLE sidekick.notes DROP COLUMN legacy".upper(), "SELECT 1")]
"""
HIDDEN_BY_FORMAT = """from yoyo import step

steps = [step("ALTER TABLE sidekick.notes {0} legacy".format("DROP COLUMN"), "SELECT 1")]
"""
HIDDEN_BY_FUNCTION = """from yoyo import step


def apply_it(conn):
    conn.execute("ALTER TABLE sidekick.notes DROP COLUMN legacy")


steps = [step(apply_it)]
"""
HIDDEN_BY_FSTRING_CALL = """from yoyo import step

steps = [step(f"ALTER TABLE sidekick.notes {'DROP'.lower()} COLUMN legacy", "SELECT 1")]
"""
HIDDEN_BY_LINE_BREAK = """from yoyo import step

steps = [
    step(
        \"\"\"
        ALTER TABLE sidekick.notes ALTER COLUMN body
            TYPE text
        \"\"\",
        "SELECT 1",
    )
]
"""
HIDDEN_BY_LINE_BREAK_DROP = """from yoyo import step

steps = [step("ALTER TABLE sidekick.notes\\n  DROP\\n  COLUMN legacy", "SELECT 1")]
"""
HIDDEN_BY_CONCAT = """from yoyo import step

steps = [step("ALTER TABLE sidekick.notes " + "DROP COLUMN legacy", "SELECT 1")]
"""
HIDDEN_BY_CONSTANT = """from yoyo import step

_UP = "ALTER TABLE sidekick.notes DROP COLUMN legacy"
steps = [step(f"SET LOCAL ROLE sidekick_owner;\\n{_UP}", "SELECT 1")]
"""
READABLE_CONSTANT = """from yoyo import step

_UP = "CREATE TABLE sidekick.more (id uuid PRIMARY KEY)"
steps = [step(f"SET LOCAL ROLE sidekick_owner;\\n{_UP}", "SELECT 1")]
"""


@pytest.mark.parametrize(
    "source",
    [
        HIDDEN_BY_VARIABLE,
        HIDDEN_BY_CALL,
        HIDDEN_BY_FORMAT,
        HIDDEN_BY_FUNCTION,
        HIDDEN_BY_FSTRING_CALL,
        HIDDEN_BY_LINE_BREAK,
        HIDDEN_BY_LINE_BREAK_DROP,
        HIDDEN_BY_CONCAT,
        HIDDEN_BY_CONSTANT,
    ],
)
def test_a_contract_statement_cannot_hide_from_the_scan(repo: Path, source: str) -> None:
    add_migration(repo, "002_hidden.py", source)

    assert run(repo, "--release-class", "expand") == 1


def test_an_f_string_over_module_constants_is_read(repo: Path) -> None:
    add_migration(repo, "002_more.py", READABLE_CONSTANT)

    assert run(repo, "--release-class", "expand") == 0


def test_an_unreadable_step_argument_names_why(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    add_migration(repo, "002_hidden.py", HIDDEN_BY_CALL)

    assert run(repo, "--release-class", "expand") == 1
    assert "cannot analyse" in capsys.readouterr().out


# The text scan decides: SQL reaching step() by a route the ast pass cannot follow is still found.
HEADER = "from yoyo import step\n\n"
CONDITIONAL_REASSIGNMENT = (
    HEADER
    + """import os

sql = "SELECT 1"
if os.environ.get("X"):
    sql = "ALTER TABLE sidekick.notes DROP COLUMN legacy"
steps = [step(sql, "SELECT 1")]
"""
)
TUPLE_ASSIGNMENT = (
    HEADER
    + """sql, other = "SELECT 1", "ALTER TABLE sidekick.notes DROP COLUMN legacy"
steps = [step(other, "SELECT 1")]
"""
)
LOCAL_SHADOWING = (
    HEADER
    + """sql = "SELECT 1"


def build() -> list:
    sql = "ALTER TABLE sidekick.notes RENAME COLUMN a TO b"
    return [step(sql, "SELECT 1")]


steps = build()
"""
)
KWARGS_UNPACKING = (
    HEADER
    + """steps = [
    step(**{"apply": "ALTER TABLE sidekick.notes DROP COLUMN legacy", "rollback": "SELECT 1"})
]
"""
)
TRUNCATING = HEADER + """steps = [step("TRUNCATE sidekick.notes", "SELECT 1")]\n"""
DELETE_ALL = HEADER + """steps = [step("DELETE FROM sidekick.notes", "SELECT 1")]\n"""
SET_TYPE_BROKEN = (
    HEADER
    + """steps = [
    step("ALTER TABLE sidekick.notes ALTER COLUMN body SET DATA\\n TYPE text", "SELECT 1")
]
"""
)
DELETE_WITH_WHERE = (
    HEADER + """steps = [step("DELETE FROM sidekick.notes WHERE id IS NULL", "SELECT 1")]\n"""
)
ROLLBACK_CONSTANT_ONLY = (
    '''"""Rolling back would DROP COLUMN and delete from it; prose is not SQL."""
'''
    + HEADER
    + """_DOWN = "DROP TABLE sidekick.more"  # DROP in a comment is not SQL either
steps = [step("CREATE TABLE sidekick.more (id uuid PRIMARY KEY)", f"{_DOWN}")]
"""
)
SPLIT_KEYWORD = (
    HEADER + """steps = [step("ALTER TABLE sidekick.notes DR" "OP COLUMN legacy", "SELECT 1")]\n"""
)
SHARED_CONSTANT = (
    HEADER
    + """_SQL = "DROP TABLE sidekick.more"
steps = [step(_SQL, _SQL)]
"""
)


WALRUS_IN_ROLLBACK = (
    HEADER
    + """sql = "SELECT 1"
step("SELECT 1", (sql := "DROP TABLE sidekick.tasks"))
steps = [step(sql)]
"""
)
CALL_IN_ROLLBACK = HEADER + """steps = [step("SELECT 1", "DROP TABLE sidekick.t".lower())]\n"""
LAMBDA_IN_ROLLBACK = HEADER + """steps = [step("SELECT 1", (lambda: "SELECT 1")())]\n"""
SUBSCRIPT_IN_ROLLBACK = HEADER + """steps = [step("SELECT 1", ["SELECT 1"][0])]\n"""
REASSIGNED_CONSTANT = (
    HEADER
    + """import os

_SQL = "SELECT 1"
if os.environ.get("X"):
    _SQL = "DROP TABLE sidekick.tasks"
steps = [step(_SQL, "SELECT 1")]
"""
)
REASSIGNED_ROLLBACK_CONSTANT = (
    HEADER
    + """_DOWN = "SELECT 1"
_DOWN = "SELECT 2"
steps = [step("SELECT 1", _DOWN)]
"""
)
TUPLE_REBOUND_CONSTANT = (
    HEADER
    + """_SQL = "SELECT 1"
_SQL, _OTHER = "DROP TABLE sidekick.tasks", 1
steps = [step(_SQL, "SELECT 1")]
"""
)


@pytest.mark.parametrize(
    "source",
    [
        WALRUS_IN_ROLLBACK,
        CALL_IN_ROLLBACK,
        LAMBDA_IN_ROLLBACK,
        SUBSCRIPT_IN_ROLLBACK,
        REASSIGNED_CONSTANT,
        REASSIGNED_ROLLBACK_CONSTANT,
        TUPLE_REBOUND_CONSTANT,
        CONDITIONAL_REASSIGNMENT,
        TUPLE_ASSIGNMENT,
        LOCAL_SHADOWING,
        KWARGS_UNPACKING,
        TRUNCATING,
        DELETE_ALL,
        SET_TYPE_BROKEN,
        SHARED_CONSTANT,
        SPLIT_KEYWORD,
    ],
)
def test_the_text_scan_finds_sql_that_the_ast_pass_cannot_follow(repo: Path, source: str) -> None:
    add_migration(repo, "002_hidden.py", source)

    assert run(repo, "--release-class", "expand") == 1


@pytest.mark.parametrize("source", [DELETE_WITH_WHERE, ROLLBACK_CONSTANT_ONLY])
def test_rollbacks_prose_and_scoped_deletes_are_not_contract_statements(
    repo: Path, source: str
) -> None:
    add_migration(repo, "002_fine.py", source)

    assert run(repo, "--release-class", "expand") == 0


# A file that uses a construct which can rebind or run code is UNANALYSABLE as a whole, even when
# every step argument looks like a plain literal.
MATCH_BINDS_CONSTANT = (
    HEADER
    + """SQL = "SELECT 1"
match 1:
    case SQL:
        pass
steps = [step(SQL, "SELECT 1")]
"""
)
WALRUS_ELSEWHERE = HEADER + """(unused := 1)\nsteps = [step("SELECT 1", "SELECT 1")]\n"""
EXEC_PRESENT = HEADER + """exec("pass")\nsteps = [step("SELECT 1", "SELECT 1")]\n"""
GLOBAL_PRESENT = (
    HEADER
    + """SQL = "SELECT 1"


def rebind() -> None:
    global SQL
    SQL = "SELECT 2"


steps = [step(SQL, "SELECT 1")]
"""
)
DEL_PRESENT = HEADER + """x = 1\ndel x\nsteps = [step("SELECT 1", "SELECT 1")]\n"""
FOREIGN_IMPORT = "import os\n" + HEADER + """steps = [step("SELECT 1", "SELECT 1")]\n"""
FOREIGN_IMPORT_FROM = (
    "from os import path\n" + HEADER + """steps = [step("SELECT 1", "SELECT 1")]\n"""
)
ALLOWED_IMPORTS_ONLY = (
    "from __future__ import annotations\n\nfrom typing import Any\n\nimport yoyo\n"
    + HEADER
    + """steps: list[Any] = [step("SELECT 1", "SELECT 1"), yoyo.step("SELECT 1")]\n"""
)


@pytest.mark.parametrize(
    "source",
    [
        MATCH_BINDS_CONSTANT,
        WALRUS_ELSEWHERE,
        EXEC_PRESENT,
        GLOBAL_PRESENT,
        DEL_PRESENT,
        FOREIGN_IMPORT,
        FOREIGN_IMPORT_FROM,
    ],
)
def test_a_file_with_a_rebinding_or_dynamic_construct_is_unanalysable(
    repo: Path, source: str, capsys: pytest.CaptureFixture[str]
) -> None:
    add_migration(repo, "002_dynamic.py", source)

    assert run(repo, "--release-class", "expand") == 1
    assert "UNANALYSABLE" in capsys.readouterr().out


def test_yoyo_future_and_typing_imports_are_fine(repo: Path) -> None:
    add_migration(repo, "002_plain.py", ALLOWED_IMPORTS_ONLY)

    assert run(repo, "--release-class", "expand") == 0
