/**
 * What the per-room planners (companion-shopping.ts, companion-journal.ts) share: the shape of a planned call, the
 * checks the transport hands them, and the two small things both need (a date, and a query from a closed key list).
 * The planners import nothing from companion-transport.ts at run time: the transport passes its checks in as
 * `PlanHelpers`, so the transport can list the planners' tools without an import cycle.
 */
import type { NativeQuery, NativeRequest } from "./sidekick-native";

export type Args = Record<string, unknown>;

/**
 * What the phone's outbox needs to send a write later when no answer comes: a purchase (`itemId`, `version`, the asked
 * state) or items added to a list (`listId` and the request body).
 */
export type Queueable =
  | { kind: "purchase"; itemId: string; version: number; purchased: boolean }
  | {
      kind: "add";
      listId: string;
      body: { items: Args[]; merge_duplicates?: boolean };
    };

/**
 * What was planned for one call: the request, the key to forget when the write is settled, and for a shopping write
 * what the outbox needs (`queue`).
 */
export type Planned = {
  request: NativeRequest;
  signature?: string;
  queue?: Queueable;
};

/** The transport's own checks. Each refuses with the closed `validation_error` before anything is sent. */
export type PlanHelpers = {
  invalid: () => never;
  /** Refuses an argument outside `allowed`. */
  onlyKeys: (args: Args, allowed: readonly string[]) => void;
  /** A UUID (any case), returned in lower case. */
  uuidOf: (value: unknown) => string;
  /** An integer of at least 1. */
  versionOf: (value: unknown) => number;
  /** The room's own idempotency key when it gave one, else the key kept for this action until it is settled. */
  keyOf: (given: unknown, signature: string) => string;
};

const DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

/** A real calendar date, YYYY-MM-DD. */
export function dateOf(value: unknown, h: PlanHelpers): string {
  if (typeof value !== "string") return h.invalid();
  const match = DATE.exec(value);
  if (!match) return h.invalid();
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const probe = new Date(Date.UTC(year, month - 1, day));
  if (
    probe.getUTCFullYear() !== year ||
    probe.getUTCMonth() !== month - 1 ||
    probe.getUTCDate() !== day
  )
    return h.invalid();
  return value;
}

/** A plain JSON object (not null, not a list). */
export function isRecord(value: unknown): value is Args {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * The query of a read: only keys in `allowed` (the path's own keys in `skip` are left out), null and undefined meaning
 * "not given", scalars as text. A key in `dates` must be a real date. Anything else refuses the whole call.
 */
export function queryOf(
  args: Args,
  allowed: readonly string[],
  skip: readonly string[],
  dates: readonly string[],
  h: PlanHelpers,
): NativeQuery {
  const query: NativeQuery = {};
  for (const [key, value] of Object.entries(args)) {
    if (skip.includes(key)) continue;
    if (!allowed.includes(key)) h.invalid();
    if (value === null || value === undefined) continue;
    if (dates.includes(key)) query[key] = dateOf(value, h);
    else if (typeof value === "string") query[key] = value;
    else if (typeof value === "number" && Number.isFinite(value))
      query[key] = String(value);
    else if (typeof value === "boolean") query[key] = String(value);
    else h.invalid();
  }
  return query;
}

/** `{ query }` when there is one, else nothing, so a request without a query carries none. */
export function withQuery(query: NativeQuery): { query?: NativeQuery } {
  return Object.keys(query).length > 0 ? { query } : {};
}
