"""The display title of every MCP tool, in each app language.

Tool names, descriptions and schemas are model-facing and stay as they are. Only the title, the
short name the host shows the user, follows `SIDEKICK_MCP_APP_LOCALE`. A tool has no `title=` of its
own: `LocalizeToolTitles` sets it from this table when the tools are listed, so Swedish and English
can never disagree about which tools exist. A new tool needs a row here (`test_tool_titles` fails
otherwise).
"""

from __future__ import annotations

from collections.abc import Sequence

from fastmcp.server.transforms import Transform
from fastmcp.tools import Tool
from mcp.types import ToolAnnotations

from sidekick.shared.locale import AppLocale, LocalizedText, localized

TOOL_TITLES: dict[str, LocalizedText] = {
    "list_contacts": {"sv": "Lista kontakter", "en": "List contacts"},
    "get_contact_context": {"sv": "Visa kontakt med sammanhang", "en": "View contact with context"},
    "list_task_contacts": {
        "sv": "Lista kontakter kopplade till uppgift",
        "en": "List task contacts",
    },
    "create_contact": {"sv": "Skapa kontakt", "en": "Create contact"},
    "update_contact": {"sv": "Ändra kontakt", "en": "Update contact"},
    "archive_contact": {"sv": "Arkivera kontakt", "en": "Archive contact"},
    "restore_contact": {"sv": "Återställ kontakt", "en": "Restore contact"},
    "add_contact_alias": {"sv": "Lägg till alias för kontakt", "en": "Add contact nickname"},
    "remove_contact_alias": {"sv": "Ta bort alias för kontakt", "en": "Remove contact nickname"},
    "link_contact_to_project": {
        "sv": "Koppla kontakt till projekt",
        "en": "Link contact to project",
    },
    "unlink_contact_from_project": {
        "sv": "Koppla bort kontakt från projekt",
        "en": "Unlink contact from project",
    },
    "link_contact_to_task": {"sv": "Koppla kontakt till uppgift", "en": "Link contact to task"},
    "unlink_contact_from_task": {
        "sv": "Koppla bort kontakt från uppgift",
        "en": "Unlink contact from task",
    },
    "list_journal_entries": {"sv": "Lista dagboksinlägg", "en": "List journal entries"},
    "get_journal_entry": {"sv": "Visa dagboksinlägg", "en": "View journal entry"},
    "get_journal_day": {"sv": "Visa dagboksdag", "en": "View journal day"},
    "get_daily_journal_summary": {"sv": "Visa dagboksammanfattning", "en": "View daily summary"},
    "get_journal_source": {"sv": "Visa dagbokskälla", "en": "View journal source"},
    "list_pending_journal": {
        "sv": "Lista dagbok som väntar på granskning",
        "en": "List journal items awaiting review",
    },
    "create_journal_source": {"sv": "Skapa dagboksunderlag", "en": "Create journal source"},
    "create_manual_journal_entry": {"sv": "Skapa dagboksinlägg", "en": "Create journal entry"},
    "write_journal_entry": {"sv": "Skriv dagbok", "en": "Write journal entry"},
    "update_journal_entry": {"sv": "Ändra dagboksinlägg", "en": "Update journal entry"},
    "set_daily_journal_summary": {"sv": "Skriv dagboksammanfattning", "en": "Write daily summary"},
    "get_journal_draft": {"sv": "Visa dagboksutkast", "en": "View journal draft"},
    "update_journal_draft": {"sv": "Ändra dagboksutkast", "en": "Update journal draft"},
    "reject_journal_draft": {"sv": "Avvisa dagboksutkast", "en": "Reject journal draft"},
    "finalize_journal_draft": {"sv": "Slutför dagboksutkast", "en": "Finalize journal draft"},
    "list_assistant_activity": {
        "sv": "Lista assistentens aktivitet",
        "en": "List assistant activity",
    },
    "list_shopping_lists": {"sv": "Lista inköpslistor", "en": "List shopping lists"},
    "get_shopping_list": {"sv": "Visa inköpslista", "en": "View shopping list"},
    "create_shopping_list": {"sv": "Skapa inköpslista", "en": "Create shopping list"},
    "update_shopping_list": {"sv": "Ändra inköpslista", "en": "Update shopping list"},
    "add_shopping_items": {
        "sv": "Lägg till varor i inköpslistan",
        "en": "Add items to shopping list",
    },
    "update_shopping_item": {"sv": "Ändra vara i inköpslistan", "en": "Update shopping item"},
    "set_shopping_item_purchased": {"sv": "Markera vara som köpt", "en": "Mark item as bought"},
    "set_shopping_items_purchased": {"sv": "Markera varor som köpta", "en": "Mark items as bought"},
    "list_trash": {"sv": "Lista papperskorgen", "en": "List trash"},
    "move_to_trash": {"sv": "Flytta till papperskorgen", "en": "Move to trash"},
    "restore_from_trash": {"sv": "Återställ från papperskorgen", "en": "Restore from trash"},
    "link_external_reference_to_task": {
        "sv": "Koppla extern referens till uppgift",
        "en": "Link reference to task",
    },
    "unlink_external_reference_from_task": {
        "sv": "Koppla bort extern referens från uppgift",
        "en": "Unlink reference from task",
    },
    "list_task_external_references": {
        "sv": "Lista externa referenser för uppgift",
        "en": "List task references",
    },
    "search": {"sv": "Sök på ord", "en": "Search by keyword"},
    "recall_memory": {"sv": "Sök i minnet", "en": "Search memory"},
    "get_memory_status": {"sv": "Visa minnesstatus", "en": "View memory status"},
    "set_memory_settings": {"sv": "Ändra minnesinställningar", "en": "Update memory settings"},
    "exclude_from_memory": {"sv": "Undanta från minnet", "en": "Exclude from memory"},
    "set_license_key": {"sv": "Ange licensnyckel", "en": "Enter license key"},
    "show_work_changes": {"sv": "Visa ändringar i arbetet", "en": "View work changes"},
    "get_today_brief": {"sv": "Dagens läge", "en": "Today\u2019s brief"},
    "list_recent_changes": {"sv": "Senaste ändringar", "en": "Recent changes"},
    "reschedule_tasks": {"sv": "Flytta uppgifter", "en": "Reschedule tasks"},
    "create_tasks": {"sv": "Skapa flera uppgifter", "en": "Create tasks"},
    "reorder_work_board_column": {"sv": "Ordna om tavlans kolumn", "en": "Reorder Status column"},
    "list_projects": {"sv": "Lista projekt", "en": "List projects"},
    "get_project": {"sv": "Visa projekt", "en": "View project"},
    "create_project": {"sv": "Skapa projekt", "en": "Create project"},
    "update_project": {"sv": "Ändra projekt", "en": "Update project"},
    "list_domains": {"sv": "Lista domäner", "en": "List areas"},
    "get_domain": {"sv": "Visa domän", "en": "View area"},
    "create_domain": {"sv": "Skapa domän", "en": "Create area"},
    "update_domain": {"sv": "Ändra domän", "en": "Update area"},
    "create_process": {"sv": "Skapa process", "en": "Create process"},
    "update_process": {"sv": "Ändra process", "en": "Update process"},
    "list_processes": {"sv": "Lista processer", "en": "List processes"},
    "get_process": {"sv": "Visa process", "en": "View process"},
    "list_task_steps": {"sv": "Lista steg för uppgift", "en": "List task steps"},
    "list_step_actions": {"sv": "Lista åtgärder för steg", "en": "List step actions"},
    "create_task_step": {"sv": "Skapa steg för uppgift", "en": "Create task step"},
    "create_step_action": {"sv": "Skapa åtgärd för steg", "en": "Create step action"},
    "update_task_step": {"sv": "Ändra steg", "en": "Update step"},
    "complete_task_step": {"sv": "Slutför steg", "en": "Complete step"},
    "archive_task_step": {"sv": "Arkivera steg", "en": "Archive step"},
    "restore_task_step": {"sv": "Återställ steg", "en": "Restore step"},
    "reorder_task_steps": {"sv": "Ordna om steg", "en": "Reorder steps"},
    "update_step_action": {"sv": "Ändra åtgärd", "en": "Update action"},
    "complete_step_action": {"sv": "Slutför åtgärd", "en": "Complete action"},
    "archive_step_action": {"sv": "Arkivera åtgärd", "en": "Archive action"},
    "restore_step_action": {"sv": "Återställ åtgärd", "en": "Restore action"},
    "reorder_step_actions": {"sv": "Ordna om åtgärder", "en": "Reorder actions"},
    "list_tags": {"sv": "Lista taggar", "en": "List tags"},
    "list_tasks": {"sv": "Lista uppgifter", "en": "List tasks"},
    "get_work_board": {"sv": "Visa tavlan", "en": "View Status"},
    "get_work_agenda": {"sv": "Visa agendan", "en": "View agenda"},
    "get_work_hierarchy": {"sv": "Visa hierarkin", "en": "View project hierarchy"},
    "list_saved_work_views": {"sv": "Lista sparade vyer", "en": "List saved views"},
    "create_saved_work_view": {"sv": "Skapa sparad vy", "en": "Create saved view"},
    "update_saved_work_view": {"sv": "Ändra sparad vy", "en": "Update saved view"},
    "archive_saved_work_view": {"sv": "Arkivera sparad vy", "en": "Archive saved view"},
    "restore_saved_work_view": {"sv": "Återställ sparad vy", "en": "Restore saved view"},
    "get_task": {"sv": "Visa uppgift", "en": "View task"},
    "create_task": {"sv": "Skapa uppgift", "en": "Create task"},
    "update_task": {"sv": "Ändra uppgift", "en": "Update task"},
    "complete_task": {"sv": "Slutför uppgift", "en": "Complete task"},
}


