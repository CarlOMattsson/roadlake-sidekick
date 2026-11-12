/**
 * Root of the Work app from the tool result that opened it. The result is checked with the guards of
 * result-guards.ts (built from the generated tool contract); a record that fails the check opens its
 * frame with only the id, or no frame at all.
 */
import { isPlainObject } from "../../../lib/mcp/shape";
import {
  isContactRecord,
  isContactSummary,
  isFullContactRecord,
  isHierarchyNode,
  isHierarchyTask,
  isJournalEntries,
  isProjectSummary,
  isTaskSummary,
  isWorkItemRecord,
  isWorkProject,
  isWorkTask,
  type WireContactRecord,
} from "./result-guards";
import {
  AGENDA_FILTER_KEYS,
  BOARD_FILTER_KEYS,
  type WorkFilters,
  type WorkFrame,
  type WorkItemRecord,
} from "./transport-frames";
import type {
  WorkContactContext,
  WorkContactRecord,
  WorkJournalEntries,
} from "./transport-records";

/**
 * Root of the app from the tool result that opened it. A get_task result opens a Task; a
 * get_contact_context result (contact plus projects and tasks) opens a Contact; a get_project
 * result opens a Project; a get_process result opens a Process page; a list_contacts result
 * (contacts) opens the Contact list; a get_work_board result (columns) opens the board; and a get_work_agenda result (items of Work
 * records) opens the agenda. A list_contacts result opens with the search and archive switch it
 * answered. A work_changes card envelope opens a card, a Contact record alone opens a compact
 * Contact card, and a failed result (isError) opens an error frame. The Task, Contact and Project
 * frames keep the record the result carried when it is valid; otherwise they carry only the id.
 */
export function rootFromToolResult(
  structured: unknown,
  isError = false,
): WorkFrame | undefined {
  if (isError) return { kind: "error" };
  const data = structured as
    | {
        card?: {
          kind?: unknown;
          items?: unknown;
          total?: unknown;
          truncated?: unknown;
          issued_at?: unknown;
        };
        task?: { id?: unknown };
        contact?: { id?: unknown };
        project?: { id?: unknown };
        process?: { id?: unknown };
        contacts?: unknown;
        q?: unknown;
        include_archived?: unknown;
        projects?: { items?: unknown; next_cursor?: unknown };
        tasks?: { items?: unknown; next_cursor?: unknown };
        columns?: unknown;
        manually_ordered?: string[];
        items?: unknown;
        filters?: unknown;
        next_cursor?: unknown;
        nodes?: unknown;
        truncated?: unknown;
      }
    | null
    | undefined;
  const card = data?.card;
  if (card?.kind === "work_changes") {
    const items = card.items;
    const total = card.total;
    const truncated = card.truncated;
    const issuedAt = card.issued_at;
    // A missing or unreadable issued_at leaves the card without a key; it is then never superseded.
    const keyed =
      typeof issuedAt === "string" && Number.isFinite(Date.parse(issuedAt))
        ? { issuedAt }
        : {};
    if (
      Array.isArray(items) &&
      items.every(isWorkItemRecord) &&
      typeof total === "number" &&
      typeof truncated === "boolean"
    )
      return { kind: "card", items, total, truncated, ...keyed };
    return undefined;
  }
  const taskId = data?.task?.id;
  if (typeof taskId === "string") {
    const task = data?.task;
    return isWorkTask(task)
      ? { kind: "task", id: taskId, task }
      : { kind: "task", id: taskId };
  }
  const contactId = data?.contact?.id;
  if (
    typeof contactId === "string" &&
    Array.isArray(data?.projects?.items) &&
    Array.isArray(data?.tasks?.items)
  ) {
    const context = contactContextFrom(data);
    return context
      ? { kind: "contact", id: contactId, context }
      : { kind: "contact", id: contactId };
  }
  const contact = data?.contact;
  if (isContactRecord(contact))
    return { kind: "compact", entity: "contact", contact };
  const projectId = data?.project?.id;
  if (typeof projectId === "string") {
    const project = data?.project;
    return isWorkProject(project)
      ? { kind: "project", id: projectId, project }
      : { kind: "project", id: projectId };
  }
  // A Process page reads its Process and Tasks itself, so the frame carries only the id.
  const processId = data?.process?.id;
  if (typeof processId === "string") return { kind: "process", id: processId };
  const contacts = data?.contacts;
  if (Array.isArray(contacts) && contacts.every(isContactSummary)) {
    // The result says which search it answered (q, include_archived); a result without them is
    // the unfiltered list. The search is trimmed as the view trims it, so the page matches it.
    const q = typeof data?.q === "string" ? data.q.trim() : "";
    const includeArchived = data?.include_archived === true;
    return {
      kind: "contacts",
      q,
      includeArchived,
      page: {
        items: contacts,
        next_cursor: cursorFrom(data),
        q,
        includeArchived,
      },
    };
  }
  const nodes = data?.nodes;
  const truncated = data?.truncated;
  const tasks = data?.tasks;
  if (
    Array.isArray(nodes) &&
    nodes.every(isHierarchyNode) &&
    typeof truncated === "boolean"
  ) {
    const next = cursorFrom(data);
    const more = next === null ? {} : { next_cursor: next };
    if (tasks === undefined)
      return { kind: "hierarchy", nodes, truncated, ...more };
    if (Array.isArray(tasks) && tasks.every(isHierarchyTask))
      return { kind: "hierarchy", nodes, truncated, tasks, ...more };
  }
  const columns = data?.columns;
  if (
    isPlainObject(columns) &&
    Object.values(columns).every(
      (list) => Array.isArray(list) && list.every(isWorkItemRecord),
    )
  )
    return {
      kind: "board",
      filters: filtersFrom(data, BOARD_FILTER_KEYS),
      page: {
        columns: columns as Record<string, WorkItemRecord[]>,
        next_cursor: cursorFrom(data),
        manually_ordered: data?.manually_ordered,
      },
    };
  const items = data?.items;
  if (Array.isArray(items) && items.every(isWorkItemRecord))
    return {
      kind: "agenda",
      filters: filtersFrom(data, AGENDA_FILTER_KEYS),
      page: { items, next_cursor: cursorFrom(data) },
    };
  return undefined;
}

