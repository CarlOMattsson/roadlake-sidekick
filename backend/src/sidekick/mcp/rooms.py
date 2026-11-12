"""Which room each MCP tool belongs to, and what a room that is switched off takes away.

`SIDEKICK_ENABLED_ROOMS` (sidekick.shared.rooms) lets an instance show some rooms only. For the MCP
surface a switched-off room means two things, both applied by `create_mcp_server`:

- its tools are not registered, so the model cannot read or write what the owner cannot see;
- its scopes are taken off the actor, so the tools that look across rooms (`search`,
  `get_today_brief`, `recall_memory`, the trash and the change list) leave that room's records out
  the way they do for a session that never held the scope.

`ROOM_TOOLS` is the one place that says where a tool belongs. A test requires every tool in the
curated contract to be listed here, so a new tool cannot be added without choosing its room.

Tools that read across rooms stay with `work` (`search`, `get_today_brief`, `recall_memory`) and
narrow themselves by scope. The trash tools stay with `work` so that an instance with Arbete only
can delete and undo; the Papperskorg view itself is Kontroll's. The change list, the memory
settings and the assistant activity are what Kontroll shows, so they belong to `control`.
"""

from collections.abc import Callable, Collection, Mapping
from typing import Final

from fastmcp import FastMCP

from sidekick.shared.rooms import Room, disabled_scopes
from sidekick.shared.types import Actor

ROOM_TOOLS: Final[Mapping[Room, tuple[str, ...]]] = {
    "work": (
        "list_projects",
        "get_project",
        "create_project",
        "update_project",
        "list_domains",
        "get_domain",
        "create_domain",
        "update_domain",
        "list_processes",
        "get_process",
        "create_process",
        "update_process",
        "list_tasks",
        "get_task",
        "create_task",
        "create_tasks",
        "update_task",
        "complete_task",
        "reschedule_tasks",
        "list_task_steps",
        "create_task_step",
        "update_task_step",
        "complete_task_step",
        "archive_task_step",
        "restore_task_step",
        "reorder_task_steps",
        "list_step_actions",
        "create_step_action",
        "update_step_action",
        "complete_step_action",
        "archive_step_action",
        "restore_step_action",
        "reorder_step_actions",
        "list_tags",
        "get_work_agenda",
        "get_work_board",
        "get_work_hierarchy",
        "reorder_work_board_column",
        "show_work_changes",
        "list_saved_work_views",
        "create_saved_work_view",
        "update_saved_work_view",
        "archive_saved_work_view",
        "restore_saved_work_view",
        "list_task_external_references",
        "link_external_reference_to_task",
        "unlink_external_reference_from_task",
        # Across rooms; each narrows itself to the rooms that are on.
        "get_today_brief",
        "search",
        "recall_memory",
        # The instance's license key (D-081): the owner's own, and not tied to a room's data.
        "set_license_key",
        # The trash: a Work-only instance still lets Claude delete and undo. Records of an off room
        # are skipped through the narrowed scopes.
        "list_trash",
        "move_to_trash",
        "restore_from_trash",
    ),
    "journal": (
        "list_journal_entries",
        "get_journal_entry",
        "get_journal_day",
        "get_daily_journal_summary",
        "get_journal_source",
        "list_pending_journal",
        "create_journal_source",
        "create_manual_journal_entry",
        "write_journal_entry",
        "update_journal_entry",
        "set_daily_journal_summary",
        "get_journal_draft",
        "update_journal_draft",
        "reject_journal_draft",
        "finalize_journal_draft",
    ),
    "shopping": (
        "list_shopping_lists",
        "get_shopping_list",
        "create_shopping_list",
        "update_shopping_list",
        "add_shopping_items",
        "update_shopping_item",
        "set_shopping_item_purchased",
        "set_shopping_items_purchased",
    ),
    "contacts": (
        "list_contacts",
        "get_contact_context",
        "create_contact",
        "update_contact",
        "archive_contact",
        "restore_contact",
        "add_contact_alias",
        "remove_contact_alias",
        "link_contact_to_project",
        "unlink_contact_from_project",
        "link_contact_to_task",
        "unlink_contact_from_task",
        "list_task_contacts",
    ),
    "control": (
        "list_recent_changes",
        "list_assistant_activity",
        "get_memory_status",
        "set_memory_settings",
        "exclude_from_memory",
    ),
}

TOOL_ROOM: Final[Mapping[str, Room]] = {
    tool: room for room, tools in ROOM_TOOLS.items() for tool in tools
}
if len(TOOL_ROOM) != sum(len(tools) for tools in ROOM_TOOLS.values()):
    raise RuntimeError("a tool is listed under two rooms in ROOM_TOOLS")


def tool_is_enabled(tool: str, enabled: Collection[str]) -> bool:
    """False only for a tool of a room that is switched off. A tool outside the table is kept."""

    room = TOOL_ROOM.get(tool)
    return room is None or room in enabled


def remove_disabled_room_tools(mcp: FastMCP, enabled: Collection[str]) -> None:
    """Unregister the tools of every room that is switched off. Nothing to do with all rooms on."""

    for room, tools in ROOM_TOOLS.items():
        if room not in enabled:
            for tool in tools:
                mcp.local_provider.remove_tool(tool)


def room_actor_provider(
    actor_provider: Callable[[], Actor], enabled: Collection[str]
) -> Callable[[], Actor]:
    """The provider itself with all rooms on; else its actor minus the scopes of the off rooms."""

    off = disabled_scopes(enabled)
    if not off:
        return actor_provider

    def narrowed() -> Actor:
        actor = actor_provider()
        return Actor(actor.user_id, actor.scopes - off)

    return narrowed
