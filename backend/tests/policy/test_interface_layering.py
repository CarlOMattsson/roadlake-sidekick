"""The two interfaces share `sidekick.structured`; neither imports the other's helpers.

`sidekick.api.companion*` and `sidekick.mcp` answer the same reads and writes through the shared
records in `sidekick.structured`. A runtime import from the API into the MCP layer (or back) would
bring the import cycle back, so the imports are read from the source and checked here.
`sidekick.composition` builds the container for both and imports neither; nothing outside
`sidekick.api` imports `sidekick.api` (`api/app.py` imports `mcp` to mount it, which the tests
allow).
The transport layers (`api`, `mcp`) hold no SQL: they import neither `sqlalchemy` nor the shared
persistence package nor any context's own `persistence` module, only application services and
`structured` reads through the container.
`<domain>/application` packages import no `sidekick.shared.persistence` either. Their `sqlalchemy`
imports are already covered by `test_package_boundaries.py` (rule 5, empty debt for `application`),
so that rule is not repeated here.
"""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.policy

SRC = Path(__file__).parents[2] / "src" / "sidekick"

# Modules outside `sidekick.api` that may still import it. Empty: the stdio, voice and
# export-contract entrances only need `create_container`, which lives in `sidekick.composition`.
API_IMPORT_EXCEPTIONS: set[str] = set()


# Transport modules (relative to `sidekick`) that may import SQLAlchemy or the persistence package,
# each with its reason. Empty: `api` and `mcp` get the session factory type from
# `sidekick.composition.SessionFactory`, and everything else (the companion services included)
# through the `Container`. Add an entry only for wiring that cannot go through the composition
# root, and say why.
TRANSPORT_PERSISTENCE_EXCEPTIONS: dict[str, str] = {}

PERSISTENCE_PACKAGES = ("sqlalchemy", "sidekick.shared.persistence")

# `<domain>/application` modules (relative to `sidekick`) that still import the persistence package,
# each with its reason. The list only shrinks: replace the ORM row class with a record type in the
# application layer or in `shared/types`, then delete the entry. Never add one to get a build green.
APPLICATION_PERSISTENCE_EXCEPTIONS: dict[str, str] = {}


def test_auth_knows_no_memory_type_and_memory_application_imports_no_persistence() -> None:
    """Provisioning a memory row goes through the composition hook, not through `AuthService`."""

    auth_source = (SRC / "shared" / "auth" / "service.py").read_text()
    assert "Memory" not in auth_source
    assert "sidekick.memory" not in auth_source
    memory_application = sorted((SRC / "memory" / "application").glob("*.py"))
    assert memory_application
    for path in memory_application:
        assert _imports_package(_all_imports(path), "sidekick.shared.persistence") == [], path.name


def _absolute_module(path: Path, node: ast.ImportFrom) -> str:
    """The absolute module an `ImportFrom` names; relative imports resolve against `path`."""

    if node.level == 0:
        return node.module or ""
    package = ["sidekick", *path.relative_to(SRC).parts[:-1]]
    base = package[: len(package) - (node.level - 1)]
    return ".".join([*base, *([node.module] if node.module else [])])


