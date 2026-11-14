/**
 * Journal App contract. The view sees only these typed calls; the MCP adapter maps them to
 * tools/call and reads structuredContent. Types follow contracts/mcp-tools.generated.json
 * (get_journal_day, get_journal_entry, get_journal_source, list_pending_journal, get_journal_draft
 * and update/reject/finalize_journal_draft). Extra fields are allowed. The app writes only on an
 * explicit owner action (reviewing a draft, or writing and editing an entry by hand); it creates
 * no source and calls no AI.
 */
import { isNotFound } from "../../lib/mcp/errors";
import { cursorFrom, isPlainObject } from "../../lib/mcp/shape";
import type { Item, WithOptional } from "../../lib/mcp/derived";
import type {
  ToolInputs,
  ToolResults,
} from "../../lib/mcp/tool-results.generated";
import type { RoomTransport } from "../mcp-apps/room-types";
import { withEntry } from "./entry-result";
import {
  createTagTransport,
  type TagSupport,
  type TagTransport,
} from "./tag-transport";

export type JournalKeyPoint =
  ToolResults["get_journal_entry"]["entry"]["key_points"][number];
/** One linked Project or Contact. `label` is its name; null when the read had no content or scope. */
export type JournalEntryLink = Item<
  ToolResults["get_journal_entry"]["entry"]["links"]
>;
/**
 * One Journal entry as get_journal_entry and get_journal_day return it (JournalEntryRecord).
 * `links` (the Projects and Contacts with their names) and `tags` (slugs) are absent from an older server.
 */
export type JournalEntry = WithOptional<
  ToolResults["get_journal_entry"]["entry"],
  "links" | "tags"
>;
type JournalDayResult = ToolResults["get_journal_day"];
/** Only the daily summary fields the day view shows (JournalSummaryRecord). */
export type JournalDaySummary = Pick<
  JournalDayResult["summary"],
  "journal_date" | "exists" | "status"
> & {
  content: Partial<
    Pick<NonNullable<JournalDayResult["summary"]["content"]>, "overview">
  > | null;
};
/** A Task completed on the day; a recurring one by its last completion. */
export type JournalDoneTask = Item<JournalDayResult["done"]["tasks"]>;
/** A step checked on the day, with the title of its Task. */
export type JournalDoneStep = Item<JournalDayResult["done"]["steps"]>;
/** A shopping item bought on the day and still bought. */
export type JournalDonePurchase = Item<JournalDayResult["done"]["purchases"]>;
/**
 * What was done on the day (the diary's `done` section): each list in time order, at most 50;
 * `counts` are the real totals and `truncated` is true when a list was cut.
 */
export type JournalDone = JournalDayResult["done"];
/** One day. `done` is absent from an older server: the day then shows no Gjort section. */
export type JournalDay = Pick<
  JournalDayResult,
  "journal_date" | "next_cursor"
> & {
  entries: JournalEntry[];
  summary: JournalDaySummary;
  done?: JournalDone;
  /** The owner's IANA zone, named by the server; absent from an older server. */
  owner_timezone?: string;
};
/** Source provenance; `raw_text` is present only when the read asked for it (JournalSourceReadRecord). */
export type JournalSource = WithOptional<
  Pick<
    ToolResults["get_journal_source"]["source"],
    | "id"
    | "source_type"
    | "journal_date"
    | "occurred_at"
    | "source_recorded_at"
    | "language"
    | "created_at"
    | "raw_text"
  >,
  "raw_text"
>;
export type JournalPendingItem = Item<
  ToolResults["list_pending_journal"]["items"]
>;
export type JournalPending = { items: JournalPendingItem[] };

type DraftRecord = ToolResults["get_journal_draft"]["draft"];
/**
 * A Task proposal as the draft carries it, and as finalize and update_journal_draft take it back.
 * It is the input type, which the draft's own proposals (all fields set) are assignable to; the
 * fields of an update proposal the draft leaves out are optional.
 */
