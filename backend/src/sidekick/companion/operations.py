"""The reviewed mapping from a device capability to application permission (ADR-005).

A companion device holds only device capabilities (`companion:*`). The application services check
application scopes (`tasks:read`, `tasks:write`, ...). Each companion route names one operation
below; the adapter checks the device capability and then calls the fixed use case with an actor
that carries exactly that operation's application scopes, for that one call. The device never
holds an application scope, and no other use case is reachable with these actors: the routes are
the only callers, and each calls one service method.

`task.complete` needs `tasks:write` because `TaskService.complete` requires it
(`sidekick.tasks.application.service`). That actor
is built only inside the completion route, which calls `TaskService.complete` and nothing else,
and the reopen route, which calls `TaskService.update` with exactly `status = todo` on a completed
Task (the undo of a completion). So `companion:tasks:complete` cannot otherwise update, move,
trash or create a Task.

The read operations also carry `projects:read` (Work tags and Project titles in the result, as
in MCP) and the agenda carries `contacts:read`, used only for the waiting contact's display name
in an agenda row, exactly as the MCP agenda shows it. The only other Contact read is the linked
Contacts of one Task (`task.contacts`), the same summary page as the MCP tool.
"""

from __future__ import annotations

from dataclasses import dataclass

from sidekick.lifecycle import RecordKind
from sidekick.shared.auth import CompanionCredential
from sidekick.shared.errors.core import PermissionDeniedError
from sidekick.shared.types import Actor


@dataclass(frozen=True, slots=True)
class CompanionOperation:
    name: str
    capability: str
    application_scopes: frozenset[str]
    # A second capability the device must hold too: a write that answers with the record it wrote
    # also needs the room's read capability, so a write never reads what the device may not read.
    also: str | None = None


WORK_AGENDA = CompanionOperation(
    "work.agenda",
    "companion:tasks:read",
    frozenset({"tasks:read", "projects:read", "contacts:read"}),
)
# Arbetes Idag for the widget and the app's Idag: `WorkListService.work_today_page`, the agenda's
# own overdue and today groups. It needs only `tasks:read` (the Project title is a field of the
# Task's Work record); no Contact is read.
WORK_TODAY = CompanionOperation(
    "work.today",
    "companion:tasks:read",
    frozenset({"tasks:read", "projects:read"}),
)
TASK_DETAIL = CompanionOperation(
    "task.get",
    "companion:tasks:read",
    frozenset({"tasks:read", "projects:read"}),
)
TASK_COMPLETE = CompanionOperation(
    "task.complete",
    "companion:tasks:complete",
    frozenset({"tasks:write", "projects:read"}),
)

TASK_STEPS = CompanionOperation(
    "task.steps",
    "companion:tasks:read",
    frozenset({"tasks:read"}),
)
# The two linked-record reads of the task screen. Contacts need `contacts:read` as well, because
# `ContactService.list_task_contacts` requires both; the result is the MCP tool's page of Contact
# summaries (name, relationship, organization, role; never an address). References need only
# `tasks:read`: the MCP page is pointers (title, https link, provider), no mail/event content.
TASK_CONTACTS = CompanionOperation(
    "task.contacts",
    "companion:tasks:read",
    frozenset({"tasks:read", "contacts:read"}),
)
TASK_EXTERNAL_REFERENCES = CompanionOperation(
    "task.external_references",
    "companion:tasks:read",
    frozenset({"tasks:read"}),
)
# Undo of a completion ("Ångra" on the agenda row): `TaskService.update` with exactly
# `status = todo`, and only while the Task is completed at the version the device sent. It is the
# same use case as `update_task` with `changes={"status": "todo"}`, under the completion
# capability: undoing one's own tick is part of ticking, and no other field can be changed.
TASK_REOPEN = CompanionOperation(
    "task.reopen",
    "companion:tasks:complete",
    frozenset({"tasks:read", "tasks:write", "projects:read"}),
)

