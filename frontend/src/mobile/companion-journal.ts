/**
 * The Journal room's calls over the companion routes (ADR-005). Each tool the room asks for maps,
 * from this CLOSED list, to one named route; the answer is the tool's own structuredContent, so the room cannot tell
 * the difference. No generic execute, no path from the caller, no argument outside what the route takes.
 *
 *   get_journal_day       -> GET  /companion/v1/journal/days/{journal_date}       (include_content, limit, cursor)
 *   list_journal_entries  -> GET  /companion/v1/journal/entries                   (from_date, to_date, include_content, limit, cursor)
 *   get_journal_entry     -> GET  /companion/v1/journal/entries/{entry_id}        (include_content)
 *   get_journal_source   -> GET  /companion/v1/journal/sources/{source_id}        (include_content): the text a hand-written entry keeps
 *   write_journal_entry   -> POST /companion/v1/journal/entries                   (the owner's own words; no key in the body)
 *   update_journal_entry  -> POST /companion/v1/journal/entries/{entry_id}/update ({ version, ...the changes })
 *
 * Every write sends its key in the Idempotency-Key header. `expected_version` of the tool is `version` in the body.
 * Not in the app: the AI drafts and the review of them, the daily summary and the manual/source creators; the room
 * hides what needs them (`toolOffered`). The original text is read back (a hand-written entry has no summary, its
 * words live only in the source).
 */
import {
  dateOf,
  isRecord,
  queryOf,
  withQuery,
  type Args,
  type PlanHelpers,
  type Planned,
} from "./companion-plan";

/** The routes, for reading and for the contract tests that compare them with the backend. Nothing is built from it. */
export const JOURNAL_ROUTES = {
  get_journal_day: {
    method: "GET",
    path: "/companion/v1/journal/days/{journal_date}",
  },
  list_journal_entries: {
    method: "GET",
    path: "/companion/v1/journal/entries",
  },
  get_journal_entry: {
    method: "GET",
    path: "/companion/v1/journal/entries/{entry_id}",
  },
  get_journal_source: {
    method: "GET",
    path: "/companion/v1/journal/sources/{source_id}",
  },
  write_journal_entry: {
    method: "POST",
    path: "/companion/v1/journal/entries",
  },
  update_journal_entry: {
    method: "POST",
    path: "/companion/v1/journal/entries/{entry_id}/update",
  },
} as const;

/** The tool names this planner answers. */
export const JOURNAL_TOOLS = [
  "get_journal_day",
  "list_journal_entries",
  "get_journal_entry",
  "get_journal_source",
  "write_journal_entry",
  "update_journal_entry",
] as const;

const BASE = "/companion/v1/journal";

const WRITE_KEYS = [
  "journal_date",
  "title",
  "source_text",
  "occurred_at",
  "summary",
  "key_points",
  "project_ids",
  "task_ids",
  "contact_ids",
  "language",
] as const;

const UPDATE_KEYS = [
  "entry_id",
  "expected_version",
  "idempotency_key",
  "title",
  "summary",
  "key_points",
  "append_key_points",
  "append_text",
] as const;

/**
 * The link changes the app never sends: changing a link needs projects:read / contacts:read, which a Dagbok
 * device does not hold (the server refuses the fields with a 422). The planner refuses them before a request,
 * and the transport answers `supportsCall` no so the entry view offers no unlinking.
 */
export const JOURNAL_LINK_KEYS = [
  "add_contact_ids",
  "remove_contact_ids",
  "add_project_ids",
  "remove_project_ids",
] as const;

/** The planned call for a journal tool, or undefined when the name is not one of them. */
export function planJournal(
  name: string,
  args: Args,
  h: PlanHelpers,
): Planned | undefined {
  /** A write: the signature is the action itself, so a retry of the same action sends the same key. */
  const write = (path: string, body: Args): Planned => {
    const signature = JSON.stringify([name, path, body]);
    return {
      request: {
        method: "POST",
        path,
        body,
        idempotencyKey: h.keyOf(args.idempotency_key, signature),
      },
      signature,
    };
  };
  const text = (value: unknown): string =>
    typeof value === "string" ? value : h.invalid();
  const records = (value: unknown): Args[] =>
    Array.isArray(value) && value.every(isRecord) ? value : h.invalid();
  const ids = (value: unknown): string[] =>
    Array.isArray(value) ? value.map((id) => h.uuidOf(id)) : h.invalid();
  /** The given fields, converted by `kinds`; null (on a write, undefined) is dropped unless `keepNull`. */
  const fields = (
    keys: readonly string[],
    kinds: Record<string, (value: unknown) => unknown>,
    keepNull: readonly string[],
  ): Args => {
    const body: Args = {};
    for (const key of keys) {
      const value = args[key];
      if (value === undefined) continue;
      if (value === null) {
        if (keepNull.includes(key)) body[key] = null;
        continue;
      }
      body[key] = (kinds[key] ?? ((v: unknown) => v))(value);
    }
    return body;
  };

  switch (name) {
    case "get_journal_day": {
      const day = dateOf(args.journal_date, h);
      return {
        request: {
          method: "GET",
          path: `${BASE}/days/${day}`,
          ...withQuery(
            queryOf(
              args,
              ["include_content", "limit", "cursor"],
              ["journal_date"],
              [],
              h,
            ),
          ),
        },
      };
    }
    case "list_journal_entries":
      return {
        request: {
          method: "GET",
          path: `${BASE}/entries`,
          ...withQuery(
            queryOf(
              args,
              ["from_date", "to_date", "include_content", "limit", "cursor"],
              [],
              ["from_date", "to_date"],
              h,
            ),
          ),
        },
      };
    case "get_journal_entry": {
      const id = h.uuidOf(args.entry_id);
      return {
        request: {
          method: "GET",
          path: `${BASE}/entries/${id}`,
          ...withQuery(queryOf(args, ["include_content"], ["entry_id"], [], h)),
        },
      };
    }
    case "get_journal_source": {
      const id = h.uuidOf(args.source_id);
      return {
        request: {
          method: "GET",
          path: `${BASE}/sources/${id}`,
          ...withQuery(
            queryOf(args, ["include_content"], ["source_id"], [], h),
          ),
        },
      };
    }
    case "write_journal_entry": {
      h.onlyKeys(args, [...WRITE_KEYS, "idempotency_key"]);
      const day = dateOf(args.journal_date, h);
      const body = fields(
        WRITE_KEYS,
        {
          journal_date: () => day,
          title: text,
          source_text: text,
          occurred_at: text,
          summary: text,
          language: text,
          key_points: records,
          project_ids: ids,
          task_ids: ids,
          contact_ids: ids,
        },
        [],
      );
      // The day, the title and the owner's words are required; the server judges the rest.
      if (
        typeof body.title !== "string" ||
        typeof body.source_text !== "string"
      )
        return h.invalid();
      return write(`${BASE}/entries`, body);
    }
    case "update_journal_entry": {
      h.onlyKeys(args, UPDATE_KEYS);
      const id = h.uuidOf(args.entry_id);
      const version = h.versionOf(args.expected_version);
      const body = fields(
        UPDATE_KEYS.filter(
          (key) =>
            key !== "entry_id" &&
            key !== "expected_version" &&
            key !== "idempotency_key",
        ),
        {
          title: text,
          summary: text,
          append_text: text,
          key_points: records,
          append_key_points: records,
        },
        // A null summary clears it (the entry editor's replace mode); the other fields have no null.
        ["summary"],
      );
      return write(`${BASE}/entries/${id}/update`, { version, ...body });
    }
    default:
      return undefined;
  }
}