export type JournalTaskProposal = Item<
  ToolInputs["finalize_journal_draft"]["task_proposals"]
>;
export type TaskPriority = Extract<
  JournalTaskProposal,
  { type: "create_task" }
>["priority"];
/** A Project, Task or Contact candidate the owner may link (catalog entry, scope filtered). */
type CatalogEntry = Item<DraftRecord["catalog"][keyof DraftRecord["catalog"]]>;
export type JournalCandidate = Pick<CatalogEntry, "id" | "label"> &
  Partial<Pick<CatalogEntry, "context" | "status">>;
export type JournalDraftSuggestion = Item<
  DraftRecord["suggestions"]["projects"]
>;
export type JournalDraftState = DraftRecord["state"];
/** get_journal_draft with content: the AI-derived draft the owner reviews (JournalDraftRecord). */
export type JournalDraft = Omit<
  DraftRecord,
  "run" | "catalog" | "task_proposals"
> & {
  catalog: { [K in keyof DraftRecord["catalog"]]: JournalCandidate[] };
  task_proposals: JournalTaskProposal[];
};
export type JournalDraftRead = { draft: JournalDraft; source: JournalSource };
/** What update/reject return: state and next version only, never the draft's content. */
export type JournalDraftStatus = {
  draft: Pick<
    ToolResults["update_journal_draft"]["draft"],
    "id" | "state" | "version"
  >;
};
type FinalizeInput = ToolInputs["finalize_journal_draft"];
export type RelationSelection = FinalizeInput["relation_selection"];
export type RelationChoice = Item<RelationSelection["project_ids"]>;
export type RelationOrigin = RelationChoice["origin"];
/** The fields update_journal_draft replaces; Task proposals are the draft's own, unchanged. */
export type JournalDraftFields = Pick<
  FinalizeInput,
  "title" | "summary" | "key_points"
>;
export type JournalFinalizeInput = JournalDraftFields & {
  relation_selection: RelationSelection;
  task_proposals: JournalTaskProposal[];
  /** The tags the owner set on the new entry (the complete set); absent: the entry starts without tags. */
  tags?: string[];
};
export type JournalFinalizeResult = Omit<
  ToolResults["finalize_journal_draft"],
  "entry"
> & { entry: JournalEntry };

/** The link changes update_journal_entry takes alone (links only: the content stays, the version moves on). */
export type JournalLinkChange = Pick<
  ToolInputs["update_journal_entry"],
  | "add_contact_ids"
  | "remove_contact_ids"
  | "add_project_ids"
  | "remove_project_ids"
>;

/** What write_journal_entry takes from the app: the owner's own words, saved as the source of the new entry. */
export type JournalEntryInput = Pick<
  ToolInputs["write_journal_entry"],
  "journal_date" | "title" | "source_text" | "occurred_at"
>;

