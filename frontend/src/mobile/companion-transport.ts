/**
 * CompanionRoomTransport: the mobile app's RoomTransport (room-types.ts). A room calls it the way it calls the
 * backend tools (`call("get_task", { task_id })`). Each call is mapped from a closed list to one companion route
 * (COMPANION_ROUTES) and answered as HostBridge.call answers: the tool's structuredContent, or a HostToolError with
 * the server's closed error code. The rooms cannot tell the difference.
 *
 * Why closed: no generic execute, no URL or path from the caller, and no unknown arguments passed through. A tool
 * not on the list, or arguments its route does not take, fails with NotInAppError before anything is sent.
 * update_task is answered only for the two changes the app makes: completing `{ status: "completed" }` and
 * reopening `{ status: "todo" }`. The network itself is the typed SidekickNative plugin.
 *
 * Shopping, Journal and license tools are planned by companion-shopping.ts, companion-journal.ts and
 * companion-license.ts; the default branch of plan() asks them in turn.
 *
 * Offline: a call that got no answer because of the connection (the native codes `network` and `timeout`) fails with
 * CompanionNetworkError, so the room says `network`. A shopping purchase that got no answer is put in
 * the phone's outbox with its key instead and fails with CompanionQueuedError: the room shows it as waiting for the
 * network, not as failed. Items added without an answer are put in the outbox the same way, but the call succeeds with
 * stand-in rows (companion-queued-adds.ts): the room reads on, and the list shows them as waiting until the outbox has
 * sent them, with the key of the first attempt so the server never adds them twice. A shopping, Agenda or Task detail
 * read may be answered from the phone's offline copy; `offline.readAt` tells when that copy was read.
 * `offline.queuedCompletions` names the Tasks ticked and not yet sent (by the widget too), for the room to draw as done.
 */
import { HostToolError } from "@/features/mcp-apps/bridge";
import { keyFor, type PendingKey } from "@/features/mcp-apps/idempotency";
import type {
  OfflineSupport,
  RoomTransport,
} from "@/features/mcp-apps/room-types";
import type { CompanionErrorCode } from "@/lib/mcp/errors";
import {
  isConnectionCode,
  nativeErrorCode,
  nativeErrorGeneration,
  type QueuedShoppingAdd,
  type SidekickNativePlugin,
  type NativeQuery,
} from "./sidekick-native";
import type { PlanHelpers, Planned, Queueable } from "./companion-plan";
import {
  JOURNAL_LINK_KEYS,
  JOURNAL_TOOLS,
  planJournal,
} from "./companion-journal";
import { LICENSE_TOOLS, planLicense } from "./companion-license";
import {
  queuedAddResult,
  queuedItems,
  withQueuedAdds,
} from "./companion-queued-adds";
import { SHOPPING_TOOLS, planShopping } from "./companion-shopping";

/** The routes, for reading and for the contract tests that compare them with the backend. Nothing is built from it. */
export const COMPANION_ROUTES = {
  get_work_agenda: { method: "GET", path: "/companion/v1/work/agenda" },
  get_task: { method: "GET", path: "/companion/v1/tasks/{task_id}" },
  complete_task: {
    method: "POST",
    path: "/companion/v1/tasks/{task_id}/complete",
  },
  reopen_task: {
    method: "POST",
    path: "/companion/v1/tasks/{task_id}/reopen",
  },
  list_task_steps: {
    method: "GET",
    path: "/companion/v1/tasks/{task_id}/steps",
  },
  list_task_contacts: {
    method: "GET",
    path: "/companion/v1/tasks/{task_id}/contacts",
  },
  list_task_external_references: {
    method: "GET",
    path: "/companion/v1/tasks/{task_id}/external-references",
  },
  get_work_hierarchy: { method: "GET", path: "/companion/v1/work/hierarchy" },
  get_project: { method: "GET", path: "/companion/v1/projects/{project_id}" },
  list_project_tasks: {
    method: "GET",
    path: "/companion/v1/projects/{project_id}/tasks",
  },
  get_domain: { method: "GET", path: "/companion/v1/domains/{domain_id}" },
  get_process: { method: "GET", path: "/companion/v1/processes/{process_id}" },
  complete_task_step: {
    method: "POST",
    path: "/companion/v1/steps/{step_id}/complete",
  },
  reopen_task_step: {
    method: "POST",
    path: "/companion/v1/steps/{step_id}/reopen",
  },
} as const;