# --- Work beyond the agenda: the Project list, Projects, their Domains and Processes, and
# the Steps of a Task. All of them reuse the device capabilities that already exist, so a device
# paired before these routes existed has them at once: reading is `companion:tasks:read`, ticking is
# `companion:tasks:complete`.
# Reads of the hierarchy carry `projects:read` (as the MCP tools do). The Step ticks need
# `tasks:write` for `StepsService.complete_step` / `update_step`; the actor is built only inside
# those two routes, and reopen sets exactly `status = todo` on a completed Step (a use case guard).
# `include_tasks` (and the Process filter) opens Tasks and Steps under the nodes, exactly as the MCP
# tool does, so the hierarchy read also carries `tasks:read`; the capability stays the read one.
WORK_HIERARCHY = CompanionOperation(
    "work.hierarchy",
    "companion:tasks:read",
    frozenset({"projects:read", "tasks:read"}),
)
PROJECT_DETAIL = CompanionOperation(
    "project.get",
    "companion:tasks:read",
    frozenset({"projects:read", "tasks:read"}),
)
PROJECT_TASKS = CompanionOperation(
    "project.tasks",
    "companion:tasks:read",
    frozenset({"tasks:read", "projects:read"}),
)
DOMAIN_DETAIL = CompanionOperation(
    "domain.get",
    "companion:tasks:read",
    frozenset({"projects:read"}),
)
PROCESS_DETAIL = CompanionOperation(
    "process.get",
    "companion:tasks:read",
    frozenset({"projects:read"}),
)
STEP_COMPLETE = CompanionOperation(
    "step.complete",
    "companion:tasks:complete",
    frozenset({"tasks:write"}),
)
STEP_REOPEN = CompanionOperation(
    "step.reopen",
    "companion:tasks:complete",
    frozenset({"tasks:write"}),
)

# Registering or removing the device's own UnifiedPush endpoint (D-078: push through UnifiedPush,
# the message carries no content). It reaches no domain
# use case, so it holds no application scope: the actor carries only the credential's owner.
PUSH_SUBSCRIPTION = CompanionOperation("push.subscription", "companion:push", frozenset())

# The visible reminders: fetch what is pending, acknowledge, queue the device's test.
# They read and write only the reminders table of the credential's owner, so no application scope.
PUSH_REMINDERS = CompanionOperation("push.reminders", "companion:push", frozenset())

# The instance's license (D-081: signed keys checked offline): read the display state, enter a
# key. Neither reaches a domain use
# case, so no application scope; the key is set through `LicenseService.set_by_owner`, which also
# requires the credential's user to be the installation's only owner.
LICENSE_SHOW = CompanionOperation("license.show", "companion:license", frozenset())
LICENSE_SET = CompanionOperation("license.set", "companion:license", frozenset())

# --- Shopping -----------------------------------------------------------------------------------
# The reads need `companion:shopping:read`; the writes need `companion:shopping:write` and the read
# capability too. Adding and changing an item can name a gift recipient, which the use case checks
# against `contacts:read` (it only confirms the Contact exists; no Contact field is returned).
SHOPPING_LISTS = CompanionOperation(
    "shopping.lists", "companion:shopping:read", frozenset({"shopping:read"})
)
SHOPPING_LIST = CompanionOperation(
    "shopping.list", "companion:shopping:read", frozenset({"shopping:read"})
)
SHOPPING_LIST_CREATE = CompanionOperation(
    "shopping.list_create",
    "companion:shopping:write",
    frozenset({"shopping:write"}),
    also="companion:shopping:read",
)
SHOPPING_LIST_UPDATE = CompanionOperation(
    "shopping.list_update",
    "companion:shopping:write",
    frozenset({"shopping:write"}),
    also="companion:shopping:read",
)
SHOPPING_ITEMS_ADD = CompanionOperation(
    "shopping.items_add",
    "companion:shopping:write",
    frozenset({"shopping:write", "contacts:read"}),
    also="companion:shopping:read",
)
SHOPPING_ITEM_UPDATE = CompanionOperation(
    "shopping.item_update",
    "companion:shopping:write",
    frozenset({"shopping:write", "contacts:read"}),
    also="companion:shopping:read",
)
SHOPPING_ITEM_PURCHASED = CompanionOperation(
    "shopping.item_purchased",
    "companion:shopping:write",
    frozenset({"shopping:write"}),
    also="companion:shopping:read",
)

