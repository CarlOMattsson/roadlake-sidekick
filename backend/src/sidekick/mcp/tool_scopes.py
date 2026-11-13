"""The scopes each curated MCP tool needs, in one table the tool reference is generated from.

The server enforces scopes in the application use cases (`Actor.require`) and, for the reply of a
write tool, in `sidekick.mcp.reply_scopes`. This module names them per tool so that
`docs/reference/mcp` does not carry a hand-written copy:

- `requires`: every one of these scopes, or the call is refused. The read scope of a write tool's
  reply is not typed here; it comes from `WRITE_REPLY_READ_SCOPES`, which the server enforces.
- `any_of`: at least one of these, because the tool works per kind of record and answers with the
  kinds the session can read (search, memory, trash). The sets come from the mappings the use cases
  use (`search.domain.KIND_SCOPE`, `memory.application.recall.KIND_READ_SCOPE`,
  `lifecycle.application.service.READ_SCOPES`), not from a copy.
- `optional`: extra scopes that widen the answer (a part is left out without them) or that some
  arguments need (linking contacts to a task needs `contacts:write`).

A contract test requires every tool in `contracts/mcp-tools.generated.json` to be in the table, and
`tests/contract/test_mcp_tool_scope_table.py` calls every tool against a real server and checks the
table against what the server refuses.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final

from sidekick.lifecycle.application.service import CHANGE_SCOPES, READ_SCOPES, WRITE_SCOPES
from sidekick.mcp.reply_scopes import WRITE_REPLY_READ_SCOPES
from sidekick.memory.application.recall import KIND_READ_SCOPE as MEMORY_READ_SCOPE
from sidekick.memory.application.settings import DOMAIN_WRITE_SCOPE
from sidekick.search.domain import KIND_SCOPE as SEARCH_SCOPE


@dataclass(frozen=True, slots=True)
class ToolScopes:
    requires: tuple[str, ...] = ()
    any_of: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()

    def everything(self) -> frozenset[str]:
        """Every scope the table names for the tool; a session with all of them is never refused."""
        return frozenset((*self.requires, *self.any_of, *self.optional))


def _sorted(scopes: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(scopes)))


def _tools(scopes: ToolScopes, *names: str) -> dict[str, ToolScopes]:
    return dict.fromkeys(names, scopes)


_JOURNAL_RELATED_READS: Final = ("contacts:read", "projects:read", "tasks:read")

# What each tool needs for itself. A write tool's reply scope is added by `_with_reply_scope`.
_OWN_SCOPES: Final[Mapping[str, ToolScopes]] = {
    # Work: Tasks. Their reply and listing name the Project, so `projects:read` comes with them.
    **_tools(ToolScopes(("projects:read", "tasks:read")), "list_tasks", "get_task"),
    "create_task": ToolScopes(("projects:read", "tasks:write"), optional=("contacts:write",)),
    **_tools(
        ToolScopes(("projects:read", "tasks:write")), "create_tasks", "update_task", "complete_task"
    ),
    **_tools(ToolScopes(("tasks:write",)), "reschedule_tasks", "reorder_work_board_column"),
    **_tools(
        ToolScopes(("tasks:read",)),
        "get_work_board",
        "get_work_agenda",
        "list_task_steps",
        "list_step_actions",
        "list_task_external_references",
        "list_assistant_activity",
    ),
    **_tools(
        ToolScopes(("tasks:write",)),
        "create_task_step",
        "update_task_step",
        "complete_task_step",
        "archive_task_step",
        "restore_task_step",
        "reorder_task_steps",
        "create_step_action",
        "update_step_action",
        "complete_step_action",
        "archive_step_action",
        "restore_step_action",
        "reorder_step_actions",
        "link_external_reference_to_task",
        "unlink_external_reference_from_task",
    ),
    # The instance's license key (D-081: offline signed license keys) is an administrative change
    # with a scope of its own.
    "set_license_key": ToolScopes(("license:write",)),
    # Work: Projects, Domains, Processes, tags and saved views.
    **_tools(
        ToolScopes(("projects:read",)),
        "get_work_hierarchy",
        "list_domains",
        "get_domain",
        "list_processes",
        "get_process",
        "list_projects",
        "get_project",
        "list_tags",
        "list_saved_work_views",
        "show_work_changes",
    ),
    **_tools(
        ToolScopes(("projects:write",)),
        "create_domain",
        "update_domain",
        "create_process",
        "update_process",
        "create_project",
        "update_project",
        "create_saved_work_view",
        "update_saved_work_view",
        "archive_saved_work_view",
        "restore_saved_work_view",
    ),
    # Contacts.
    **_tools(ToolScopes(("contacts:read",)), "list_contacts"),
    **_tools(ToolScopes(("contacts:read", "projects:read", "tasks:read")), "get_contact_context"),
    **_tools(ToolScopes(("contacts:read", "tasks:read")), "list_task_contacts"),
    **_tools(
        ToolScopes(("contacts:write",)),
        "create_contact",
        "update_contact",
        "archive_contact",
        "restore_contact",
        "add_contact_alias",
        "remove_contact_alias",
    ),
    **_tools(
        ToolScopes(("contacts:write", "projects:read")),
        "link_contact_to_project",
        "unlink_contact_from_project",
    ),
    **_tools(
        ToolScopes(("contacts:write", "tasks:read")),
        "link_contact_to_task",
        "unlink_contact_from_task",
    ),
    # Journal.
    **_tools(
        ToolScopes(("journal:read",)),
        "list_journal_entries",
        "get_journal_entry",
        "get_journal_day",
        "get_daily_journal_summary",
        "get_journal_source",
        "list_pending_journal",
        "get_journal_draft",
    ),
    **_tools(
        ToolScopes(("journal:write",), optional=_JOURNAL_RELATED_READS),
        "create_manual_journal_entry",
        "write_journal_entry",
        "update_journal_entry",
    ),
    **_tools(ToolScopes(("journal:write",)), "create_journal_source", "set_daily_journal_summary"),
    **_tools(ToolScopes(("journal:write",)), "update_journal_draft", "reject_journal_draft"),
    **_tools(
        ToolScopes(("journal:write",), optional=(*_JOURNAL_RELATED_READS, "tasks:write")),
        "finalize_journal_draft",
    ),
    # Shopping.
    **_tools(ToolScopes(("shopping:read",)), "list_shopping_lists", "get_shopping_list"),
    **_tools(
        ToolScopes(("shopping:write",)),
        "create_shopping_list",
        "update_shopping_list",
        "add_shopping_items",
        "update_shopping_item",
        "set_shopping_item_purchased",
        "set_shopping_items_purchased",
    ),
    # Overview, search and memory: each answers with the parts the session can read.
    "get_today_brief": ToolScopes(optional=("journal:read", "shopping:read", "tasks:read")),
    "list_recent_changes": ToolScopes(optional=_sorted(CHANGE_SCOPES)),
    "search": ToolScopes(any_of=_sorted(SEARCH_SCOPE.values())),
    "recall_memory": ToolScopes(any_of=_sorted(MEMORY_READ_SCOPE.values())),
    "get_memory_status": ToolScopes(any_of=_sorted(MEMORY_READ_SCOPE.values())),
    "set_memory_settings": ToolScopes(any_of=_sorted(DOMAIN_WRITE_SCOPE.values())),
    "exclude_from_memory": ToolScopes(any_of=_sorted(DOMAIN_WRITE_SCOPE.values())),
    # The trash works per kind of record.
    "list_trash": ToolScopes(any_of=_sorted(READ_SCOPES)),
    "move_to_trash": ToolScopes(any_of=_sorted(WRITE_SCOPES)),
    "restore_from_trash": ToolScopes(any_of=_sorted(WRITE_SCOPES)),
}


def _with_reply_scope(name: str, own: ToolScopes) -> ToolScopes:
    """Adds the read scope the server demands for the reply of a write tool."""
    reply = WRITE_REPLY_READ_SCOPES.get(name)
    if reply is None or reply in own.requires:
        return own
    return ToolScopes(_sorted((*own.requires, reply)), own.any_of, own.optional)


TOOL_SCOPES: Final[Mapping[str, ToolScopes]] = {
    name: _with_reply_scope(name, own) for name, own in _OWN_SCOPES.items()
}


def describe(scopes: ToolScopes) -> str:
    """The scopes of one tool as a Markdown sentence."""

    def names(items: Iterable[str]) -> str:
        return ", ".join(f"`{item}`" for item in items)

    parts: list[str] = []
    if scopes.requires:
        parts.append(f"requires {names(scopes.requires)}")
    if scopes.any_of:
        parts.append(f"requires at least one of {names(scopes.any_of)}")
    if scopes.optional and (scopes.requires or scopes.any_of):
        parts.append(f"some arguments or parts of the answer also use {names(scopes.optional)}")
    elif scopes.optional:
        parts.append(
            f"requires no single scope; the answer holds only the parts "
            f"whose read scope the session has ({names(scopes.optional)})"
        )
    return "; ".join(parts) if parts else "none"
