"""Dependency rules between the backend packages, read from the source with `ast`.

A *context* is a top-level package under `sidekick` that is not `shared` and not an interface
(`api`, `mcp`, `structured`). Its *layers* are the next path part: `<context>/domain` (or
`<context>/domain.py`) and `<context>/application`. Flat modules such as `references/service.py`
have no layer yet and are not restricted by rules 1 and 2.

1. domain      -> only `sidekick.shared` and domains (own or another context's).
2. application -> `sidekick.shared`, its own context, and other contexts' *domain*; never another
                  context's application (or persistence, or any other part).
3. shared      -> nothing above it: no context, no interface (`api`, `mcp`, `structured`) and no
                  top-level module such as `composition` or `store`. An entrance that needs the
                  composition root (the `admin` CLI) is a context of its own, not part of `shared`.
4. features    -> never the cross-readers `lifecycle`, `search`, `memory`, `owner_export` or
                  `backup`; they sit above the features.
5. service     -> never `sqlalchemy`. A context's `application` modules and its `service` modules
                  ask a store for rows (queries live in the context's own `persistence` module,
                  composed into `sidekick.store`); they type the open session as
                  `sidekick.shared.types.TxSession`.

Every import counts: top level, inside functions (late imports) and inside `if TYPE_CHECKING:`.
Relative imports are resolved to absolute module names first.

Known violations are listed in `DEBT` (rule -> module -> imported modules) so the suite fails on
any *new* violation; the list is empty today.
`test_the_debt_list_has_no_stale_entries` fails when an entry is no longer violated, so the list
only shrinks. Fix a violation, then delete its line. Never add a line to get a build green.
"""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.policy

SRC = Path(__file__).parents[2] / "src" / "sidekick"

SHARED = "shared"
INTERFACES = frozenset({"api", "mcp", "structured"})
CONTEXTS = frozenset(
    path.name
    for path in SRC.iterdir()
    if path.is_dir() and path.name != "__pycache__" and path.name != SHARED
    if path.name not in INTERFACES
)
# Contexts that own a user-visible part of the product. `companion` and `license` are platform
# modules (flat service + ORM) and `lifecycle`, `search`, `memory` read across features.
FEATURES = frozenset({"tasks", "projects", "work", "contacts", "journal", "shopping", "references"})
CROSS_READERS = frozenset({"lifecycle", "search", "memory", "owner_export", "backup"})

RULE_DOMAIN = "domain-imports-only-shared-and-domains"
RULE_APPLICATION = "application-imports-own-context-and-other-domains"
RULE_SHARED = "shared-imports-no-context"
RULE_FEATURE = "feature-imports-no-cross-reader"
RULE_SERVICE_SQL = "service-layer-imports-no-sqlalchemy"
RULES = (RULE_DOMAIN, RULE_APPLICATION, RULE_SHARED, RULE_FEATURE, RULE_SERVICE_SQL)

# Rule -> importing module -> imported modules that break it today. Shrink only.
DEBT: dict[str, dict[str, list[str]]] = {
    RULE_DOMAIN: {},
    RULE_APPLICATION: {},
    RULE_SHARED: {},
    RULE_FEATURE: {},
    RULE_SERVICE_SQL: {},
}


def _module_exists(module: str) -> bool:
    base = SRC.joinpath(*module.split(".")[1:])
    return base.with_suffix(".py").exists() or (base / "__init__.py").exists()


def _module_name(path: Path) -> tuple[str, str]:
    """The dotted module name of `path` and the dotted name of the package it lives in."""

    parts = ["sidekick", *path.relative_to(SRC).with_suffix("").parts]
    if parts[-1] == "__init__":
        parts.pop()
        return ".".join(parts), ".".join(parts)
    return ".".join(parts), ".".join(parts[:-1])


def _absolute_module(package: str, level: int, module: str | None) -> str:
    """The absolute name of `from <level dots><module> import ...` written inside `package`."""

    if not level:
        return module or ""
    anchor = package.split(".")
    anchor = anchor[: len(anchor) - (level - 1)]
    return ".".join([*anchor, *([module] if module else [])])


