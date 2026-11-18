/**
 * Contract of the Control app (trash, recent changes, memory). Every call goes through an existing
 * MCP tool; the app adds no command of its own. The record types are derived from the generated
 * tool contract (list_trash, list_recent_changes, get_memory_status, set_memory_settings,
 * list_assistant_activity), so a backend change to one of them breaks the typecheck here.
 */
import type { Item, WithOptional } from "../../lib/mcp/derived";
import type { ToolResults } from "../../lib/mcp/tool-results.generated";

export type TrashItem = Item<ToolResults["list_trash"]["items"]>;
/**
 * `next_cursor`: pass it to `trash` to read the page after this one; null when this is the last. `can_erase` is the
 * phone's own answer to whether this device may remove for good (`companion:work:erase`); a host that does not say,
 * Claude among them, is read as no.
 */
export type TrashList = Pick<
  ToolResults["list_trash"],
  "items" | "has_more" | "next_cursor"
> & { can_erase?: boolean };

/** One recent change; `related_id`, `undo_tool` and `actor` are optional because an older server leaves them out. */
export type ChangeRecord = WithOptional<
  Item<ToolResults["list_recent_changes"]["changes"]>,
  "related_id" | "undo_tool" | "actor"
>;
export type ChangesList = { changes: ChangeRecord[] };

/** One Activity Center entry, the fields the card shows. */
export type ActivityRecord = WithOptional<
  Pick<
    Item<ToolResults["list_assistant_activity"]["items"]>,
    | "id"
    | "category"
    | "source"
    | "operation"
    | "state"
    | "aggregate_type"
    | "aggregate_id"
    | "after_values"
    | "summary"
    | "occurred_at"
  >,
  "aggregate_id" | "after_values"
>;
export type ActivityList = {
  items: ActivityRecord[];
  next_cursor: ToolResults["list_assistant_activity"]["next_cursor"];
};

export type MemorySettings = ToolResults["get_memory_status"]["settings"];
export type MemoryDomain = Exclude<keyof MemorySettings, "paused" | "version">;
export const MEMORY_DOMAINS = [
  "journal",
  "contacts",
  "projects",
  "tasks",
] as const satisfies readonly MemoryDomain[];

export type MemorySourceCount = Item<
  ToolResults["get_memory_status"]["sources"]
>;
/** Which storage kind each memory domain counts (MemoryKind in the backend). */
export const DOMAIN_KIND: Record<MemoryDomain, MemorySourceCount["kind"]> = {
  journal: "journal_entry",
  contacts: "contact",
  projects: "project",
  tasks: "task",
};
/** The memory domain a stored record kind belongs to. */
export function domainOfKind(kind: MemorySourceCount["kind"]): MemoryDomain {
  return MEMORY_DOMAINS.find((domain) => DOMAIN_KIND[domain] === kind)!;
}
export type MemoryStatus = ToolResults["get_memory_status"];
export type MemoryRemoval = Item<
  ToolResults["set_memory_settings"]["turning_off"]
>;
export type SetMemoryResult = ToolResults["set_memory_settings"];

/** One fact recall_memory returned, with the record it was derived from. */
export type RecalledFact = Item<ToolResults["recall_memory"]["facts"]>;
export type RecallResult = ToolResults["recall_memory"];
export type MemoryKind = MemorySourceCount["kind"];

/** A recall: free text, optionally narrowed to one kind of record (a memory source). */
export type RecallRequest = { query: string; kind?: MemoryKind };

export type MemoryChange = {
  expectedVersion: number;
  paused?: boolean;
  domain?: MemoryDomain;
  value?: boolean;
  /** Sent only after the owner confirmed in the app. */
  confirm?: boolean;
};

/** The month's AI cost as get_ai_usage reports it: spent of the cap, Claude Code's own estimate, and today's starts. */
export type AiUsage = ToolResults["get_ai_usage"];

/** What emptying the trash did: Tasks removed, and Tasks that had Steps or links left and so stayed. */
export type EmptyResult = { removed: number; kept: number };

export type ControlTransport = {
  /** One page of the trash, newest first; with a cursor, the page after the one that issued it. */
  trash: (cursor?: string) => Promise<TrashList>;
  restore: (item: TrashItem, key: string) => Promise<unknown>;
  /**
   * Removes one trashed Task for good. Absent where the host has no such tool (Claude has none; the phone does), and
   * the trash view then offers no way to delete anything permanently. Only a Task can be removed this way.
   */
  erase?: (item: TrashItem, key: string) => Promise<unknown>;
  /** Removes every trashed Task for good, with how many went and how many had to stay. Absent with `erase`. */
  empty?: (key: string) => Promise<EmptyResult>;
  changes: () => Promise<ChangesList>;
  /** Reverses a purchase or a put-back with set_shopping_item_purchased (the change's undo_tool). */
  undoPurchase: (change: ChangeRecord, key: string) => Promise<unknown>;
  memoryStatus: () => Promise<MemoryStatus>;
  setMemory: (change: MemoryChange) => Promise<SetMemoryResult>;
  /**
   * recall_memory: what Sidekick remembers, as a read only sample. Absent when the host does not offer the tool,
   * and the memory view then draws no "show what Sidekick remembers" and no search.
   */
  recall?: (request: RecallRequest) => Promise<RecallResult>;
  /** exclude_from_memory: keeps one source record out of memory. Absent with `recall`, for the same reason. */
  forget?: (fact: RecalledFact) => Promise<unknown>;
  /** The newest page of the owner's own Activity Center entries. Read only, no write goes through it. */
  activity: () => Promise<ActivityList>;
  /**
   * get_ai_usage: the month's AI cost. Absent where the host does not offer the tool; the row is then not drawn. It is
   * called only where the instance shows the row (ai-usage-row.tsx).
   */
  aiUsage?: () => Promise<AiUsage>;
};

/** What the trash view needs of a transport: the phone's trash screen builds just this, without the rest of Control. */
export type TrashTransport = Pick<
  ControlTransport,
  "trash" | "restore" | "erase" | "empty"
>;

export { writeFailure, type WriteFailure } from "../../lib/mcp/errors";

/** The only undo tool the app calls. Any other undo_tool value gets no button. */
export const UNDO_PURCHASE_TOOL = "set_shopping_item_purchased";

/** A change the app can reverse: a purchase or a put-back of a shopping item, via an existing tool. */
export function canUndo(change: ChangeRecord): boolean {
  return (
    change.undo_tool === UNDO_PURCHASE_TOOL &&
    change.kind === "shopping_item" &&
    change.state === "active"
  );
}