def _runtime_imports(path: Path) -> set[str]:
    """Modules imported at run time: imports outside an `if TYPE_CHECKING:` block."""

    tree = ast.parse(path.read_text())
    type_checking = {
        id(node)
        for block in ast.walk(tree)
        if isinstance(block, ast.If)
        and isinstance(block.test, ast.Name)
        and block.test.id == "TYPE_CHECKING"
        for node in ast.walk(block)
    }
    found: set[str] = set()
    for node in ast.walk(tree):
        if id(node) in type_checking:
            continue
        if isinstance(node, ast.ImportFrom):
            module = _absolute_module(path, node)
            if module:
                found.add(module)
                found.update(f"{module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


def _all_imports(path: Path) -> set[str]:
    """Every module imported, also inside `if TYPE_CHECKING:` blocks and function bodies."""

    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom):
            module = _absolute_module(path, node)
            if module:
                found.add(module)
                found.update(f"{module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


def _imports_package(modules: set[str], package: str) -> list[str]:
    return sorted(m for m in modules if m == package or m.startswith(f"{package}."))


def _persistence_imports(modules: set[str]) -> list[str]:
    """SQLAlchemy, the shared persistence package, and any context's own `persistence` module."""

    found = {m for p in PERSISTENCE_PACKAGES for m in _imports_package(modules, p)}
    found.update(m for m in modules if m.startswith("sidekick.") and "persistence" in m.split("."))
    return sorted(found)


def test_the_companion_routes_do_not_import_the_mcp_layer() -> None:
    for path in sorted((SRC / "api").glob("companion*.py")):
        assert _imports_package(_runtime_imports(path), "sidekick.mcp") == [], path.name


def test_the_shared_structured_layer_imports_neither_interface() -> None:
    paths = sorted((SRC / "structured").glob("*.py"))
    assert paths
    for path in paths:
        imports = _runtime_imports(path)
        assert _imports_package(imports, "sidekick.mcp") == [], path.name
        assert _imports_package(imports, "sidekick.api") == [], path.name


def test_nothing_outside_the_api_imports_it_not_even_for_types() -> None:
    offenders: dict[str, list[str]] = {}
    for path in sorted(SRC.rglob("*.py")):
        relative = path.relative_to(SRC)
        if relative.parts[0] == "api" or relative.as_posix() in API_IMPORT_EXCEPTIONS:
            continue
        found = _imports_package(_all_imports(path), "sidekick.api")
        if found:
            offenders[relative.as_posix()] = found
    assert offenders == {}


def test_the_mcp_layer_never_imports_the_api() -> None:
    paths = sorted((SRC / "mcp").glob("*.py"))
    assert paths
    for path in paths:
        assert _imports_package(_all_imports(path), "sidekick.api") == [], path.name


def test_the_composition_root_imports_neither_interface() -> None:
    imports = _all_imports(SRC / "composition.py")
    assert _imports_package(imports, "sidekick.api") == []
    assert _imports_package(imports, "sidekick.mcp") == []


def test_the_api_reexports_the_composition_symbols() -> None:
    from sidekick import composition
    from sidekick.api import app

    assert app.Container is composition.Container
    assert app.create_container is composition.create_container


def _application_imports(path: Path) -> list[str]:
    """Imports of any `sidekick.<domain>.application` package, absolute or relative."""

    found = sorted(
        module
        for module in _all_imports(path)
        if module.startswith("sidekick.") and ".application" in module
    )
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.level > 0:
            names = [node.module or "", *(alias.name for alias in node.names)]
            if any(part == "application" for name in names for part in name.split(".")):
                found.append(f"{'.' * node.level}{node.module or ''}")
    return found


def test_persistence_adapters_never_import_an_application_package() -> None:
    paths = sorted((SRC / "shared" / "persistence").rglob("*.py"))
    assert paths
    offenders = {path.name: _application_imports(path) for path in paths}
    assert {name: found for name, found in offenders.items() if found} == {}


def test_domain_packages_never_import_an_application_package() -> None:
    paths = sorted(SRC.glob("*/domain/**/*.py")) + sorted(SRC.glob("*/domain.py"))
    assert paths
    offenders = {str(path.relative_to(SRC)): _application_imports(path) for path in paths}
    assert {name: found for name, found in offenders.items() if found} == {}


def test_the_transport_layers_import_no_sql_and_no_persistence_package() -> None:
    offenders: dict[str, list[str]] = {}
    for layer in ("api", "mcp"):
        paths = sorted((SRC / layer).rglob("*.py"))
        assert paths
        for path in paths:
            relative = path.relative_to(SRC).as_posix()
            if relative in TRANSPORT_PERSISTENCE_EXCEPTIONS:
                continue
            found = _persistence_imports(_all_imports(path))
            if found:
                offenders[relative] = found
    assert offenders == {}


def test_the_transport_persistence_exceptions_are_real_and_explained() -> None:
    for relative, reason in TRANSPORT_PERSISTENCE_EXCEPTIONS.items():
        assert reason.strip(), relative
        imports = _all_imports(SRC / relative)
        assert _persistence_imports(imports), relative


def _application_modules() -> list[Path]:
    paths = sorted(SRC.glob("*/application/**/*.py"))
    assert paths
    return paths


def test_the_application_packages_import_no_persistence_package() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _application_modules():
        relative = path.relative_to(SRC).as_posix()
        if relative in APPLICATION_PERSISTENCE_EXCEPTIONS:
            continue
        found = _imports_package(_all_imports(path), "sidekick.shared.persistence")
        if found:
            offenders[relative] = found
    assert offenders == {}


def test_the_application_persistence_exceptions_are_real_and_explained() -> None:
    for relative, reason in APPLICATION_PERSISTENCE_EXCEPTIONS.items():
        assert reason.strip(), relative
        imports = _all_imports(SRC / relative)
        assert _imports_package(imports, "sidekick.shared.persistence"), relative


def test_relative_imports_are_resolved_to_absolute_modules() -> None:
    """`from ..mcp import x` inside `sidekick.structured` counts as an import of `sidekick.mcp`."""

    module = SRC / "structured" / "_probe.py"
    source = "from ..mcp import tools\nfrom . import records\nfrom ...outside import y\n"
    tree = ast.parse(source)
    nodes = [n for n in tree.body if isinstance(n, ast.ImportFrom)]
    assert [_absolute_module(module, n) for n in nodes] == [
        "sidekick.mcp",
        "sidekick.structured",
        "outside",
    ]