export type JournalTransport = TagTransport & {
  /** One day with entry content and summary status; the view reads it for its own navigation. */
  getDay: (journalDate: string) => Promise<JournalDay>;
  /**
   * The days from `from` to `to` (YYYY-MM-DD, inclusive) that have at least one entry, for the dots in the day
   * strip. One list_journal_entries read for the whole range, without content: dates only. Optional, so a
   * transport without it shows a dot only for the day it has read.
   */
  listEntryDates?: (from: string, to: string) => Promise<string[]>;
  /** One owned entry; the app asks for content because the user opened their own entry. */
  getEntry: (entryId: string) => Promise<{ entry: JournalEntry }>;
  /**
   * One owned source with its original text, which is immutable. Optional: a host without get_journal_source (the
   * mobile app) leaves it out, and the entry view offers no link to the original.
   */
  getSource?: (sourceId: string) => Promise<{ source: JournalSource }>;
  /** One pending draft with its source text; the owner opened it to review it. */
  getDraft: (draftId: string) => Promise<JournalDraftRead>;
  /** Replaces the draft's title, summary, key points and Task proposals at `version`. */
  updateDraft: (
    draftId: string,
    version: number,
    fields: JournalDraftFields & { task_proposals: JournalTaskProposal[] },
    idempotencyKey: string,
  ) => Promise<JournalDraftStatus>;
  /** Terminal: the draft cannot be edited or finalized afterwards. */
  rejectDraft: (
    draftId: string,
    version: number,
    idempotencyKey: string,
  ) => Promise<JournalDraftStatus>;
  /** Terminal: creates the entry and applies only the kept Task proposals. */
  finalizeDraft: (
    draftId: string,
    version: number,
    input: JournalFinalizeInput,
    idempotencyKey: string,
  ) => Promise<JournalFinalizeResult>;
  /**
   * Adds or removes Project and Contact links of one entry at `version` (links only, content unchanged).
   * The answer is the entry with its new version and links. Optional: without it the view offers no unlink.
   */
  updateEntryLinks?: (
    entryId: string,
    version: number,
    change: JournalLinkChange,
    idempotencyKey: string,
  ) => Promise<{ entry: JournalEntry }>;
  /**
   * Writes a new entry from the owner's own words (no AI). Optional: without it the day offers no manual writing.
   * The answer is the saved entry.
   */
  writeEntry?: (
    input: JournalEntryInput,
    idempotencyKey: string,
  ) => Promise<{ entry: JournalEntry }>;
  /**
   * Replaces the entry's title, summary and key points at `version` (null summary clears it). The original text is
   * provenance and is never changed. Optional: without it the entry view offers no editing.
   */
  updateEntry?: (
    entryId: string,
    version: number,
    fields: JournalDraftFields,
    idempotencyKey: string,
  ) => Promise<{ entry: JournalEntry }>;
  /** Adds the owner's words to the entry as a new source at `version`; the earlier text is kept. */
  appendEntryText?: (
    entryId: string,
    version: number,
    text: string,
    idempotencyKey: string,
  ) => Promise<{ entry: JournalEntry }>;
  /**
   * Moves the entry to the trash at `version` (move_to_trash). The answer carries the trash record's version, which
   * `restoreEntry` needs for Undo. Optional: without it (or without `restoreEntry`) the entry view offers no delete.
   */
  trashEntry?: (
    entryId: string,
    version: number,
    idempotencyKey: string,
  ) => Promise<{ version: number }>;
  /**
   * The title of a linked Task (get_task), so the entry shows its Tasks by name. Optional: without it (a host without
   * get_task, or the Work room off) the entry shows the count of its Tasks.
   */
  getTaskTitle?: (taskId: string) => Promise<string>;
  /** Takes the entry back out of the trash (restore_from_trash) at the trash version `trashEntry` answered with. */
  restoreEntry?: (
    entryId: string,
    trashVersion: number,
    idempotencyKey: string,
  ) => Promise<unknown>;
};

/**
 * The journal transport over the host's tools/call. Reads, plus the draft review writes the owner
 * triggers explicitly. The app never creates a source or generates anything; every write carries the
 * draft version and an idempotency key.
 */
