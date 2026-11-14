import type { RoomTransport } from "../../mcp-apps/room-types";
import type { ToolSupport } from "../../mcp-apps/tool-support";
import type { TagRecord } from "../../mcp-apps/ui/tag-vocabulary";
import {
  rootFromToolResult,
  type WorkAgendaPage,
  type WorkBoardPage,
  type WorkContactPage,
  type WorkContactSummary,
  type WorkSavedView,
  type WorkDomain,
  type WorkTask,
  type WorkTaskSummaryPage,
  type WorkTransport,
  type WorkUnsortedPage,
} from "./transport";

/**
 * The work transport over the host's tools/call. No network, credential or backend URL. `support` is the host's
 * answer to which tools it has (absent in Claude, where every tool is there); the views read it through `toolOffered`.
 * `offline` is the phone's offline copy and outbox (the mobile app only).
 */
export function createWorkTransport(
  call: RoomTransport["call"],
  support: ToolSupport = {},
  offline?: RoomTransport["offline"],
): WorkTransport {
  return {
    ...(offline ? { offline } : {}),
    ...(support.supportsTool ? { supportsTool: support.supportsTool } : {}),
    ...(support.supportsCall ? { supportsCall: support.supportsCall } : {}),
    getTask: (taskId) => call("get_task", { task_id: taskId }),
    getProject: (projectId) => call("get_project", { project_id: projectId }),
    updateProject: (projectId, version, changes, idempotencyKey) =>
      call("update_project", {
        project_id: projectId,
        version,
        idempotency_key: idempotencyKey,
        changes,
      }),
    listProjectTasks: (projectId, cursor) =>
      call<{
        tasks: WorkTaskSummaryPage["items"];
        next_cursor: string | null;
      }>("list_tasks", {
        project_id: projectId,
        limit: 20,
        cursor: cursor ?? null,
      }).then((page) => ({ items: page.tasks, next_cursor: page.next_cursor })),
    listProcessTasks: (processId, cursor) =>
      call<{
        tasks: WorkTaskSummaryPage["items"];
        next_cursor: string | null;
        truncated?: boolean;
      }>("list_tasks", {
        process_id: processId,
        limit: 20,
        cursor: cursor ?? null,
      }).then((page) => ({
        items: page.tasks,
        next_cursor: page.next_cursor,
        ...(page.truncated === true ? { truncated: true } : {}),
      })),
    rescheduleTasks: (items, idempotencyKey) =>
      call("reschedule_tasks", {
        items: items.map((item) => ({
          task_id: item.taskId,
          expected_version: item.version,
          when: item.when,
        })),
        idempotency_key: idempotencyKey,
      }),
    updateTask: (taskId, version, changes, idempotencyKey) =>
      call("update_task", {
        task_id: taskId,
        version,
        idempotency_key: idempotencyKey,
        changes,
      }),
    reorderBoardColumn: (status, items, idempotencyKey) =>
      call("reorder_work_board_column", {
        status,
        items: items.map((item) => ({
          task_id: item.taskId,
          version: item.version,
        })),
        idempotency_key: idempotencyKey,
      }),
    createTask: (task, idempotencyKey) =>
      call("create_task", { ...task, idempotency_key: idempotencyKey }),
    listUnsortedTasks: (cursor, limit = 25) =>
      call<{ tasks: WorkTask[]; next_cursor: string | null }>("list_tasks", {
        unsorted: true,
        limit,
        cursor: cursor ?? null,
      }).then((page): WorkUnsortedPage => ({
        items: page.tasks,
        next_cursor: page.next_cursor,
      })),
    listDomains: () =>
      call<{ domains: WorkDomain[] }>("list_domains", {
        limit: 100,
        cursor: null,
      }).then((page) => page.domains),
    listTaskSteps: (taskId, cursor) =>
      call("list_task_steps", {
        task_id: taskId,
        limit: 100,
        ...(cursor ? { cursor } : {}),
      }),
    createTaskStep: (taskId, title, idempotencyKey) =>
      call("create_task_step", {
        task_id: taskId,
        title,
        idempotency_key: idempotencyKey,
      }),
    completeTaskStep: (stepId, version, idempotencyKey) =>
      call("complete_task_step", {
        step_id: stepId,
        version,
        idempotency_key: idempotencyKey,
      }),
    updateTaskStep: (stepId, version, changes, idempotencyKey) =>
      call("update_task_step", {
        step_id: stepId,
        version,
        idempotency_key: idempotencyKey,
        changes,
      }),
    listTaskContacts: (taskId, cursor) =>
      call("list_task_contacts", {
        task_id: taskId,
        limit: 20,
        cursor: cursor ?? null,
      }),
    searchContacts: (q, cursor) =>
      call<{
        contacts: WorkContactPage["items"];
        next_cursor: string | null;
      }>("list_contacts", { q, limit: 10, cursor: cursor ?? null }).then(
        (page) => ({
          items: page.contacts,
          next_cursor: page.next_cursor,
        }),
      ),
    listContacts: ({ q, includeArchived, tags = [] }, cursor) =>
      call<{
        contacts: WorkContactSummary[];
        next_cursor: string | null;
      }>("list_contacts", {
        q: q === "" ? null : q,
        include_archived: includeArchived,
        // Sent only when chosen, so an unfiltered read stays the call it was.
        ...(tags.length > 0 ? { tags, tag_match: "all" } : {}),
        limit: 25,
        cursor: cursor ?? null,
      }).then((page) => ({
        items: page.contacts,
        next_cursor: page.next_cursor,
      })),
    createContact: (contact, idempotencyKey) =>
      call("create_contact", {
        ...contact,
        idempotency_key: idempotencyKey,
      }),
    linkContactToTask: (taskId, contactId, idempotencyKey) =>
      call("link_contact_to_task", {
        task_id: taskId,
        contact_id: contactId,
        idempotency_key: idempotencyKey,
      }),
    unlinkContactFromTask: (taskId, contactId, idempotencyKey) =>
      call("unlink_contact_from_task", {
        task_id: taskId,
        contact_id: contactId,
        idempotency_key: idempotencyKey,
      }),
    trashTask: (taskId, version, idempotencyKey) =>
      call("move_to_trash", {
        kind: "task",
        record_id: taskId,
        version,
        idempotency_key: idempotencyKey,
      }),
    restoreTask: (taskId, trashVersion, idempotencyKey) =>
      call("restore_from_trash", {
        kind: "task",
        record_id: taskId,
        version: trashVersion,
        idempotency_key: idempotencyKey,
      }),
    getContactContext: (contactId, taskCursor) =>
      call("get_contact_context", {
        contact_id: contactId,
        project_limit: 10,
        task_limit: 20,
        task_cursor: taskCursor ?? null,
      }),
    listTags: () =>
      call<{ tags: TagRecord[] }>("list_tags", { limit: 100 }).then(
        (page) => page.tags,
      ),
    updateContact: (contactId, expectedVersion, changes, idempotencyKey) =>
      call("update_contact", {
        contact_id: contactId,
        expected_version: expectedVersion,
        idempotency_key: idempotencyKey,
        changes,
      }),
    addContactAlias: (contactId, expectedVersion, value, idempotencyKey) =>
      call("add_contact_alias", {
        contact_id: contactId,
        expected_version: expectedVersion,
        value,
        idempotency_key: idempotencyKey,
      }),
    removeContactAlias: (contactId, aliasId, expectedVersion, idempotencyKey) =>
      call("remove_contact_alias", {
        contact_id: contactId,
        alias_id: aliasId,
        expected_version: expectedVersion,
        idempotency_key: idempotencyKey,
      }),
    archiveContact: (contactId, expectedVersion, idempotencyKey) =>
      call("archive_contact", {
        contact_id: contactId,
        expected_version: expectedVersion,
        idempotency_key: idempotencyKey,
      }),
    restoreContact: (contactId, expectedVersion, idempotencyKey) =>
      call("restore_contact", {
        contact_id: contactId,
        expected_version: expectedVersion,
        idempotency_key: idempotencyKey,
      }),
    getWorkBoard: (filters, cursor) =>
      call<WorkBoardPage>("get_work_board", {
        ...filters,
        limit: 25,
        cursor: cursor ?? null,
      }),
    getWorkAgenda: (filters, cursor) =>
      call<WorkAgendaPage>("get_work_agenda", {
        ...filters,
        limit: 25,
        cursor: cursor ?? null,
      }),
    getWorkHierarchy: (options) =>
      call<unknown>("get_work_hierarchy", {
        ...(options?.includeTasks ? { include_tasks: true } : {}),
        ...(options?.cursor ? { cursor: options.cursor } : {}),
      }).then((structured) => {
        const frame = rootFromToolResult(structured);
        if (frame?.kind !== "hierarchy")
          throw new Error("get_work_hierarchy returned no hierarchy");
        return frame;
      }),
    archiveTaskStep: (stepId, version, idempotencyKey) =>
      call("archive_task_step", {
        step_id: stepId,
        version,
        idempotency_key: idempotencyKey,
      }),
    restoreTaskStep: (stepId, version, idempotencyKey) =>
      call("restore_task_step", {
        step_id: stepId,
        version,
        idempotency_key: idempotencyKey,
      }),
    reorderTaskSteps: (taskId, items, idempotencyKey) =>
      call("reorder_task_steps", {
        task_id: taskId,
        items,
        idempotency_key: idempotencyKey,
      }),
    listStepActions: (stepId) =>
      call("list_step_actions", { step_id: stepId, limit: 100 }),
    completeStepAction: (actionId, version, idempotencyKey) =>
      call("complete_step_action", {
        action_id: actionId,
        version,
        idempotency_key: idempotencyKey,
      }),
    reopenStepAction: (actionId, version, idempotencyKey) =>
      call("update_step_action", {
        action_id: actionId,
        version,
        idempotency_key: idempotencyKey,
        changes: { status: "open" },
      }),
    archiveStepAction: (actionId, version, idempotencyKey) =>
      call("archive_step_action", {
        action_id: actionId,
        version,
        idempotency_key: idempotencyKey,
      }),
    restoreStepAction: (actionId, version, idempotencyKey) =>
      call("restore_step_action", {
        action_id: actionId,
        version,
        idempotency_key: idempotencyKey,
      }),
    reorderStepActions: (stepId, items, idempotencyKey) =>
      call("reorder_step_actions", {
        step_id: stepId,
        items,
        idempotency_key: idempotencyKey,
      }),
    listSavedWorkViews: (includeArchived) =>
      call<{ saved_views: WorkSavedView[] }>("list_saved_work_views", {
        include_archived: includeArchived,
      }).then((result) => result.saved_views),
    createSavedWorkView: (name, definition, idempotencyKey) =>
      call("create_saved_work_view", {
        name,
        definition,
        idempotency_key: idempotencyKey,
      }),
    updateSavedWorkView: (viewId, version, changes, idempotencyKey) =>
      call("update_saved_work_view", {
        view_id: viewId,
        version,
        ...changes,
        idempotency_key: idempotencyKey,
      }),
    archiveSavedWorkView: (viewId, version, idempotencyKey) =>
      call("archive_saved_work_view", {
        view_id: viewId,
        version,
        idempotency_key: idempotencyKey,
      }),
    restoreSavedWorkView: (viewId, version, idempotencyKey) =>
      call("restore_saved_work_view", {
        view_id: viewId,
        version,
        idempotency_key: idempotencyKey,
      }),
    linkContactToProject: (contactId, projectId, idempotencyKey) =>
      call("link_contact_to_project", {
        contact_id: contactId,
        project_id: projectId,
        idempotency_key: idempotencyKey,
      }),
    unlinkContactFromProject: (contactId, projectId, idempotencyKey) =>
      call("unlink_contact_from_project", {
        contact_id: contactId,
        project_id: projectId,
        idempotency_key: idempotencyKey,
      }),
    listTaskExternalReferences: (taskId, cursor) =>
      call("list_task_external_references", {
        task_id: taskId,
        limit: 25,
        cursor: cursor ?? null,
      }),
    unlinkExternalReferenceFromTask: (taskId, referenceId, idempotencyKey) =>
      call("unlink_external_reference_from_task", {
        task_id: taskId,
        reference_id: referenceId,
        idempotency_key: idempotencyKey,
      }),
    linkExternalReferenceToTask: (taskId, reference, idempotencyKey) =>
      call("link_external_reference_to_task", {
        task_id: taskId,
        kind: reference.kind,
        provider: reference.provider,
        account_ref: reference.account_ref,
        external_id: reference.external_id,
        instance_ref: reference.instance_ref,
        title: reference.title,
        url: reference.url,
        occurs_at: reference.occurs_at,
        idempotency_key: idempotencyKey,
      }),
    getDomain: (domainId) => call("get_domain", { domain_id: domainId }),
    getProcess: (processId) => call("get_process", { process_id: processId }),
  };
}
