"""Support for the cross-owner isolation tests: two seeded owners, the schema walk that finds every
identifier a tool accepts, and the digest of one owner's rows.

Nothing here asserts. `tests/contract/test_cross_owner_isolation.py` does.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID, uuid4

from fastmcp import Client
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from sidekick.api.app import Container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.auth import MCP_SCOPES
from sidekick.shared.types import Actor
from tests.support.journal_drafts import seed_entry_draft

JOURNAL_DATE = "2026-07-21"
ALL_SCOPES = frozenset(MCP_SCOPES)

# Every title, name and text of an owner starts with its marker, so a response that holds the
# other owner's marker holds the other owner's data. Queries use the marker word as well.
MARKER_A = "alphasecret"
MARKER_B = "bravoown"

# The identifier parameter names, and the kind of seeded record each one points at.
NAME_KIND: dict[str, str] = {
    "task_id": "task",
    "task_ids": "task",
    "project_id": "project",
    "project_ids": "project",
    "add_project_ids": "project",
    "remove_project_ids": "project",
    "domain_id": "domain",
    "process_id": "process",
    "contact_id": "contact",
    "contact_ids": "contact",
    "add_contact_ids": "contact",
    "remove_contact_ids": "contact",
    "waiting_on_contact_id": "contact",
    "recipient_contact_id": "contact",
    "entry_id": "entry",
    "source_id": "source",
    "replaces_source_id": "source",
    "draft_id": "draft",
    "list_id": "list",
    "item_id": "item",
    "step_id": "step",
    "action_id": "action",
    "alias_id": "alias",
    "view_id": "view",
    "reference_id": "reference",
}
# `kind` enum values (trash, memory exclusion, change refs) to the seeded kind they address.
ENUM_KIND: dict[str, str] = {"journal_entry": "entry", "shopping_item": "item"}
# A bare `id` or `record_id` takes its kind from a sibling `kind`, else from the nearest
# `*_ids` ancestor, else from the tool.
TOOL_ID_KIND: dict[str, str] = {"reorder_task_steps": "step", "reorder_step_actions": "action"}
# Not references: free text or opaque keys that merely end in `_id`.
NOT_A_REFERENCE = frozenset({"external_id", "idempotency_key", "client_ref", "account_ref"})
# Tools that act on a record only once it is in the trash.
TRASHED_TOOLS = frozenset({"restore_from_trash"})

VERSIONED = frozenset(
    {
        "domain",
        "process",
        "project",
        "task",
        "contact",
        "entry",
        "draft",
        "list",
        "item",
        "step",
        "action",
        "view",
        "reference",
    }
)
TRASHABLE = ("domain", "process", "project", "task", "step", "action", "contact", "entry", "item")


@dataclass(frozen=True, slots=True)
class Record:
    id: str
    version: int | None


@dataclass
class OwnerSeed:
    name: str
    marker: str
    user_id: UUID
    records: dict[str, Record] = field(default_factory=dict)

    @property
    def actor(self) -> Actor:
        return Actor(self.user_id, ALL_SCOPES)

    @property
    def needles(self) -> list[str]:
        """What marks a text as this owner's: labels are `<marker> <kind>`, tags `<marker>tag`."""

        return [f"{self.marker} ", f"{self.marker}tag"]

    def ids(self) -> set[str]:
        return {record.id for record in self.records.values()}


def enum_for(kind: str) -> str:
    """The `kind` enum value that addresses a seeded kind (the reverse of `ENUM_KIND`)."""

    return {value: key for key, value in ENUM_KIND.items()}.get(kind, kind)


