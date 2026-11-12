/**
 * The Shopping room's calls over the companion routes (ADR-005). Each tool the room asks for maps,
 * from this CLOSED list, to one named route; the answer is the tool's own structuredContent, so the room cannot tell
 * the difference. No generic execute, no path from the caller, no argument outside what the route takes.
 *
 *   list_shopping_lists         -> GET  /companion/v1/shopping/lists                    (include_archived, limit, offset)
 *   get_shopping_list           -> GET  /companion/v1/shopping/lists/{list_id}          (on_date, limit, offset, store)
 *   create_shopping_list        -> POST /companion/v1/shopping/lists                    ({ name })
 *   update_shopping_list        -> POST /companion/v1/shopping/lists/{list_id}/update   ({ name, archived, version })
 *   add_shopping_items          -> POST /companion/v1/shopping/lists/{list_id}/items    ({ items, merge_duplicates })
 *   update_shopping_item        -> POST /companion/v1/shopping/items/{item_id}/update   ({ item, version })
 *   set_shopping_item_purchased -> POST /companion/v1/shopping/items/{item_id}/purchased ({ purchased, version })
 *
 * A purchase and an add that get no answer are kept in the phone's outbox (companion-transport.ts). Every write sends
 * its key in the Idempotency-Key header. Not in the app: list_contacts (the recipient search) and
 * set_shopping_items_purchased; the room hides what needs them (`toolOffered`).
 */
import {
  isRecord,
  queryOf,
  withQuery,
  type Args,
  type PlanHelpers,
  type Planned,
} from "./companion-plan";

/** The routes, for reading and for the contract tests that compare them with the backend. Nothing is built from it. */
export const SHOPPING_ROUTES = {
  list_shopping_lists: {
    method: "GET",
    path: "/companion/v1/shopping/lists",
  },
  get_shopping_list: {
    method: "GET",
    path: "/companion/v1/shopping/lists/{list_id}",
  },
  create_shopping_list: {
    method: "POST",
    path: "/companion/v1/shopping/lists",
  },
  update_shopping_list: {
    method: "POST",
    path: "/companion/v1/shopping/lists/{list_id}/update",
  },
  add_shopping_items: {
    method: "POST",
    path: "/companion/v1/shopping/lists/{list_id}/items",
  },
  update_shopping_item: {
    method: "POST",
    path: "/companion/v1/shopping/items/{item_id}/update",
  },
  set_shopping_item_purchased: {
    method: "POST",
    path: "/companion/v1/shopping/items/{item_id}/purchased",
  },
} as const;

/** The tool names this planner answers. */
export const SHOPPING_TOOLS = [
  "list_shopping_lists",
  "get_shopping_list",
  "create_shopping_list",
  "update_shopping_list",
  "add_shopping_items",
  "update_shopping_item",
  "set_shopping_item_purchased",
] as const;

const BASE = "/companion/v1/shopping";

/** The planned call for a shopping tool, or undefined when the name is not one of them. */
export function planShopping(
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
  const flag = (value: unknown): boolean =>
    typeof value === "boolean" ? value : h.invalid();

  switch (name) {
    case "list_shopping_lists":
      return {
        request: {
          method: "GET",
          path: `${BASE}/lists`,
          ...withQuery(
            queryOf(args, ["include_archived", "limit", "offset"], [], [], h),
          ),
        },
      };
    case "get_shopping_list": {
      const id = h.uuidOf(args.list_id);
      return {
        request: {
          method: "GET",
          path: `${BASE}/lists/${id}`,
          ...withQuery(
            queryOf(
              args,
              ["on_date", "limit", "offset", "store"],
              ["list_id"],
              ["on_date"],
              h,
            ),
          ),
        },
      };
    }
    case "create_shopping_list":
      h.onlyKeys(args, ["name", "idempotency_key"]);
      return write(`${BASE}/lists`, { name: text(args.name) });
    case "update_shopping_list": {
      h.onlyKeys(args, [
        "list_id",
        "name",
        "archived",
        "version",
        "idempotency_key",
      ]);
      const id = h.uuidOf(args.list_id);
      return write(`${BASE}/lists/${id}/update`, {
        name: text(args.name),
        archived: flag(args.archived),
        version: h.versionOf(args.version),
      });
    }
    case "add_shopping_items": {
      h.onlyKeys(args, [
        "list_id",
        "items",
        "merge_duplicates",
        "idempotency_key",
      ]);
      const id = h.uuidOf(args.list_id);
      const items = args.items;
      if (!Array.isArray(items) || items.length === 0 || !items.every(isRecord))
        return h.invalid();
      const merge = args.merge_duplicates;
      const body = {
        items,
        ...(merge === undefined || merge === null
          ? {}
          : { merge_duplicates: flag(merge) }),
      };
      // Items added without an answer (a shop without coverage) wait in the phone's outbox with the same key.
      return {
        ...write(`${BASE}/lists/${id}/items`, body),
        queue: { kind: "add", listId: id, body },
      };
    }
    case "update_shopping_item": {
      h.onlyKeys(args, ["item_id", "item", "version", "idempotency_key"]);
      const id = h.uuidOf(args.item_id);
      if (!isRecord(args.item)) return h.invalid();
      return write(`${BASE}/items/${id}/update`, {
        item: args.item,
        version: h.versionOf(args.version),
      });
    }
    case "set_shopping_item_purchased": {
      h.onlyKeys(args, ["item_id", "purchased", "version", "idempotency_key"]);
      const id = h.uuidOf(args.item_id);
      const purchased = flag(args.purchased);
      const version = h.versionOf(args.version);
      // A purchase without an answer (a shop without coverage) waits in the phone's outbox instead of failing.
      return {
        ...write(`${BASE}/items/${id}/purchased`, { purchased, version }),
        queue: { kind: "purchase", itemId: id, version, purchased },
      };
    }
    default:
      return undefined;
  }
}