export function createJournalTransport(
  call: RoomTransport["call"],
  /** False: the host cannot read the original text (get_journal_source), so the transport has no `getSource`. */
  withSource = true,
  /** False: the host cannot change links (the mobile app), so the transport has no `updateEntryLinks`. */
  withLinks = true,
  /** True: the host offers move_to_trash and restore_from_trash for journal entries, so the entry can be deleted with Undo. */
  withTrash = false,
  /** True: the host offers get_task and the Work room is on, so a linked Task shows by its title. */
  withTaskTitles = false,
  /** What the host answers of tags: the vocabulary (list_tags), the tagged read and the entry's tag write. */
  withTags: TagSupport = { vocabulary: false, filter: false, write: false },
): JournalTransport {
  return {
    ...createTagTransport(call, withTags),
    ...(withTaskTitles
      ? {
          getTaskTitle: (taskId: string) =>
            call<{ task?: { title?: unknown } }>("get_task", {
              task_id: taskId,
            }).then(({ task }) => {
              if (typeof task?.title !== "string" || !task.title.trim())
                throw new Error("get_task answered without a title");
              return task.title;
            }),
        }
      : {}),
    // The server refuses a day with no entries as not_found; every day read shows it as an empty day.
    getDay: (journalDate) =>
      call<JournalDay>("get_journal_day", {
        journal_date: journalDate,
        include_content: true,
        limit: 50,
      }).then(
        // `done` is checked as the root's is; a malformed one is dropped, not drawn.
        ({ done, ...day }) => ({ ...day, ...withDone(done) }),
        (error: unknown) => {
          if (isNotFound(error)) return emptyDay(journalDate);
          throw error;
        },
      ),
    // One read for the strip's seven days. 50 is the tool's ceiling; a week with more entries than that marks
    // the days of the first 50 (oldest first), and the day view adds the day it has read.
    listEntryDates: (from, to) =>
      call<{ entries: { journal_date: string }[] }>("list_journal_entries", {
        from_date: from,
        to_date: to,
        include_content: false,
        limit: 50,
      }).then((page) => [
        ...new Set(
          (page.entries ?? [])
            .map((entry) => entry.journal_date)
            .filter((date) => typeof date === "string"),
        ),
      ]),
    getEntry: (entryId) =>
      call<{ entry: JournalEntry }>("get_journal_entry", {
        entry_id: entryId,
        include_content: true,
      }),
    ...(withSource
      ? {
          getSource: (sourceId: string) =>
            call<{ source: JournalSource }>("get_journal_source", {
              source_id: sourceId,
              include_content: true,
            }),
        }
      : {}),
    getDraft: (draftId) =>
      call<JournalDraftRead>("get_journal_draft", {
        draft_id: draftId,
        include_content: true,
      }),
    updateDraft: (draftId, version, fields, idempotencyKey) =>
      call<JournalDraftStatus>("update_journal_draft", {
        draft_id: draftId,
        expected_version: version,
        title: fields.title,
        summary: fields.summary,
        key_points: fields.key_points,
        task_proposals: fields.task_proposals,
        idempotency_key: idempotencyKey,
      }),
    rejectDraft: (draftId, version, idempotencyKey) =>
      call<JournalDraftStatus>("reject_journal_draft", {
        draft_id: draftId,
        expected_version: version,
        idempotency_key: idempotencyKey,
      }),
    finalizeDraft: (draftId, version, input, idempotencyKey) =>
      call<JournalFinalizeResult>("finalize_journal_draft", {
        draft_id: draftId,
        expected_version: version,
        title: input.title,
        summary: input.summary,
        key_points: input.key_points,
        relation_selection: input.relation_selection,
        task_proposals: input.task_proposals,
        ...(input.tags ? { tags: input.tags } : {}),
        idempotency_key: idempotencyKey,
      }),
    ...(withLinks
      ? {
          updateEntryLinks: (
            entryId: string,
            version: number,
            change: JournalLinkChange,
            idempotencyKey: string,
          ) =>
            call<{ entry: JournalEntry }>("update_journal_entry", {
              entry_id: entryId,
              expected_version: version,
              idempotency_key: idempotencyKey,
              ...change,
            }).then((result) => withEntry(result, "update_journal_entry")),
        }
      : {}),
    writeEntry: (input, idempotencyKey) =>
      call<{ entry: JournalEntry }>("write_journal_entry", {
        ...input,
        idempotency_key: idempotencyKey,
      }).then((result) => withEntry(result, "write_journal_entry")),
    // The server's replace mode needs title and key points together, and clears a summary that is left out.
    updateEntry: (entryId, version, fields, idempotencyKey) =>
      call<{ entry: JournalEntry }>("update_journal_entry", {
        entry_id: entryId,
        expected_version: version,
        idempotency_key: idempotencyKey,
        title: fields.title,
        summary: fields.summary,
        key_points: fields.key_points,
      }).then((result) => withEntry(result, "update_journal_entry")),
    appendEntryText: (entryId, version, text, idempotencyKey) =>
      call<{ entry: JournalEntry }>("update_journal_entry", {
        entry_id: entryId,
        expected_version: version,
        idempotency_key: idempotencyKey,
        append_text: text,
      }).then((result) => withEntry(result, "update_journal_entry")),
    ...(withTrash
      ? {
          trashEntry: (
            entryId: string,
            version: number,
            idempotencyKey: string,
          ) =>
            call<ToolResults["move_to_trash"]>("move_to_trash", {
              kind: "journal_entry",
              record_id: entryId,
              version,
              idempotency_key: idempotencyKey,
            }),
          restoreEntry: (
            entryId: string,
            trashVersion: number,
            idempotencyKey: string,
          ) =>
            call<ToolResults["restore_from_trash"]>("restore_from_trash", {
              kind: "journal_entry",
              record_id: entryId,
              version: trashVersion,
              idempotency_key: idempotencyKey,
            }),
        }
      : {}),
  };
}

