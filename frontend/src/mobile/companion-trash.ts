/**
 * Deleting and the trash over the companion routes (ADR-005, amendment 2026-11-15: writing from the app). Each tool the
 * rooms ask for maps, from this CLOSED list, to one named route; the answer is the tool's own structuredContent
 * (`TrashItemRecord`, `TrashListResult`), so the rooms cannot tell the difference. No generic execute, no path from the
 * caller, no argument outside what the route takes.
 *
 *   move_to_trash       -> POST /companion/v1/{tasks|journal/entries|shopping/items}/{id}/trash    ({ version })
 *   restore_from_trash  -> POST /companion/v1/{tasks|journal/entries|shopping/items}/{id}/untrash  ({ version })
 *   list_trash          -> GET  /companion/v1/trash                                  (kind, limit, cursor)
 *
 * Only a Task, a Journal entry and a Shopping item can be moved: any other kind is answered no by `supportsCall`.
 * Permanent removal is not a tool of the server (D-031) and exists only here, for the phone's own trash view, under two
 * names that no room of Claude has:
 *
 *   erase_trashed_task  -> POST /companion/v1/tasks/{task_id}/erase  ({ version, confirm: true })
 *   empty_trash         -> POST /companion/v1/trash/empty            ({ confirm: true })
 *
 * Both are refused here, before anything is sent, unless the caller passes `confirmed: true`, which only the trash
 * view sets after the owner has said yes in a dialog. A Journal entry and a Shopping item cannot be erased at all: the
 * server refuses them and this planner has no route for them.
 */
import {
  isRecord,
  queryOf,
  withQuery,
  type Args,
  type PlanHelpers,
  type Planned,
} from "./companion-plan";

/** The kinds the app may move to the trash and back; the server answers no route for any other. */
export const TRASH_KINDS = ["task", "journal_entry", "shopping_item"] as const;
export type TrashKind = (typeof TRASH_KINDS)[number];

/** The routes, for reading and for the contract tests that compare them with the backend. Nothing is built from it. */
export const TRASH_ROUTES = {
  trash_task: { method: "POST", path: "/companion/v1/tasks/{task_id}/trash" },
  untrash_task: {
    method: "POST",
    path: "/companion/v1/tasks/{task_id}/untrash",
  },
  erase_trashed_task: {
    method: "POST",
    path: "/companion/v1/tasks/{task_id}/erase",
  },
  trash_journal_entry: {
    method: "POST",
    path: "/companion/v1/journal/entries/{entry_id}/trash",
  },
  untrash_journal_entry: {
    method: "POST",
    path: "/companion/v1/journal/entries/{entry_id}/untrash",
  },
  trash_shopping_item: {
    method: "POST",
    path: "/companion/v1/shopping/items/{item_id}/trash",
  },
  untrash_shopping_item: {
    method: "POST",
    path: "/companion/v1/shopping/items/{item_id}/untrash",
  },
  list_trash: { method: "GET", path: "/companion/v1/trash" },
  empty_trash: { method: "POST", path: "/companion/v1/trash/empty" },
} as const;

/** The tool names this planner answers. `erase_trashed_task` and `empty_trash` are the phone's own (see above). */
export const TRASH_TOOLS = [
  "list_trash",
  "move_to_trash",
  "restore_from_trash",
  "erase_trashed_task",
  "empty_trash",
] as const;

/** The collection each kind lives under, for its trash and untrash paths. */
const COLLECTION: Record<TrashKind, string> = {
  task: "tasks",
  journal_entry: "journal/entries",
  shopping_item: "shopping/items",
};

/** True for a kind the app may move to the trash. */
export function isTrashKind(value: unknown): value is TrashKind {
  return (TRASH_KINDS as readonly unknown[]).includes(value);
}

/** The planned call for a trash tool, or undefined when the name is not one of them or the kind has no route. */
export function planTrash(
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
  /** The one explicit yes a permanent removal needs; nothing is sent without it. */
  const confirmed = () => {
    if (args.confirmed !== true) h.invalid();
  };

  switch (name) {
    case "move_to_trash":
    case "restore_from_trash": {
      h.onlyKeys(args, ["kind", "record_id", "version", "idempotency_key"]);
      if (!isTrashKind(args.kind)) return undefined;
      const id = h.uuidOf(args.record_id);
      const action = name === "move_to_trash" ? "trash" : "untrash";
      return write(`/companion/v1/${COLLECTION[args.kind]}/${id}/${action}`, {
        version: h.versionOf(args.version),
      });
    }
    case "erase_trashed_task": {
      h.onlyKeys(args, ["task_id", "version", "confirmed", "idempotency_key"]);
      confirmed();
      return write(`/companion/v1/tasks/${h.uuidOf(args.task_id)}/erase`, {
        version: h.versionOf(args.version),
        confirm: true,
      });
    }
    case "empty_trash": {
      h.onlyKeys(args, ["confirmed", "idempotency_key"]);
      confirmed();
      return write("/companion/v1/trash/empty", { confirm: true });
    }
    case "list_trash": {
      const query = queryOf(args, ["kind", "limit", "cursor"], [], [], h);
      if ("kind" in query && !isTrashKind(query.kind)) return undefined;
      return {
        request: {
          method: "GET",
          path: TRASH_ROUTES.list_trash.path,
          ...withQuery(query),
        },
      };
    }
    default:
      return undefined;
  }
}

/** True when `args` names a record the trash tools answer: no kind (a question about the tool), or an allowed one. */
export function trashCallSupported(args: unknown): boolean {
  return !isRecord(args) || !("kind" in args) || isTrashKind(args.kind);
}