/** The tool names the transport answers. update_task is answered only for the completing change. */
export const COMPANION_TOOLS = [
  "get_work_agenda",
  "get_task",
  "complete_task",
  "update_task",
  "list_task_steps",
  "list_task_contacts",
  "list_task_external_references",
  "get_work_hierarchy",
  "get_project",
  "list_tasks",
  "get_domain",
  "get_process",
  "complete_task_step",
  "update_task_step",
  ...SHOPPING_TOOLS,
  ...JOURNAL_TOOLS,
  ...LICENSE_TOOLS,
] as const;

/** The arguments get_work_agenda takes (contracts/mcp-tools.generated.json); anything else is refused. */
const AGENDA_QUERY_KEYS: ReadonlySet<string> = new Set([
  "actionable",
  "archive",
  "attention",
  "cursor",
  "estimate",
  "group",
  "include_undated",
  "kind",
  "limit",
  "max_minutes",
  "priority",
  "q",
  "sort",
  "status",
  "tag_match",
  "tags",
  "waiting",
]);

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const ERROR_CODE = /^[a-z][a-z0-9_]{0,63}$/;

/**
 * No answer came because of the connection (no network, or none in time). Not a HostToolError: the room's error notice
 * reads it as the connection (`networkFailure`, `maybeConnection` match by name). The code is the native one.
 */
export class CompanionNetworkError extends Error {
  constructor(readonly code: "network" | "timeout") {
    super("No connection");
    this.name = "CompanionNetworkError";
  }
}

/**
 * A purchase that got no answer now waits in the phone's outbox, which sends it with the same key once a network
 * exists. `purchased` is the state that will be sent. Matched by name (`isQueuedPurchase`).
 */
export class CompanionQueuedError extends Error {
  constructor(readonly purchased: boolean) {
    super("Waiting for network");
    this.name = "CompanionQueuedError";
  }
}

/** The tool is not offered in the mobile app (yet). A room shows it as its ordinary failure state. */
export class NotInAppError extends HostToolError {
  constructor() {
    super("not_in_app");
    this.name = "NotInAppError";
    this.message = "Not available in the app yet";
  }
}

type Args = Record<string, unknown>;