# --- Journal ------------------------------------------------------------------------------------
# The same application scopes as the MCP tools of the same name (`JOURNAL_TOOL_SCOPES`; a test pins
# the equality). Only the owner's manual writing is here (D-076: the journal is written by hand
# in the room, AI-first otherwise): a new entry from the owner's own
# words and a change of an existing entry, and reading the source text back. No draft, summary or
# other AI-derived flow.
JOURNAL_DAY = CompanionOperation(
    "journal.day", "companion:journal:read", frozenset({"journal:read"})
)
JOURNAL_ENTRIES = CompanionOperation(
    "journal.entries", "companion:journal:read", frozenset({"journal:read"})
)
JOURNAL_ENTRY = CompanionOperation(
    "journal.entry", "companion:journal:read", frozenset({"journal:read"})
)
# The immutable text of one owned source: what the owner wrote by hand is read back here, since
# a hand-written entry has no summary of its own (the use case and scope of `get_journal_source`).
JOURNAL_SOURCE = CompanionOperation(
    "journal.source", "companion:journal:read", frozenset({"journal:read"})
)
JOURNAL_ENTRY_WRITE = CompanionOperation(
    "journal.entry_write",
    "companion:journal:write",
    frozenset({"journal:write", "projects:read", "tasks:read", "contacts:read"}),
    also="companion:journal:read",
)
JOURNAL_ENTRY_UPDATE = CompanionOperation(
    "journal.entry_update",
    "companion:journal:write",
    frozenset({"journal:read", "journal:write"}),
    also="companion:journal:read",
)

# A photo the owner adds from the phone: the same use case as the app-only `add_journal_photo`, over
# a multipart route (the phone has the file, not a base64 text). It answers with the stored record,
# so it needs the room's read capability too. The device never reads a photo back through it.
JOURNAL_PHOTO_ADD = CompanionOperation(
    "journal.photo_add",
    "companion:journal:write",
    frozenset({"journal:read", "journal:write"}),
    also="companion:journal:read",
)

# --- Work writes ---------------------------------------------------------------------------------
# The owner's manual creating and editing of Tasks and of a Project's title, status, description
# and dates, for the moments the owner cannot talk to Claude (ADR-005, "Amendment 2026-11-15").
# One capability, `companion:work:write`, plus the read capability, because each write answers
# with the record it wrote. The application scopes are those of the MCP tools of the same name
# (`create_task` and `update_task` need `projects:read` and `tasks:write`; `update_project` needs
# `projects:write` and, for the tags in its reply, `projects:read`). Each actor is built only
# inside the route that calls the one use case, and the request bodies name only the fields the
# form can change.
TASK_CREATE = CompanionOperation(
    "task.create",
    "companion:work:write",
    frozenset({"tasks:write", "projects:read"}),
    also="companion:tasks:read",
)
TASK_UPDATE = CompanionOperation(
    "task.update",
    "companion:work:write",
    frozenset({"tasks:write", "projects:read"}),
    also="companion:tasks:read",
)
PROJECT_UPDATE = CompanionOperation(
    "project.update",
    "companion:work:write",
    frozenset({"projects:write", "projects:read"}),
    also="companion:tasks:read",
)

# --- The trash ------------------------------------------------------------------------------------
# The owner's manual deleting for the moments the owner cannot talk to Claude (ADR-005, "Amendment
# 2026-11-15"): move a Task, a Journal entry or a Shopping item to the trash and take it back, which
# is the use case of the MCP tools `move_to_trash` and `restore_from_trash`, under the room's own
# write capability and with the room's read capability too, because the answer names the record.
# Only a trashed Task can be removed permanently (the use case refuses the other two kinds), by its
# own route with a confirmation in the body; emptying the trash removes the trashed Tasks. Both
# need `companion:work:erase`, a capability of its own that is irreversible and therefore granted
# on its own, and `companion:work:write` besides. No route reaches any other kind, so a device
# cannot trash a Project, a Contact or a Step.
TASK_TRASH = CompanionOperation(
    "task.trash",
    "companion:work:write",
    frozenset({"tasks:write", "tasks:read"}),
    also="companion:tasks:read",
)
TASK_UNTRASH = CompanionOperation(
    "task.untrash",
    "companion:work:write",
    frozenset({"tasks:write", "tasks:read"}),
    also="companion:tasks:read",
)
TASK_ERASE = CompanionOperation(
    "task.erase",
    "companion:work:erase",
    frozenset({"tasks:write"}),
    also="companion:work:write",
)
TRASH_EMPTY = CompanionOperation(
    "trash.empty",
    "companion:work:erase",
    frozenset({"tasks:write", "tasks:read"}),
    also="companion:work:write",
)
JOURNAL_ENTRY_TRASH = CompanionOperation(
    "journal.entry_trash",
    "companion:journal:write",
    frozenset({"journal:write", "journal:read"}),
    also="companion:journal:read",
)
JOURNAL_ENTRY_UNTRASH = CompanionOperation(
    "journal.entry_untrash",
    "companion:journal:write",
    frozenset({"journal:write", "journal:read"}),
    also="companion:journal:read",
)
SHOPPING_ITEM_TRASH = CompanionOperation(
    "shopping.item_trash",
    "companion:shopping:write",
    frozenset({"shopping:write", "shopping:read"}),
    also="companion:shopping:read",
)
SHOPPING_ITEM_UNTRASH = CompanionOperation(
    "shopping.item_untrash",
    "companion:shopping:write",
    frozenset({"shopping:write", "shopping:read"}),
    also="companion:shopping:read",
)