/** One navigation frame. A day frame keeps its page, so going back shows it without a new read. */
export type JournalFrame =
  | {
      kind: "day";
      page: JournalDay;
      /** The tags the day view is filtered on (slugs); absent or empty: the day itself. Kept so Back returns to the list. */
      tags?: string[];
    }
  | {
      kind: "entry";
      id: string;
      /**
       * Set right after a draft was finalized: how many Tasks that created and updated, and the ids of the
       * created ones (from finalize_journal_draft's created_task_ids) so the view can open them.
       */
      notice?: { created: number; updated: number; createdTaskIds?: string[] };
    }
  | { kind: "draft"; id: string }
  | { kind: "source"; id: string }
  | { kind: "pending"; page: JournalPending };

export {
  isForbidden,
  writeFailure,
  type WriteFailure,
} from "../../lib/mcp/errors";

/** A day without entries or summary, the shape the day view draws as an empty day. */
function emptyDay(journalDate: string): JournalDay {
  return {
    journal_date: journalDate,
    entries: [],
    next_cursor: null,
    summary: {
      journal_date: journalDate,
      exists: false,
      status: null,
      content: null,
    },
  };
}

/**
 * Root of the app from the tool result that opened it. A get_journal_day result (journal_date
 * with entries and summary) opens a day; a get_journal_entry result (entry) opens an entry; and a
 * list_pending_journal result (items) opens the pending list. A get_journal_draft result (draft)
 * opens that draft for review; the draft frame reads the draft itself with its content. An id-only
 * `{ source: { id } }` opens the original of a source, and an `{ entry: { id }, notice }` (a draft
 * just saved, routed by the shell) opens the entry with its notice. The draft check comes before the
 * source check, because a get_journal_draft result also carries a `source`.
 */
export function rootFromToolResult(
  structured: unknown,
): JournalFrame | undefined {
  const data = structured as
    | {
        journal_date?: unknown;
        entries?: unknown;
        summary?: unknown;
        next_cursor?: unknown;
        entry?: { id?: unknown };
        items?: unknown;
        draft?: { id?: unknown };
        source?: { id?: unknown };
        notice?: unknown;
      }
    | null
    | undefined;
  if (
    typeof data?.journal_date === "string" &&
    Array.isArray(data.entries) &&
    data.entries.every(isJournalEntry) &&
    isPlainObject(data.summary)
  )
    return {
      kind: "day",
      page: {
        journal_date: data.journal_date,
        entries: data.entries,
        next_cursor: cursorFrom(data),
        summary: data.summary as JournalDaySummary,
        ...withDone((data as { done?: unknown }).done),
        ...withOwnerTimezone(
          (data as { owner_timezone?: unknown }).owner_timezone,
        ),
      },
    };
  const entryId = data?.entry?.id;
  if (typeof entryId === "string") {
    const notice = noticeFrom(data?.notice);
    return notice
      ? { kind: "entry", id: entryId, notice }
      : { kind: "entry", id: entryId };
  }
  const draftId = data?.draft?.id;
  if (typeof draftId === "string") return { kind: "draft", id: draftId };
  // Only the id-only reference opens the original; a full get_journal_source record does not open the room.
  const sourceRef = data?.source;
  if (
    sourceRef &&
    typeof sourceRef.id === "string" &&
    Object.keys(sourceRef).length === 1
  )
    return { kind: "source", id: sourceRef.id };
  if (Array.isArray(data?.items) && data.items.every(isPendingItem))
    return { kind: "pending", page: { items: data.items } };
  return undefined;
}