async def seed_owner(container: Container, name: str, marker: str) -> OwnerSeed:
    """One record of every kind, made through the tools with every scope, plus one trashed
    record of each trashable kind (key `trashed_<kind>`)."""

    user_id = container.auth.provision_user(name, name.title())
    seed = OwnerSeed(name, marker, user_id)
    seed_actor = seed.actor
    counter = itertools.count()
    server = create_mcp_server(container, actor_provider=lambda: seed_actor, enable_auth=False)

    async with Client(server) as client:

        async def call(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
            arguments = {**arguments, "idempotency_key": f"{name}-{next(counter)}-{uuid4().hex}"}
            result = await client.call_tool(tool, arguments)
            return result.structured_content or {}

        def label(kind: str) -> str:
            return f"{marker} {kind}"

        async def make_domain(text_: str) -> dict[str, Any]:
            return (
                await call("create_domain", {"name": label(text_), "description": label(text_)})
            )["domain"]

        async def make(kind: str) -> Record:
            """A fresh record of `kind` on its own parent chain."""

            if kind == "domain":
                item = await make_domain("domain")
            elif kind == "process":
                parent = await make_domain("domain of process")
                created = await call(
                    "create_process", {"domain_id": parent["id"], "name": label("process")}
                )
                item = created["process"]
            elif kind == "project":
                parent = await make_domain("domain of project")
                created = await call(
                    "create_project",
                    {
                        "domain_id": parent["id"],
                        "title": label("project"),
                        "description": label("project"),
                    },
                )
                item = created["project"]
            elif kind == "task":
                item = (await call("create_task", {"title": label("task")}))["task"]
            elif kind == "step":
                task = await make("task")
                created = await call(
                    "create_task_step", {"task_id": task.id, "title": label("step")}
                )
                item = created["step"]
            elif kind == "action":
                step = await make("step")
                created = await call(
                    "create_step_action", {"step_id": step.id, "title": label("action")}
                )
                item = created["action"]
            elif kind == "contact":
                created = await call("create_contact", {"display_name": label("contact")})
                item = created["contact"]
            elif kind == "entry":
                created = await call(
                    "write_journal_entry",
                    {
                        "journal_date": JOURNAL_DATE,
                        "title": label("entry"),
                        "source_text": label("entry source"),
                        "summary": label("entry summary"),
                    },
                )
                item = created["entry"]
            elif kind == "list":
                item = (await call("create_shopping_list", {"name": label("list")}))[
                    "shopping_list"
                ]
            elif kind == "item":
                shopping_list = await make("list")
                added = await call(
                    "add_shopping_items",
                    {
                        "list_id": shopping_list.id,
                        "items": [{"name": label("item"), "client_ref": "ref-1"}],
                    },
                )
                item = added["items"][0]["item"]
            else:
                raise AssertionError(kind)
            return Record(item["id"], item.get("version"))

        for kind in ("domain", "process", "project", "contact", "entry", "list", "item"):
            seed.records[kind] = await make(kind)
        # A task inside the project, with a tag, a contact, a step, an action and a reference.
        task = (
            await call(
                "create_task",
                {
                    "title": label("task"),
                    "description": label("task description"),
                    "project_id": seed.records["project"].id,
                    "tags": [f"{marker}tag"],
                    "contact_ids": [seed.records["contact"].id],
                },
            )
        )["task"]
        seed.records["task"] = Record(task["id"], task["version"])
        # More of what is listed, so a list tool has a second page for a cursor to point at.
        for index in range(2):
            await call(
                "create_task",
                {"title": label(f"task {index}"), "project_id": seed.records["project"].id},
            )
            await call(
                "create_project",
                {"domain_id": seed.records["domain"].id, "title": label(f"project {index}")},
            )
            await call("create_contact", {"display_name": label(f"contact {index}")})
            await call("create_shopping_list", {"name": label(f"list {index}")})
            await call(
                "write_journal_entry",
                {
                    "journal_date": JOURNAL_DATE,
                    "title": label(f"entry {index}"),
                    "source_text": label(f"entry source {index}"),
                },
            )
        step = (await call("create_task_step", {"task_id": task["id"], "title": label("step")}))[
            "step"
        ]
        seed.records["step"] = Record(step["id"], step["version"])
        action = (
            await call("create_step_action", {"step_id": step["id"], "title": label("action")})
        )["action"]
        seed.records["action"] = Record(action["id"], action["version"])
        contact = seed.records["contact"]
        aliased = (
            await call(
                "add_contact_alias",
                {
                    "contact_id": contact.id,
                    "value": label("alias"),
                    "expected_version": contact.version,
                },
            )
        )["contact"]
        seed.records["contact"] = Record(contact.id, aliased["version"])
        seed.records["alias"] = Record(aliased["aliases"][0]["id"], None)
        reference = (
            await call(
                "link_external_reference_to_task",
                {
                    "task_id": task["id"],
                    "kind": "mail",
                    "provider": "other",
                    "account_ref": label("account"),
                    "external_id": label("external"),
                    "title": label("reference"),
                },
            )
        )["reference"]
        seed.records["reference"] = Record(reference["id"], reference["version"])
        view = (
            await call(
                "create_saved_work_view",
                {"name": label("view"), "definition": {"view": "list", "context": "all"}},
            )
        )["saved_view"]
        seed.records["view"] = Record(view["id"], view["version"])
        source = (
            await call(
                "create_journal_source",
                {
                    "source_type": "manual_text",
                    "journal_date": JOURNAL_DATE,
                    "raw_text": label("draft source"),
                },
            )
        )["source"]
        seed.records["source"] = Record(source["id"], None)
        draft_id = seed_entry_draft(
            container, seed_actor, UUID(source["id"]), date.fromisoformat(JOURNAL_DATE)
        )
        read = await client.call_tool("get_journal_draft", {"draft_id": str(draft_id)})
        assert read.structured_content is not None
        seed.records["draft"] = Record(str(draft_id), read.structured_content["draft"]["version"])
        # A trashed record of each trashable kind.
        for kind in TRASHABLE:
            record = await make(kind)
            trashed = await call(
                "move_to_trash",
                {"kind": enum_for(kind), "record_id": record.id, "version": record.version},
            )
            seed.records[f"trashed_{kind}"] = Record(record.id, trashed["version"])
    return seed


# --- the schema walk ---------------------------------------------------------------------------


def is_reference_name(name: str) -> bool:
    if name in NOT_A_REFERENCE:
        return False
    return name.endswith(("_id", "_ids")) or name in ("id", "record_id")


Path = tuple[str | int, ...]


@dataclass(frozen=True, slots=True)
class Slot:
    """One place in a tool's arguments that names a record of some kind."""

    path: Path
    kind: str

    @property
    def label(self) -> str:
        return ".".join(str(part) for part in self.path) + f"[{self.kind}]"


# What a slot is filled with: the id of a record and its version.
Reference = Callable[[Slot], tuple[str, int | None]]
Local = list[tuple[str, int | None]]


def _merge(base: Any, extra: Any) -> Any:
    if isinstance(base, dict) and isinstance(extra, dict):
        return {**base, **{key: _merge(base.get(key), value) for key, value in extra.items()}}
    return extra


class ToolShape:
    """The arguments of one tool, generated from its input schema.

    Required fields get a minimal valid value; every property that names a record (`*_id`,
    `*_ids`, `id`, `record_id`) is included wherever it sits, nested or not, and filled by the
    caller through `Reference`. A bare `id` takes its kind from a sibling `kind` enum, which
    `kind_choices` enumerates.
    """

    def __init__(self, tool: str, schema: dict[str, Any]):
        self.tool = tool
        self.root = schema
        self._only: Slot | None = None

    # -- schema helpers
    def _resolve(self, schema: dict[str, Any]) -> dict[str, Any]:
        while "$ref" in schema:
            schema = self.root["$defs"][schema["$ref"].rsplit("/", 1)[-1]]
        for key in ("anyOf", "oneOf"):
            if key in schema:
                options = [o for o in schema[key] if o.get("type") != "null"]
                return self._resolve(options[0])
        return schema

    def _holds_reference(self, schema: dict[str, Any]) -> bool:
        schema = self._resolve(schema)
        if schema.get("type") == "array":
            return self._holds_reference(schema["items"])
        if schema.get("type") == "object":
            return any(
                is_reference_name(name) or self._holds_reference(sub)
                for name, sub in schema.get("properties", {}).items()
            )
        return False

    def _plain_text(self, properties: dict[str, Any]) -> str | None:
        """The first property that takes any text, to make an otherwise empty object a change."""

        for name, sub in properties.items():
            resolved = self._resolve(sub)
            if resolved.get("type") == "string" and not (
                {"format", "pattern", "enum"} & set(resolved)
            ):
                return name
        return None

    def _wanted(self, path: Path) -> bool:
        """Whether an optional property is in the call: all of them, or only the way to `only`."""

        return self._only is None or self._only.path[: len(path)] == path

    def _is_one_of(self, schema: dict[str, Any]) -> bool:
        if "$ref" in schema:
            schema = self.root["$defs"][schema["$ref"].rsplit("/", 1)[-1]]
        return "oneOf" in schema

    # -- kind choices
    def kind_choices(self) -> list[dict[Path, str]]:
        fields: list[tuple[Path, list[str]]] = []

        def walk(schema: dict[str, Any], path: Path) -> None:
            schema = self._resolve(schema)
            if schema.get("type") == "object":
                properties = schema.get("properties", {})
                if "kind" in properties and ("id" in properties or "record_id" in properties):
                    options = list(self._resolve(properties["kind"])["enum"])
                    fields.append(((*path, "kind"), options))
                for name, sub in properties.items():
                    walk(sub, (*path, name))
            elif schema.get("type") == "array":
                walk(schema["items"], (*path, 0))

        walk(self.root, ())
        if not fields:
            return [{}]
        paths = [path for path, _ in fields]
        return [
            dict(zip(paths, values, strict=True))
            for values in itertools.product(*(options for _, options in fields))
        ]

    # -- generation
    def arguments(
        self,
        choice: dict[Path, str],
        reference: Reference,
        only: Slot | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """The call. With `only`, the optional references other than that slot are left out, so a
        refusal cannot come from one of the others (a Task has one context, a link is not both
        added and removed). `extra` is merged over the result to make the call well formed."""

        self._only = only
        built = self._object(self.root, (), (), True, choice, reference)
        return _merge(built, extra or {})  # type: ignore[no-any-return]

    def slots(self, choice: dict[Path, str]) -> list[Slot]:
        found: list[Slot] = []

        def record(slot: Slot) -> tuple[str, int | None]:
            found.append(slot)
            return str(uuid4()), 1

        self.arguments(choice, record)
        return found

    def _object(
        self,
        schema: dict[str, Any],
        path: Path,
        parents: tuple[str, ...],
        top: bool,
        choice: dict[Path, str],
        reference: Reference,
    ) -> dict[str, Any]:
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        names = [name for name in properties if name in required]
        names += [
            name
            for name, sub in properties.items()
            if name not in names
            and (is_reference_name(name) or self._holds_reference(sub))
            and self._wanted((*path, name))
        ]
        if not names and not top:
            names = [self._plain_text(properties) or next(iter(properties))]
        value: dict[str, Any] = {}
        local: Local = []
        for name in names:
            if name in ("version", "expected_version"):
                continue
            value[name] = self._value(
                properties[name], (*path, name), (*parents, name), name, properties, choice,
                reference, local,
            )  # fmt: skip
        for name in ("version", "expected_version"):
            if name in properties:
                value[name] = next((v for _, v in local if v is not None), 1)
        return value

    def _value(
        self,
        schema: dict[str, Any],
        path: Path,
        parents: tuple[str, ...],
        key: str,
        siblings: dict[str, Any],
        choice: dict[Path, str],
        reference: Reference,
        local: Local,
    ) -> Any:
        one_of = self._is_one_of(schema)
        schema = self._resolve(schema)
        if is_reference_name(key) and schema.get("type") == "string":
            return self._reference(key, path, parents, siblings, choice, reference, local)
        if "enum" in schema:
            return choice.get(path, schema["enum"][0])
        kind = schema.get("type")
        if kind == "object":
            return self._object(schema, path, parents, False, choice, reference)
        if kind == "array":
            raw_items = schema["items"]
            items = self._resolve(raw_items)
            if one_of or self._is_one_of(raw_items):
                return []
            if is_reference_name(key) and items.get("type") == "string":
                return [
                    self._reference(key, (*path, 0), parents, siblings, choice, reference, local)
                ]
            if schema.get("minItems", 0) or self._holds_reference(items):
                return [
                    self._value(
                        raw_items, (*path, 0), parents, key, siblings, choice, reference, []
                    )
                ]
            return []
        if kind == "integer":
            return max(1, schema.get("minimum", 1))
        if kind == "boolean":
            return True
        formats = {"uuid": str(uuid4()), "date": JOURNAL_DATE, "date-time": "2026-01-01T00:00:00Z"}
        if schema.get("format") in formats:
            return formats[schema["format"]]
        if schema.get("pattern") == "^[0-9a-f]{64}$":
            return "a" * 64
        if key in ("query", "q"):
            return MARKER_A
        return "x" * max(8, schema.get("minLength", 1))

    def _reference(
        self,
        key: str,
        path: Path,
        parents: tuple[str, ...],
        siblings: dict[str, Any],
        choice: dict[Path, str],
        reference: Reference,
        local: Local,
    ) -> str:
        if key in ("id", "record_id") and "kind" in siblings:
            kind_path = (*path[:-1], "kind")
            enum_value = choice.get(kind_path) or self._resolve(siblings["kind"])["enum"][0]
            kind = ENUM_KIND.get(enum_value, enum_value)
        elif key in ("id", "record_id"):
            kind = next(
                (NAME_KIND[parent] for parent in reversed(parents) if parent in NAME_KIND),
                TOOL_ID_KIND.get(self.tool, ""),
            )
        else:
            kind = NAME_KIND.get(key, "")
        record_id, version = reference(Slot(path, kind))
        local.append((record_id, version if kind in VERSIONED else None))
        return record_id


# --- one owner's rows --------------------------------------------------------------------------

_OWNER_COLUMNS = ("owner_id", "actor_id", "user_id")


def owner_tables(factory: sessionmaker[Session]) -> dict[str, str]:
    """Each table of the schema that names an owner, and the column that does."""

    with factory() as session:
        rows = session.execute(
            text(
                "SELECT t.tablename, c.column_name FROM pg_tables t "
                "JOIN information_schema.columns c ON c.table_schema = t.schemaname "
                "AND c.table_name = t.tablename AND c.column_name = ANY(:columns) "
                "WHERE t.schemaname = 'sidekick' ORDER BY t.tablename, c.ordinal_position"
            ),
            {"columns": list(_OWNER_COLUMNS)},
        ).all()
    tables: dict[str, str] = {}
    for table, column in rows:
        tables.setdefault(table, column)
    return tables


def owner_digest(
    factory: sessionmaker[Session], tables: dict[str, str], user_id: UUID
) -> dict[str, str]:
    """A digest of every row that belongs to `user_id`, per table."""

    digests: dict[str, str] = {}
    with factory() as session:
        for table, column in tables.items():
            digests[table] = session.execute(
                text(
                    "SELECT coalesce(md5(string_agg(t::text, '' ORDER BY t::text)), '') "
                    f'FROM sidekick."{table}" t WHERE t."{column}" = :owner'
                ),
                {"owner": user_id},
            ).scalar_one()
        digests["users"] = session.execute(
            text("SELECT md5(t::text) FROM sidekick.users t WHERE t.id = :owner"),
            {"owner": user_id},
        ).scalar_one()
    return digests


def whole_digest(factory: sessionmaker[Session]) -> dict[str, str]:
    """A digest of every row of every table."""

    digests: dict[str, str] = {}
    with factory() as session:
        names = session.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'sidekick' ORDER BY 1")
        ).scalars()
        for name in list(names):
            digests[name] = session.execute(
                text(
                    "SELECT coalesce(md5(string_agg(t::text, '' ORDER BY t::text)), '') "
                    f'FROM sidekick."{name}" t'
                )
            ).scalar_one()
    return digests


def strings_in(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings_in(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings_in(item)


def leaked(output: Any, other: OwnerSeed, supplied: Any) -> list[str]:
    """What of `other`'s data an answer holds: its marker, or an id the call did not hand it."""

    text_out = json.dumps(output, default=str)
    for given in set(strings_in(supplied)):
        if given in other.ids():
            text_out = text_out.replace(given, "")
    found = [needle for needle in other.needles if needle in text_out]
    found += sorted(
        f"{kind}:{record.id}" for kind, record in other.records.items() if record.id in text_out
    )
    return found