function isArgs(value: unknown): value is Args {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** The arguments were outside what the route takes. Nothing was sent. */
function invalid(): never {
  throw new HostToolError("validation_error");
}

function uuidOf(id: unknown): string {
  if (typeof id !== "string" || !UUID.test(id)) invalid();
  return id.toLowerCase();
}

function idOf(args: Args, key: string): string {
  return uuidOf(args[key]);
}

function taskIdOf(args: Args): string {
  return idOf(args, "task_id");
}

function versionValue(version: unknown): number {
  if (typeof version !== "number" || !Number.isInteger(version) || version < 1)
    invalid();
  return version;
}

function versionOf(args: Args): number {
  return versionValue(args.version);
}

function onlyKeys(args: Args, allowed: readonly string[]) {
  for (const key of Object.keys(args)) if (!allowed.includes(key)) invalid();
}

/** Query text for one agenda argument; null and undefined mean "not given". */
function queryValue(value: unknown): string | string[] | undefined {
  if (value === null || value === undefined) return undefined;
  if (typeof value === "string") return value;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  if (typeof value === "boolean") return String(value);
  if (Array.isArray(value) && value.every((item) => typeof item === "string"))
    return value;
  return invalid();
}

/** The query of a sub-list: only the keys the tool takes, null/undefined meaning "not given". The id is the path's. */
function listQuery(
  args: Args,
  allowed: readonly string[],
  idKey = "task_id",
): NativeQuery {
  const query: NativeQuery = {};
  for (const [key, value] of Object.entries(args)) {
    if (key === idKey) continue;
    if (!allowed.includes(key)) invalid();
    const text = queryValue(value);
    if (text !== undefined) query[key] = text;
  }
  return query;
}

function agendaQuery(args: Args): NativeQuery {
  const query: NativeQuery = {};
  for (const [key, value] of Object.entries(args)) {
    if (!AGENDA_QUERY_KEYS.has(key)) invalid();
    const text = queryValue(value);
    if (text !== undefined) query[key] = text;
  }
  return query;
}

/** The one change update_task is answered for: the tick, `{ status: "completed" }` and nothing else. */
function isCompletingChange(changes: unknown): boolean {
  return (
    isArgs(changes) &&
    Object.keys(changes).length === 1 &&
    changes.status === "completed"
  );
}

/**
 * The other change update_task is answered for: back to open, `{ status: "todo" }` and nothing else. The backend's
 * reopen route sets exactly "todo" and only on a completed Task, so no other status is ever answered.
 */
function isReopeningChange(changes: unknown): boolean {
  return (
    isArgs(changes) &&
    Object.keys(changes).length === 1 &&
    changes.status === "todo"
  );
}

/**
 * The one list_tasks the app answers: a Project's tasks, `project_id` with only paging next to it. Anything else
 * (the unsorted page, a Process, a status filter) has no route.
 */
function isProjectTaskList(args: Args): boolean {
  return (
    typeof args.project_id === "string" &&
    UUID.test(args.project_id) &&
    Object.keys(args).every((key) =>
      ["project_id", "limit", "cursor"].includes(key),
    )
  );
}

/** The arguments get_work_hierarchy takes (contracts/mcp-tools.generated.json); anything else is refused. */
const HIERARCHY_QUERY_KEYS = ["limit", "cursor", "include_tasks", "process_id"];

/**
 * A hierarchy read the route takes: only its own arguments, a whole `limit` of 1 to 100, a text `cursor`, a boolean
 * `include_tasks`, and `process_id` (a uuid) only together with `include_tasks: true`, as the server insists.
 */
function isHierarchyRead(args: Args): boolean {
  if (!Object.keys(args).every((key) => HIERARCHY_QUERY_KEYS.includes(key)))
    return false;
  const { limit, cursor, include_tasks: tasks, process_id: process } = args;
  const given = (value: unknown) => value !== undefined && value !== null;
  if (
    given(limit) &&
    !(typeof limit === "number" && Number.isInteger(limit) && limit >= 1)
  )
    return false;
  if (given(cursor) && typeof cursor !== "string") return false;
  if (given(tasks) && typeof tasks !== "boolean") return false;
  if (given(process))
    return typeof process === "string" && UUID.test(process) && tasks === true;
  return true;
}

/**
 * The one list_tasks of a Process the app answers: `process_id` with `limit` next to it. The phone has no route that
 * lists a Process's Tasks, so it asks the hierarchy for them (include_tasks with process_id) and answers one page: a
 * cursor other than null is refused, because the hierarchy's cursor pages its nodes, not its Tasks. The server has no
 * cursor for the Tasks past its cap, so the answer says `truncated` instead.
 */
function isProcessTaskList(args: Args): boolean {
  return (
    typeof args.process_id === "string" &&
    UUID.test(args.process_id) &&
    (args.cursor === undefined || args.cursor === null) &&
    Object.keys(args).every((key) =>
      ["process_id", "limit", "cursor"].includes(key),
    )
  );
}

/**
 * A hierarchy answer as list_tasks answers a Process: its Tasks (id, title, status, version, due date), one page. The
 * server caps the Tasks of a Process and has no cursor for the rest, so `truncated` is carried through for the app to
 * say that the list is cut; `next_cursor` stays null because there is no next page to ask for.
 */
function processTaskPage(body: Args): Args {
  if (!Array.isArray(body.tasks)) throw new HostToolError(undefined);
  const tasks = body.tasks.filter(isArgs).map((task) => ({
    id: task.id,
    title: task.title,
    status: task.status,
    version: task.version,
    due_at: task.due_at ?? null,
  }));
  return { tasks, next_cursor: null, truncated: body.truncated === true };
}

/** The closed status -> code table for answers whose body names no code of its own. */
function codeOfStatus(status: number): CompanionErrorCode | undefined {
  switch (status) {
    case 401:
      return "unauthorized";
    case 403:
      return "forbidden";
    case 404:
      return "not_found";
    case 409:
      return "conflict";
    case 400:
    case 422:
      return "validation_error";
    case 405:
      return "method_not_allowed";
    default:
      return undefined;
  }
}

/** The server's closed error code when its body carries one; else the code of the status; never free text. */
function errorCodeOf(status: number, body: unknown): string | undefined {
  const code = isArgs(body) ? body.code : undefined;
  if (typeof code === "string" && ERROR_CODE.test(code)) return code;
  return codeOfStatus(status);
}

/** What was planned for one call: the request, the key to forget when the write is settled, and what to queue. */
type Plan = Planned;

/** The plugin as the transport uses it: `request`, and the outbox and its event where the plugin has them. */
type NativeForTransport = Pick<SidekickNativePlugin, "request"> &
  Partial<
    Pick<
      SidekickNativePlugin,
      "queuePurchase" | "queueShoppingAdd" | "queuedWrites" | "addListener"
    >
  >;

const NOTHING_QUEUED = { purchases: [], adds: [], completions: [] } as const;

export class CompanionRoomTransport implements RoomTransport {
  /** Keys of writes that were sent without a key of the room's own, until the write is settled. */
  private readonly pending = new Map<string, PendingKey>();
  /** The answers that came from the phone's offline copy, with when that copy was read. */
  private readonly copies = new WeakMap<object, number>();
  /** The room's listeners of the outbox, told also when this transport itself put something in it. */
  private readonly queueListeners = new Set<() => void>();

  constructor(private readonly native: NativeForTransport) {}

  /** Arrow properties, so a room may take `transport.call` out of the object (WorkRoom does). */
  call = async <T>(name: string, args: object): Promise<T> => {
    const plan = this.plan(name, args);
    let answer;
    try {
      answer = await this.native.request(plan.request);
    } catch (error) {
      // No answer came. The write may or may not have reached the server: its key stays for the retry.
      const code = nativeErrorCode(error);
      if (!isConnectionCode(code)) throw new HostToolError(undefined);
      if (plan.queue) {
        const stored = await this.queue(
          plan,
          plan.queue,
          nativeErrorGeneration(error),
        );
        if (stored !== undefined) return stored as T;
      }
      throw new CompanionNetworkError(code);
    }
    const { status } = answer;
    const { body } = answer;
    // Any definite answer below 500 settles the action, so its key is forgotten; a 5xx may be retried with it.
    if (plan.signature !== undefined && status < 500)
      this.pending.delete(plan.signature);
    if (status < 200 || status >= 300)
      throw new HostToolError(errorCodeOf(status, body));
    if (!isArgs(body)) throw new HostToolError(undefined);
    let page: Args = body;
    if (name === "get_shopping_list") page = await this.withQueued(args, body);
    else if (name === "list_tasks" && "process_id" in args)
      page = processTaskPage(body);
    if (typeof answer.cachedAt === "number")
      this.copies.set(page, answer.cachedAt);
    return page as T;
  };

  /** A list page with the items still waiting in the outbox appended; the page as it is when nothing waits or it is not this list's. */
  private async withQueued(
    args: object,
    body: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const { list_id: listId, store } = args as Args;
    if (typeof listId !== "string") return body;
    const { adds } = await this.queuedWrites();
    return withQueuedAdds(
      body,
      listId.toLowerCase(),
      typeof store === "string" ? store : undefined,
      adds,
    );
  }

  /** The outbox as the phone holds it; nothing when it cannot be read. */
  private async queuedWrites() {
    if (!this.native.queuedWrites) return NOTHING_QUEUED;
    try {
      // `completions` is absent from an older phone build.
      const { purchases, adds, completions } = await this.native.queuedWrites();
      return { purchases, adds, completions: completions ?? [] };
    } catch {
      return NOTHING_QUEUED;
    }
  }

  /**
   * The closed list is the answer: a room hides what it would call outside it (saved views, Control, archived).
   * update_task is listed for the two changes it answers, the completing tick and the reopening.
   */
  supportsTool: NonNullable<RoomTransport["supportsTool"]> = (name) =>
    (COMPANION_TOOLS as readonly string[]).includes(name);

  /**
   * The call itself, for the one tool the list answers in part: update_task with the completing change, and with the
   * reopening change when the asker names a completed Task (`from_status`; a question without it is answered no).
   * A room hides a date or status choice that would be refused, and keeps `markDone`, `undo` and `reopenTask`.
   * update_journal_entry is answered no when the asker names a link change (the Journal device has no right to it) or tags,
   * and list_journal_entries when it asks for tags: the companion routes take neither, so the Journal room shows no tag
   * filter or tag editing on the phone.
   */
  supportsCall: NonNullable<RoomTransport["supportsCall"]> = (name, args) => {
    if (name === "list_tasks")
      return (
        isArgs(args) && (isProjectTaskList(args) || isProcessTaskList(args))
      );
    if (name === "get_work_hierarchy")
      return isArgs(args) && isHierarchyRead(args);
    if (name === "update_task_step")
      return isArgs(args) && isReopeningChange(args.changes);
    if (name === "list_journal_entries")
      return this.supportsTool(name) && isArgs(args) && !("tags" in args);
    if (name === "update_journal_entry")
      return (
        this.supportsTool(name) &&
        isArgs(args) &&
        !("tags" in args) &&
        JOURNAL_LINK_KEYS.every((key) => !(key in args))
      );
    if (name !== "update_task") return this.supportsTool(name);
    if (!isArgs(args)) return false;
    if (isCompletingChange(args.changes)) return true;
    return isReopeningChange(args.changes) && args.from_status === "completed";
  };

  /** The phone's offline copy and outbox, for the Shopping room (room-types.ts `OfflineSupport`). */
  offline: OfflineSupport = {
    readAt: (result) => this.copies.get(result),
    // Items added without a network are listed with the purchases, by the id of their stand-in row: waiting, not bought.
    queuedPurchases: async () => {
      const { purchases, adds } = await this.queuedWrites();
      const waiting = new Map<string, boolean>(
        purchases.map((entry) => [entry.itemId, entry.purchased] as const),
      );
      for (const add of adds)
        for (const item of queuedItems(add)) waiting.set(item.id, false);
      return waiting;
    },
    // The Tasks ticked and not yet sent, whoever ticked them (the widget shares the outbox): drawn as done.
    queuedCompletions: async () => {
      const { completions } = await this.queuedWrites();
      return new Set(completions.map((entry) => entry.taskId.toLowerCase()));
    },
    onQueueChanged: (listener) => {
      this.queueListeners.add(listener);
      const handle = this.native.addListener?.("queueChanged", listener);
      return () => {
        this.queueListeners.delete(listener);
        void handle?.then((h) => h.remove()).catch(() => undefined);
      };
    },
  };

  /**
   * Puts the write that got no answer in the outbox with the key it was sent with, bound to the pairing generation the
   * request began under (a late failure after an unpair is refused by the phone). A purchase then fails with
   * CompanionQueuedError; added items are answered with their stand-in rows (and the room's listeners are told, so it
   * lists them as waiting). Undefined when it cannot be kept: the caller fails with the connection error.
   */
  private async queue(
    plan: Plan,
    queue: Queueable,
    generation: number | undefined,
  ): Promise<unknown> {
    const key = plan.request.idempotencyKey;
    // Without the generation the failed request began under, the phone could not tell a pairing that has since ended.
    if (!key || generation === undefined) return undefined;
    if (queue.kind === "purchase") {
      if (!this.native.queuePurchase) return undefined;
      let kept;
      try {
        kept = await this.native.queuePurchase({
          itemId: queue.itemId,
          version: queue.version,
          purchased: queue.purchased,
          generation,
          idempotencyKey: key,
        });
      } catch {
        return undefined;
      }
      if (!kept.queued) return undefined;
      // The outbox owns the action now; its key is no longer the transport's to keep.
      if (plan.signature !== undefined) this.pending.delete(plan.signature);
      throw new CompanionQueuedError(kept.purchased ?? queue.purchased);
    }
    if (!this.native.queueShoppingAdd) return undefined;
    try {
      const kept = await this.native.queueShoppingAdd({
        generation,
        listId: queue.listId,
        idempotencyKey: key,
        body: queue.body,
      });
      if (!kept.queued) return undefined;
    } catch {
      return undefined;
    }
    if (plan.signature !== undefined) this.pending.delete(plan.signature);
    const add: QueuedShoppingAdd = {
      listId: queue.listId,
      key,
      queuedAt: Date.now(),
      items: queue.body.items,
      mergeDuplicates: queue.body.merge_duplicates === true,
    };
    // Before the answer: the room reads the list next, and must already know which of its rows are waiting.
    for (const listener of [...this.queueListeners]) listener();
    return queuedAddResult(add);
  }

  /** The mobile app is always full: the room that asks is told it already is. */
  requestDisplayMode: RoomTransport["requestDisplayMode"] = () =>
    Promise.resolve("fullscreen");

  /** The mobile app has no model to tell. */
  updateModelContext: RoomTransport["updateModelContext"] = () =>
    Promise.resolve();

  private plan(name: string, rawArgs: object): Plan {
    if (!isArgs(rawArgs)) invalid();
    switch (name) {
      case "get_work_agenda":
        return {
          request: {
            method: "GET",
            path: COMPANION_ROUTES.get_work_agenda.path,
            query: agendaQuery(rawArgs),
          },
        };
      case "get_task":
        onlyKeys(rawArgs, ["task_id"]);
        return {
          request: {
            method: "GET",
            path: `/companion/v1/tasks/${taskIdOf(rawArgs)}`,
          },
        };
      case "list_task_steps":
        return this.taskList(rawArgs, "steps", ["limit", "cursor"]);
      case "list_task_contacts":
        return this.taskList(rawArgs, "contacts", ["limit", "cursor"]);
      case "list_task_external_references":
        return this.taskList(rawArgs, "external-references", [
          "limit",
          "cursor",
        ]);
      case "get_work_hierarchy": {
        if (!isHierarchyRead(rawArgs)) invalid();
        const query = listQuery(rawArgs, HIERARCHY_QUERY_KEYS);
        if (typeof query.process_id === "string")
          query.process_id = query.process_id.toLowerCase();
        return {
          request: {
            method: "GET",
            path: COMPANION_ROUTES.get_work_hierarchy.path,
            ...(Object.keys(query).length > 0 ? { query } : {}),
          },
        };
      }
      case "get_project":
        onlyKeys(rawArgs, ["project_id"]);
        return {
          request: {
            method: "GET",
            path: `/companion/v1/projects/${idOf(rawArgs, "project_id")}`,
          },
        };
      case "list_tasks": {
        if (isProcessTaskList(rawArgs)) {
          // One node is enough: the Tasks of the Process come whatever the node page holds.
          return {
            request: {
              method: "GET",
              path: COMPANION_ROUTES.get_work_hierarchy.path,
              query: {
                limit: "1",
                include_tasks: "true",
                process_id: idOf(rawArgs, "process_id"),
              },
            },
          };
        }
        if (!isProjectTaskList(rawArgs)) throw new NotInAppError();
        const query = listQuery(rawArgs, ["limit", "cursor"], "project_id");
        return {
          request: {
            method: "GET",
            path: `/companion/v1/projects/${idOf(rawArgs, "project_id")}/tasks`,
            ...(Object.keys(query).length > 0 ? { query } : {}),
          },
        };
      }
      case "get_domain":
        onlyKeys(rawArgs, ["domain_id"]);
        return {
          request: {
            method: "GET",
            path: `/companion/v1/domains/${idOf(rawArgs, "domain_id")}`,
          },
        };
      case "get_process":
        onlyKeys(rawArgs, ["process_id"]);
        return {
          request: {
            method: "GET",
            path: `/companion/v1/processes/${idOf(rawArgs, "process_id")}`,
          },
        };
      case "complete_task_step":
        onlyKeys(rawArgs, ["step_id", "version", "idempotency_key"]);
        return this.completion(rawArgs, "complete", "steps");
      case "update_task_step":
        onlyKeys(rawArgs, ["step_id", "version", "idempotency_key", "changes"]);
        if (!isReopeningChange(rawArgs.changes)) throw new NotInAppError();
        return this.completion(rawArgs, "reopen", "steps");
      case "complete_task":
        onlyKeys(rawArgs, ["task_id", "version", "idempotency_key"]);
        return this.completion(rawArgs);
      case "update_task": {
        onlyKeys(rawArgs, ["task_id", "version", "idempotency_key", "changes"]);
        if (isCompletingChange(rawArgs.changes))
          return this.completion(rawArgs);
        if (isReopeningChange(rawArgs.changes))
          return this.completion(rawArgs, "reopen");
        throw new NotInAppError();
      }
      default: {
        // The Shopping and Journal rooms' closed lists; a name in neither is not in the app.
        const helpers: PlanHelpers = {
          invalid,
          onlyKeys,
          uuidOf,
          versionOf: versionValue,
          keyOf: (given, signature) => this.keyOf(given, signature),
        };
        const planned =
          planShopping(name, rawArgs, helpers) ??
          planJournal(name, rawArgs, helpers) ??
          planLicense(name, rawArgs, helpers);
        if (!planned) throw new NotInAppError();
        return planned;
      }
    }
  }

  private taskList(args: Args, tail: string, allowed: readonly string[]): Plan {
    const taskId = taskIdOf(args);
    const query = listQuery(args, [...allowed]);
    return {
      request: {
        method: "GET",
        path: `/companion/v1/tasks/${taskId}/${tail}`,
        ...(Object.keys(query).length > 0 ? { query } : {}),
      },
    };
  }

  /**
   * The complete route, or the reopen route, of a Task or of a Step: the same body, the same key, the same answer
   * (`{ task }` or `{ step }`).
   */
  private completion(
    args: Args,
    route: "complete" | "reopen" = "complete",
    collection: "tasks" | "steps" = "tasks",
  ): Plan {
    const taskId = idOf(args, collection === "steps" ? "step_id" : "task_id");
    const version = versionOf(args);
    const signature = `${collection}:${route}:${taskId}:${version}`;
    return {
      request: {
        method: "POST",
        path: `/companion/v1/${collection}/${taskId}/${route}`,
        body: { version },
        idempotencyKey: this.keyOf(args.idempotency_key, signature),
      },
      signature,
    };
  }

  /**
   * One action, one key. The room's own key wins (it already reuses it for the retry of the same action); without
   * one, the key of this task and version is kept until the write is settled, so a retry sends the same key.
   */
  private keyOf(given: unknown, signature: string): string {
    if (given !== undefined) {
      if (typeof given !== "string" || given.length < 8 || given.length > 128)
        invalid();
      return given;
    }
    const pending = keyFor(this.pending.get(signature), signature);
    this.pending.set(signature, pending);
    return pending.key;
  }
}
