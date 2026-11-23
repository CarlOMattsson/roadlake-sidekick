/**
 * Router of the unified Sidekick app: which room and view a tool result belongs to.
 *
 * The tool name is the primary key (`toolInfo.tool.name` in the host context). The shape of
 * `structuredContent` is only a fallback, for hosts that do not report the name (V5, for example a
 * rehydrated conversation). Both must keep reading every historical tool result, because an old
 * conversation is redrawn with the current app HTML. Do not rename a view or tighten a shape
 * without keeping the old one working.
 *
 * `contracts/mcp-tools.generated.json` is checked against TOOL_ROUTES by a test: every tool with a
 * `_meta.ui.resourceUri` must have an entry here.
 */

export const ROOM_IDS = [
  "work",
  "journal",
  "contacts",
  "shopping",
  "control",
] as const;
export type RoomId = (typeof ROOM_IDS)[number];

/**
 * Where a room stands follows how often it is used, never what it holds, and the most used comes first.
 *
 * These stand in the strip's own cells, in order: the rooms used several times a week. The order is a design
 * decision and never follows use, so the strip does not move under the thumb. Control stays outside the strip.
 * The row holds at most four of them (`StripRow`, so a fifth does not compile): with Mer that is the five cells a
 * 360 frame has room for in both languages, and the fourth place is kept for the start view. A room that would be
 * one more belongs in Mer. A daily habit that needs no room of its own (the day's review) is a block of the start
 * view and never a cell. The room of a feature the instance has not turned on is drawn in neither place
 * (enabled-rooms.ts).
 */
export const PRIMARY_ROOM_IDS = [
  "work",
  "journal",
  "shopping",
] as const satisfies StripRow;
type StripRow = readonly RoomId[] & { readonly length: 1 | 2 | 3 | 4 };
/** Rooms used about once a week or less: rows of the strip's last cell, "Mer ⌄", in order. */
export const MORE_ROOM_IDS = ["contacts"] as const;
/** Every room the strip leads to: its cells, then the rows of Mer (the narrow room picker lists them in this order). */
export const STRIP_ROOM_IDS = [...PRIMARY_ROOM_IDS, ...MORE_ROOM_IDS] as const;
export type StripRoomId = (typeof STRIP_ROOM_IDS)[number];

/**
 * The view a room opens on. The names are the room's own; a room maps an unknown view to its root.
 * work: agenda, board, hierarchy, task, project, process, changes (confirmation card), review (the review queue's card).
 * journal: day, entry, card (one entry as a compact card), draft, pending.
 * contacts: list, contact (with context), compact (one contact record).
 * shopping: list, lists, batch (items just added or updated).
 * control: trash, changes, memory, activity.
 */
export type Route = { room: RoomId; view: string };

const work = (view: string): Route => ({ room: "work", view });
const journal = (view: string): Route => ({ room: "journal", view });
const contacts = (view: string): Route => ({ room: "contacts", view });
const shopping = (view: string): Route => ({ room: "shopping", view });
const control = (view: string): Route => ({ room: "control", view });

/** Tool name to route. Contact tools belong to Contacts although their resource is the Work app. */
export const TOOL_ROUTES: Readonly<Record<string, Route>> = {
  // Work
  get_work_agenda: work("agenda"),
  get_work_board: work("board"),
  get_work_hierarchy: work("hierarchy"),
  get_task: work("task"),
  get_project: work("project"),
  get_process: work("process"),
  show_work_changes: work("changes"),
  get_review_queue: work("review"),
  // Contacts
  list_contacts: contacts("list"),
  get_contact_context: contacts("contact"),
  create_contact: contacts("compact"),
  update_contact: contacts("compact"),
  // Journal
  get_journal_day: journal("day"),
  get_journal_entry: journal("entry"),
  get_journal_draft: journal("draft"),
  list_pending_journal: journal("pending"),
  create_manual_journal_entry: journal("card"),
  write_journal_entry: journal("card"),
  update_journal_entry: journal("card"),
  // Shopping
  get_shopping_list: shopping("list"),
  list_shopping_lists: shopping("lists"),
  add_shopping_items: shopping("batch"),
  update_shopping_item: shopping("batch"),
  // Control
  list_trash: control("trash"),
  list_recent_changes: control("changes"),
  get_memory_status: control("memory"),
  list_assistant_activity: control("activity"),
};

/**
 * A host may prefix tool names with a server or namespace; the last segment is the tool. A run of underscores is one
 * separator, so a prefix that ends in `_` (`my_server___get_task`) still leaves the tool's own name.
 */
export function toolBareName(name: string): string {
  return name.split(/_{2,}|[:/.]/).pop() ?? name;
}