def _imported_modules(path: Path) -> set[str]:
    _, package = _module_name(path)
    return _imported_from_source(path.read_text(), package)


def _imported_from_source(source: str, package: str) -> set[str]:
    """Every `sidekick.*` module the source imports, anywhere in it, as absolute module names.

    `from sidekick.work import listing` yields `sidekick.work.listing` when that is a module and
    `sidekick.work` when `listing` is only a name.
    """

    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = _absolute_module(package, node.level, node.module)
            for alias in node.names:
                submodule = f"{module}.{alias.name}"
                found.add(submodule if _module_exists(submodule) else module)
    return {name for name in found if name.split(".")[0] in {"sidekick", "sqlalchemy"}}


def _is_service_module(parts: list[str]) -> bool:
    """True for a context's `application` modules and its `service` modules."""

    return (
        len(parts) > 2
        and parts[1] in CONTEXTS
        and (parts[2] == "application" or parts[-1] == "service")
    )


def _broken_rules(source: str, target: str) -> list[str]:
    """The rules that the import of `target` from the module `source` breaks."""

    src, dst = source.split("."), target.split(".")
    if dst[0] == "sqlalchemy":
        return [RULE_SERVICE_SQL] if _is_service_module(src) else []
    if len(src) < 2 or len(dst) < 2:
        return []
    src_context, dst_context = src[1], dst[1]
    src_layer = src[2] if len(src) > 2 else None
    dst_layer = dst[2] if len(dst) > 2 else None
    dst_is_domain = dst_context in CONTEXTS and dst_layer == "domain"
    broken: list[str] = []
    in_domain = src_context in CONTEXTS and src_layer == "domain"
    in_application = src_context in CONTEXTS and src_layer == "application"
    if in_domain and dst_context != SHARED and not dst_is_domain:
        broken.append(RULE_DOMAIN)
    if in_application and dst_context not in {SHARED, src_context} and not dst_is_domain:
        broken.append(RULE_APPLICATION)
    if src_context == SHARED and dst_context != SHARED:
        broken.append(RULE_SHARED)
    if src_context in FEATURES and dst_context in CROSS_READERS:
        broken.append(RULE_FEATURE)
    return broken


def _violations() -> dict[str, dict[str, set[str]]]:
    found: dict[str, dict[str, set[str]]] = {rule: {} for rule in RULES}
    for path in sorted(SRC.rglob("*.py")):
        module, _ = _module_name(path)
        for target in sorted(_imported_modules(path)):
            for rule in _broken_rules(module, target):
                found[rule].setdefault(module, set()).add(target)
    return found


def _flatten(by_rule: dict[str, dict[str, set[str]]] | dict[str, dict[str, list[str]]]) -> set[str]:
    return {
        f"{rule}: {module} -> {target}"
        for rule, modules in by_rule.items()
        for module, targets in modules.items()
        for target in targets
    }


def test_the_contexts_follow_the_package_layout() -> None:
    assert FEATURES <= CONTEXTS
    assert CROSS_READERS <= CONTEXTS
    assert not CONTEXTS & INTERFACES
    assert {"journal", "work", "shared"} <= {path.name for path in SRC.iterdir()}
    assert "admin" in CONTEXTS
    assert not (SRC / "shared" / "auth" / "cli.py").exists()
    assert set(DEBT) <= set(RULES)