class LocalizeToolTitles(Transform):
    """Give each listed tool its title in the app language. Listing returns copies."""

    def __init__(self, locale: AppLocale) -> None:
        self._locale: AppLocale = locale

    async def list_tools(self, tools: Sequence[Tool]) -> Sequence[Tool]:
        return [self._localized(tool) for tool in tools]

    def _localized(self, tool: Tool) -> Tool:
        titles = TOOL_TITLES.get(tool.name)
        if titles is None:
            return tool
        return tool.model_copy(update={"title": localized(titles, self._locale)})


class MirrorToolTitles(Transform):
    """Copy each tool's display title into `annotations.title` when listing.

    FastMCP's `Tool.to_mcp_tool` sends `Tool.title` as the top-level `title` and passes the
    annotations through unchanged, so our shared READ/WRITE/DESTRUCTIVE dicts (which have no title)
    left `annotations.title` empty on the wire. Claude.ai showed raw tool names for such tools;
    that the host reads `annotations.title` is a working hypothesis, not confirmed. Tools that
    already carry an annotation title keep it. Listing returns copies, so registered tools are
    not changed.
    """

    async def list_tools(self, tools: Sequence[Tool]) -> Sequence[Tool]:
        mirrored: list[Tool] = []
        for tool in tools:
            if not tool.title or (tool.annotations and tool.annotations.title):
                mirrored.append(tool)
                continue
            annotations = (
                tool.annotations.model_copy(update={"title": tool.title})
                if tool.annotations is not None
                else ToolAnnotations(title=tool.title)
            )
            mirrored.append(tool.model_copy(update={"annotations": annotations}))
        return mirrored