/**
 * The Contact context a get_contact_context result carries (contact, projects and tasks), or
 * undefined when any part is unreadable. The context keeps only these three parts of the result.
 */
function contactContextFrom(
  data:
    | {
        contact?: unknown;
        projects?: { items?: unknown; next_cursor?: unknown };
        tasks?: { items?: unknown; next_cursor?: unknown };
        journal_entries?: unknown;
      }
    | null
    | undefined,
): WorkContactContext | undefined {
  const contact = data?.contact;
  const projectItems = data?.projects?.items;
  const taskItems = data?.tasks?.items;
  const journal = journalEntriesOf(data?.journal_entries);
  if (
    isFullContactRecord(contact) &&
    Array.isArray(projectItems) &&
    projectItems.every(isProjectSummary) &&
    Array.isArray(taskItems) &&
    taskItems.every(isTaskSummary)
  )
    return {
      contact: withProfileDefaults(contact),
      projects: {
        items: projectItems,
        next_cursor: cursorFrom(data?.projects),
      },
      tasks: { items: taskItems, next_cursor: cursorFrom(data?.tasks) },
      ...(journal ? { journal_entries: journal } : {}),
    };
  return undefined;
}

/**
 * The Contact's linked Journal entries as get_contact_context carries them, or undefined when the part
 * is absent or unreadable. An undefined value means the Contact shows no Journal section.
 */
export function journalEntriesOf(
  value: unknown,
): WorkJournalEntries | undefined {
  if (!isJournalEntries(value)) return undefined;
  // Only the three parts the Contact card reads are kept.
  return {
    items: value.items,
    has_more: value.has_more,
    readable: value.readable,
  };
}

/** The Contact record with an absent profile field filled in as null. */
function withProfileDefaults(contact: WireContactRecord): WorkContactRecord {
  return {
    ...contact,
    relationship: contact.relationship ?? null,
    organization: contact.organization ?? null,
    role: contact.role ?? null,
    address: contact.address ?? null,
  };
}

/** Only the filter keys the tool takes, and only string or string-list values, are kept. */
function filtersFrom(
  data: { filters?: unknown } | null | undefined,
  keys: readonly string[],
): WorkFilters {
  const filters: WorkFilters = {};
  const raw = data?.filters;
  if (!isPlainObject(raw)) return filters;
  for (const key of keys) {
    const value = raw[key];
    if (typeof value === "string") filters[key] = value;
    else if (
      Array.isArray(value) &&
      value.every((item) => typeof item === "string")
    )
      filters[key] = value;
  }
  return filters;
}

function cursorFrom(data: { next_cursor?: unknown } | null | undefined) {
  return typeof data?.next_cursor === "string" ? data.next_cursor : null;
}