/**
 * The saved-draft notice of an entry result: how many Tasks were created and updated, and the ids of
 * the created ones. Anything else is no notice, so the entry opens as a plain entry.
 */
function noticeFrom(
  value: unknown,
): { created: number; updated: number; createdTaskIds?: string[] } | undefined {
  if (!isPlainObject(value)) return undefined;
  const { created, updated, createdTaskIds } = value;
  if (typeof created !== "number" || typeof updated !== "number")
    return undefined;
  if (createdTaskIds === undefined) return { created, updated };
  if (
    !Array.isArray(createdTaskIds) ||
    !createdTaskIds.every((id) => typeof id === "string")
  )
    return undefined;
  return { created, updated, createdTaskIds };
}

/** A Journal entry with the identity and dates the views need; other fields are optional. */
export function isJournalEntry(value: unknown): value is JournalEntry {
  const entry = value as
    | { id?: unknown; title?: unknown; journal_date?: unknown }
    | null
    | undefined;
  return (
    typeof entry?.id === "string" &&
    typeof entry.title === "string" &&
    typeof entry.journal_date === "string"
  );
}

function isPendingItem(value: unknown): value is JournalPendingItem {
  const item = value as
    | { source_id?: unknown; journal_date?: unknown; state?: unknown }
    | null
    | undefined;
  return (
    typeof item?.source_id === "string" &&
    typeof item.journal_date === "string" &&
    typeof item.state === "string"
  );
}

/**
 * The day's `done` when it has the shape the journal read returns: `tasks`, `steps` and `purchases`, each a list of objects whose id, title and time
 * (`completed_at`, or `purchased_at` for purchases) are strings. `counts` falls back to the list lengths and `truncated` to false. Anything else, or an older server
 * without the field, gives no `done`, and the day shows no Gjort section.
 */
export function doneFrom(value: unknown): JournalDone | undefined {
  if (!isPlainObject(value)) return undefined;
  const list = <T>(items: unknown, time: string): T[] | undefined =>
    Array.isArray(items) &&
    items.every(
      (item) =>
        isPlainObject(item) &&
        typeof item.id === "string" &&
        typeof item.title === "string" &&
        typeof item[time] === "string",
    )
      ? (items as T[])
      : undefined;
  const tasks = list<JournalDoneTask>(value.tasks, "completed_at");
  const steps = list<JournalDoneStep>(value.steps, "completed_at");
  const purchases = list<JournalDonePurchase>(value.purchases, "purchased_at");
  if (!tasks || !steps || !purchases) return undefined;
  const counts = isPlainObject(value.counts) ? value.counts : {};
  const count = (n: unknown, shown: number) =>
    typeof n === "number" && Number.isFinite(n) ? Math.max(n, shown) : shown;
  return {
    tasks,
    steps,
    purchases,
    counts: {
      tasks: count(counts.tasks, tasks.length),
      steps: count(counts.steps, steps.length),
      purchases: count(counts.purchases, purchases.length),
    },
    truncated: value.truncated === true,
  };
}

/** The owner's zone the server named on a day result; anything but a non-empty string is left out. */
function withOwnerTimezone(value: unknown): { owner_timezone?: string } {
  return typeof value === "string" && value ? { owner_timezone: value } : {};
}

function withDone(value: unknown): { done?: JournalDone } {
  const done = doneFrom(value);
  return done ? { done } : {};
}