def test_the_rules_classify_imports() -> None:
    assert _broken_rules("sidekick.journal.domain.entry", "sidekick.shared.errors") == []
    assert _broken_rules("sidekick.journal.domain.entry", "sidekick.contacts.domain.x") == []
    assert _broken_rules("sidekick.journal.domain", "sidekick.contacts.persistence") == [
        RULE_DOMAIN
    ]
    assert _broken_rules("sidekick.journal.application.a", "sidekick.journal.service") == []
    assert _broken_rules("sidekick.journal.application.a", "sidekick.contacts.domain.c") == []
    assert _broken_rules("sidekick.journal.application.a", "sidekick.contacts.application.c") == [
        RULE_APPLICATION
    ]
    assert _broken_rules("sidekick.shared.persistence.m", "sidekick.journal.domain") == [
        RULE_SHARED
    ]
    assert _broken_rules("sidekick.shared.persistence.m", "sidekick.shared.types") == []
    assert _broken_rules("sidekick.shared.auth.service", "sidekick.composition") == [RULE_SHARED]
    assert _broken_rules("sidekick.shared.auth.service", "sidekick.admin.cli") == [RULE_SHARED]
    assert _broken_rules("sidekick.shared.worker", "sidekick.api.app") == [RULE_SHARED]
    assert _broken_rules("sidekick.shared.worker", "sidekick.store") == [RULE_SHARED]
    assert _broken_rules("sidekick.admin.cli", "sidekick.composition") == []
    assert _broken_rules("sidekick.tasks.application.s", "sidekick.lifecycle.application.s") == [
        RULE_APPLICATION,
        RULE_FEATURE,
    ]
    assert _broken_rules("sidekick.references.service", "sidekick.search.service") == [RULE_FEATURE]
    assert _broken_rules("sidekick.contacts.domain", "sidekick.backup.importer") == [
        RULE_DOMAIN,
        RULE_FEATURE,
    ]
    assert _broken_rules("sidekick.lifecycle.application.s", "sidekick.contacts.application.s") == [
        RULE_APPLICATION
    ]
    assert _broken_rules("sidekick.memory.application.s", "sidekick.lifecycle.domain") == []
    assert _broken_rules("sidekick.references.service", "sqlalchemy.orm") == [RULE_SERVICE_SQL]
    assert _broken_rules("sidekick.tasks.application.s", "sqlalchemy") == [RULE_SERVICE_SQL]
    assert _broken_rules("sidekick.tasks.application.s", "sidekick.shared.types") == []
    assert _broken_rules("sidekick.memory.application.queries", "sqlalchemy.orm") == [
        RULE_SERVICE_SQL
    ]
    assert _broken_rules("sidekick.memory.infrastructure.store", "sqlalchemy.orm") == []
    assert _broken_rules("sidekick.shopping.persistence.store", "sqlalchemy") == []
    assert _broken_rules("sidekick.work.persistence.tags", "sqlalchemy") == []
    assert _broken_rules("sidekick.shared.auth.service", "sqlalchemy") == []


def test_relative_imports_are_resolved_to_absolute_names() -> None:
    assert _absolute_module("sidekick.work.application", 1, "ports") == (
        "sidekick.work.application.ports"
    )
    assert _absolute_module("sidekick.work.application", 2, "domain") == "sidekick.work.domain"
    assert _absolute_module("sidekick.work", 1, None) == "sidekick.work"
    assert _absolute_module("sidekick.work", 0, "sidekick.shared") == "sidekick.shared"


def test_imports_inside_functions_and_type_checking_blocks_are_counted() -> None:
    source = (
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from sidekick.journal.domain import Entry\n"
        "def f():\n"
        "    from sidekick.work import listing\n"
        "    from ..domain import x\n"
    )
    assert _imported_from_source(source, "sidekick.contacts.application") == {
        "sidekick.journal.domain",
        "sidekick.work.listing",
        "sidekick.contacts.domain",
    }


def test_there_are_no_new_package_boundary_violations() -> None:
    new = sorted(_flatten(_violations()) - _flatten(DEBT))
    assert new == [], "New boundary violations (fix the import, do not add debt):\n" + "\n".join(
        new
    )


def test_the_debt_list_has_no_stale_entries() -> None:
    stale = sorted(_flatten(DEBT) - _flatten(_violations()))
    assert stale == [], "Fixed violations still listed in DEBT (delete them):\n" + "\n".join(stale)