# What the trash list shows: the kinds whose trash operation the device may call, so it never lists
# what it could not trash or restore. The list route has no operation of its own.
TRASH_KIND_OPERATIONS: dict[RecordKind, CompanionOperation] = {
    RecordKind.TASK: TASK_TRASH,
    RecordKind.JOURNAL_ENTRY: JOURNAL_ENTRY_TRASH,
    RecordKind.SHOPPING_ITEM: SHOPPING_ITEM_TRASH,
}

OPERATIONS: tuple[CompanionOperation, ...] = (
    WORK_AGENDA,
    WORK_TODAY,
    TASK_DETAIL,
    TASK_STEPS,
    TASK_CONTACTS,
    TASK_EXTERNAL_REFERENCES,
    TASK_COMPLETE,
    TASK_REOPEN,
    TASK_CREATE,
    TASK_UPDATE,
    PROJECT_UPDATE,
    TASK_TRASH,
    TASK_UNTRASH,
    TASK_ERASE,
    TRASH_EMPTY,
    WORK_HIERARCHY,
    PROJECT_DETAIL,
    PROJECT_TASKS,
    DOMAIN_DETAIL,
    PROCESS_DETAIL,
    STEP_COMPLETE,
    STEP_REOPEN,
    PUSH_SUBSCRIPTION,
    PUSH_REMINDERS,
    LICENSE_SHOW,
    LICENSE_SET,
    SHOPPING_LISTS,
    SHOPPING_LIST,
    SHOPPING_LIST_CREATE,
    SHOPPING_LIST_UPDATE,
    SHOPPING_ITEMS_ADD,
    SHOPPING_ITEM_UPDATE,
    SHOPPING_ITEM_PURCHASED,
    JOURNAL_DAY,
    JOURNAL_ENTRIES,
    JOURNAL_ENTRY,
    JOURNAL_SOURCE,
    JOURNAL_ENTRY_WRITE,
    JOURNAL_ENTRY_UPDATE,
    JOURNAL_PHOTO_ADD,
    JOURNAL_ENTRY_TRASH,
    JOURNAL_ENTRY_UNTRASH,
    SHOPPING_ITEM_TRASH,
    SHOPPING_ITEM_UNTRASH,
)


class CapabilityMissing(PermissionDeniedError):
    """The device was not granted the capability this operation needs."""


def operation_actor(credential: CompanionCredential, operation: CompanionOperation) -> Actor:
    """The actor for one call of `operation`, or `CapabilityMissing`."""

    if operation.capability not in credential.scopes:
        raise CapabilityMissing(operation.name)
    if operation.also is not None and operation.also not in credential.scopes:
        raise CapabilityMissing(operation.name)
    return Actor(credential.user_id, operation.application_scopes)


def trash_listing_actor(credential: CompanionCredential) -> tuple[Actor, frozenset[RecordKind]]:
    """The actor that lists the trash, and the kinds it may list: those the device may trash.

    Raises `CapabilityMissing` when the device may trash none of them. The actor holds only the
    scopes of the kinds it may list, so a label of a kind the device cannot read is never returned.
    """

    scopes: set[str] = set()
    kinds: set[RecordKind] = set()
    for kind, operation in TRASH_KIND_OPERATIONS.items():
        try:
            scopes |= operation_actor(credential, operation).scopes
        except CapabilityMissing:
            continue
        kinds.add(kind)
    if not kinds:
        raise CapabilityMissing("trash.list")
    return Actor(credential.user_id, frozenset(scopes)), frozenset(kinds)