/** The route of a tool name, or undefined when the name is missing or not one of ours. */
export function routeForTool(name: unknown): Route | undefined {
  if (typeof name !== "string" || name === "") return undefined;
  if (Object.hasOwn(TOOL_ROUTES, name)) return TOOL_ROUTES[name];
  const bare = toolBareName(name);
  return Object.hasOwn(TOOL_ROUTES, bare) ? TOOL_ROUTES[bare] : undefined;
}

type Obj = Record<string, unknown>;

function isObj(value: unknown): value is Obj {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function hasString(value: unknown, key: string): boolean {
  return isObj(value) && typeof value[key] === "string";
}
function everyItem(list: unknown[], test: (item: unknown) => boolean) {
  return list.every(test);
}

const isWorkItem = (item: unknown) =>
  hasString(item, "kind") &&
  hasString(item, "id") &&
  hasString(item, "title") &&
  hasString(item, "status");
const isPendingItem = (item: unknown) =>
  hasString(item, "source_id") &&
  hasString(item, "journal_date") &&
  hasString(item, "state");
const isActivityItem = (item: unknown) =>
  hasString(item, "source") &&
  hasString(item, "state") &&
  hasString(item, "operation") &&
  hasString(item, "summary");
/** add_shopping_items answers `items: [{ item, merged }]`; update_shopping_item answers `item`. */
const isBatchItem = (item: unknown) => isObj(item) && isObj(item.item);

/**
 * The route a result's shape implies, or undefined when the shape is not one we know. Checks run
 * from the most specific shape to the least, because several results share `items`.
 */
export function routeForShape(structured: unknown): Route | undefined {
  if (!isObj(structured)) return undefined;
  const data = structured;
  if (isObj(data.card) && data.card.kind === "work_changes")
    return work("changes");
  if (
    Array.isArray(data.tasks) &&
    typeof data.remaining_total === "number" &&
    isObj(data.bucket_counts)
  )
    return work("review");
  if (hasString(data.task, "id")) return work("task");
  const contact = data.contact;
  if (hasString(contact, "id")) {
    const withContext =
      isObj(data.projects) &&
      Array.isArray(data.projects.items) &&
      isObj(data.tasks) &&
      Array.isArray(data.tasks.items);
    return contacts(withContext ? "contact" : "compact");
  }
  if (hasString(data.project, "id")) return work("project");
  if (hasString(data.process, "id")) return work("process");
  if (Array.isArray(data.contacts)) return contacts("list");
  if (
    typeof data.journal_date === "string" &&
    Array.isArray(data.entries) &&
    isObj(data.summary)
  )
    return journal("day");
  if (hasString(data.shopping_list, "id") && Array.isArray(data.items))
    return shopping("list");
  if (
    isObj(data.settings) &&
    typeof data.provider === "string" &&
    Array.isArray(data.sources)
  )
    return control("memory");
  if (Array.isArray(data.changes)) return control("changes");
  if (Array.isArray(data.nodes) && typeof data.truncated === "boolean")
    return work("hierarchy");
  if (isObj(data.columns)) return work("board");
  if (hasString(data.draft, "id")) return journal("draft");
  if (hasString(data.entry, "id")) return journal("entry");
  if (
    (Array.isArray(data.items) &&
      data.items.length > 0 &&
      everyItem(data.items, isBatchItem)) ||
    (isObj(data.item) && typeof data.list_name === "string")
  )
    return shopping("batch");
  if (Array.isArray(data.items)) {
    const items = data.items;
    if (typeof data.has_more === "boolean") return control("trash");
    if (items.length === 0) {
      // No element to look at: the other keys of each result decide.
      if ("filters" in data) return work("agenda");
      if ("next_cursor" in data) return control("activity");
      return journal("pending");
    }
    if (everyItem(items, isWorkItem)) return work("agenda");
    if (everyItem(items, isPendingItem)) return journal("pending");
    if ("next_cursor" in data && everyItem(items, isActivityItem))
      return control("activity");
  }
  return undefined;
}

/**
 * The route of a tool result: by tool name when the host reported one we know, otherwise by the
 * shape of the result. An error result routes by name only, since it has no shape.
 */
export function routeFor(input: {
  toolName?: unknown;
  structuredContent?: unknown;
  isError?: boolean;
}): Route | undefined {
  const byName = routeForTool(input.toolName);
  if (byName) return byName;
  if (input.isError) return undefined;
  return routeForShape(input.structuredContent);
}

/** True for a room id; narrows an untrusted string. */
export function isRoomId(value: unknown): value is RoomId {
  return (
    typeof value === "string" && (ROOM_IDS as readonly string[]).includes(value)
  );
}
