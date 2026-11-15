/**
 * Record writes (a new or edited Task, Project or journal entry) that got no answer wait in the phone's outbox
 * (QueuedRecordWrite) until it sends them. Until then the server does not have them, so the room is answered with
 * stand-ins made here: the same shape as the tool's own result (a room cannot tell the difference), so the room shows
 * what the user wrote. A new record's stand-in has an id that is not a UUID and that never reaches the server; an edit's
 * stand-in is the record as the room last read it with the change laid over it, and keeps its version (the server has
 * not moved on). `queuedRecordIds` names them for the rooms, which draw them as waiting.
 */
import { isRecord, type Args } from "./companion-plan";
import type { QueuedRecordWrite } from "./sidekick-native";

/** The id of the stand-in of the record created under `key`. */
const QUEUED_PREFIX = "queued-";

export function queuedRecordId(key: string): string {
  return `${QUEUED_PREFIX}${key}`;
}

/** Whether an id is a stand-in's: such a record exists only on the phone so far. */
export function isQueuedRecordId(id: unknown): id is string {
  return typeof id === "string" && id.startsWith(QUEUED_PREFIX);
}

/** The most records remembered; the oldest read is forgotten first. */
const MAX_KNOWN = 400;

/**
 * The records the transport has seen in its answers (Tasks, Projects, journal entries, rows of lists), by lower-case id.
 * An edit that waits for the network is drawn from the last one seen, so it needs no read to make its stand-in.
 */
export class KnownRecords {
  private readonly records = new Map<string, Args>();

  /** Remembers every record in `body`: the ones it holds directly, and the ones in its lists. */
  remember(body: unknown): void {
    if (!isRecord(body)) return;
    for (const value of Object.values(body)) {
      if (Array.isArray(value)) value.forEach((item) => this.add(item));
      else this.add(value);
    }
  }

  get(id: string): Args | undefined {
    return this.records.get(id.toLowerCase());
  }

  private add(value: unknown): void {
    if (
      !isRecord(value) ||
      typeof value.id !== "string" ||
      typeof value.version !== "number"
    )
      return;
    const id = value.id.toLowerCase();
    const kept = this.records.get(id);
    this.records.delete(id);
    this.records.set(id, kept ? { ...kept, ...value } : value);
    if (this.records.size > MAX_KNOWN) {
      const oldest = this.records.keys().next();
      if (!oldest.done) this.records.delete(oldest.value);
    }
  }
}

type RecordWrite = Pick<QueuedRecordWrite, "kind" | "subjectId" | "body">;

/** The body without the named fields. */
function without(body: Args, names: readonly string[]): Args {
  return Object.fromEntries(
    Object.entries(body).filter(([name]) => !names.includes(name)),
  );
}

/** The fields of an edit's body that change the record: everything but the version it rests on. */
function changesOf(body: Args): Args {
  return without(body, ["version"]);
}

function listOf(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

/**
 * The answer of the tool for a write that is queued instead, or undefined when it cannot be made: an edit whose record
 * has not been seen (nothing to lay the change over). `key` is the key the write was sent with; `at` is when it was made.
 */
export function standInFor(
  write: RecordWrite,
  key: string,
  known: KnownRecords,
  at: number,
): Args | undefined {
  const stamp = new Date(at).toISOString();
  const { body } = write;
  switch (write.kind) {
    case "create_task":
      return {
        task: {
          description: null,
          due_at: null,
          project_id: null,
          domain_id: null,
          process_id: null,
          ...body,
          id: queuedRecordId(key),
          status: "todo",
          version: 1,
          created_at: stamp,
          updated_at: stamp,
        },
      };
    case "update_task":
    case "update_project": {
      const base = write.subjectId ? known.get(write.subjectId) : undefined;
      if (!base) return undefined;
      const record = { ...base, ...changesOf(body) };
      return write.kind === "update_task"
        ? { task: record }
        : { project: record };
    }
    case "write_journal_entry":
      return {
        entry: {
          archived: false,
          contact_ids: [],
          key_points: [],
          links: [],
          occurred_at: null,
          project_ids: [],
          source_id: "",
          summary: null,
          tags: [],
          task_ids: [],
          ...body,
          id: queuedRecordId(key),
          version: 1,
        },
      };
    case "update_journal_entry": {
      const base = write.subjectId ? known.get(write.subjectId) : undefined;
      if (!base) return undefined;
      // The appended text lives in the entry's source, which a stand-in does not carry.
      const entry: Args = {
        ...base,
        ...without(body, ["version", "append_key_points", "append_text"]),
      };
      if (body.append_key_points !== undefined)
        entry.key_points = [
          ...listOf(base.key_points),
          ...listOf(body.append_key_points),
        ];
      return { entry };
    }
    default:
      return undefined;
  }
}

/**
 * The ids the rooms draw as waiting: the stand-in of every new record, and every record with an edit in the outbox
 * (lower case).
 */
export function queuedRecordIds(
  records: readonly QueuedRecordWrite[],
): ReadonlySet<string> {
  return new Set(
    records.map((record) =>
      record.subjectId
        ? record.subjectId.toLowerCase()
        : queuedRecordId(record.key),
    ),
  );
}

/** The stand-in Task of a queued new one, for a read of its id; undefined when none waits under it. */
export function queuedTask(
  records: readonly QueuedRecordWrite[],
  id: string,
  known: KnownRecords,
): Args | undefined {
  const found = records.find(
    (record) =>
      record.kind === "create_task" && queuedRecordId(record.key) === id,
  );
  return found
    ? (standInFor(found, found.key, known, found.queuedAt)?.task as Args)
    : undefined;
}

/**
 * A `get_journal_day` answer with the entries written without a network on that day appended, so what the user wrote does
 * not vanish from the day while it waits. An answer that is not a day page, or a day with none waiting, is returned as it is.
 */
export function withQueuedEntries(
  body: Record<string, unknown>,
  journalDate: string,
  records: readonly QueuedRecordWrite[],
  known: KnownRecords,
): Record<string, unknown> {
  if (!Array.isArray(body.entries)) return body;
  const rows: unknown[] = body.entries;
  const extra = records
    .filter(
      (record) =>
        record.kind === "write_journal_entry" &&
        record.body.journal_date === journalDate,
    )
    .flatMap((record) => {
      const entry = standInFor(
        record,
        record.key,
        known,
        record.queuedAt,
      )?.entry;
      return entry ? [entry] : [];
    });
  return extra.length === 0 ? body : { ...body, entries: [...rows, ...extra] };
}
