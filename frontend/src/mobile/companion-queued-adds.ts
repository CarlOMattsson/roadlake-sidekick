/**
 * Items added to a shopping list without a network wait in the phone's outbox (QueuedShoppingAdd) until it sends them.
 * Until then the server has no row for them, so the room is shown stand-in rows made here: the same shape as a real item
 * (a room cannot tell the difference), with an id that is not a UUID and that never reaches the server, and listed
 * among the writes the outbox still holds (`offline.queuedPurchases`), so the room draws them as waiting and takes no
 * tap on them. Once the outbox has sent the add, its stand-ins are gone and the real rows come with the next read.
 */
import type { ShoppingItem } from "@/features/shopping-app/transport";
import type { QueuedShoppingAdd } from "./sidekick-native";

/** The id of the stand-in row for item `index` of the add queued under `key`. */
export function queuedItemId(key: string, index: number): string {
  return `queued-${key}-${index}`;
}

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

/** The stand-in rows of one queued add, in the order the items were typed. */
export function queuedItems(add: QueuedShoppingAdd): ShoppingItem[] {
  const at = new Date(add.queuedAt).toISOString();
  return add.items.map((input, index) => {
    const quantity = input.quantity;
    return {
      id: queuedItemId(add.key, index),
      list_id: add.listId,
      name: text(input.name) ?? "",
      quantity:
        typeof quantity === "number" || typeof quantity === "string"
          ? String(quantity)
          : "1",
      unit: text(input.unit),
      note: text(input.note),
      occasion: text(input.occasion),
      offer: null,
      offer_status: "none",
      product_url: text(input.product_url),
      purchased: false,
      purchased_at: null,
      recipient_contact_id: text(input.recipient_contact_id),
      store: text(input.store),
      target_date: text(input.target_date),
      created_at: at,
      updated_at: at,
      version: 1,
    };
  });
}

/** The answer of `add_shopping_items` for an add that is queued instead: the stand-in rows, none merged. */
export function queuedAddResult(add: QueuedShoppingAdd) {
  return { items: queuedItems(add).map((item) => ({ item, merged: false })) };
}

/**
 * A `get_shopping_list` answer with the list's queued adds appended to its last page; the shop view keeps the rows of
 * its shop and those without a shop, as the server does. An answer that is not a page of this list is returned as it is.
 */
export function withQueuedAdds(
  body: Record<string, unknown>,
  listId: string,
  store: string | undefined,
  adds: readonly QueuedShoppingAdd[],
): Record<string, unknown> {
  const mine = adds.filter((add) => add.listId === listId);
  if (mine.length === 0 || !Array.isArray(body.items)) return body;
  if (body.next_offset !== null && body.next_offset !== undefined) return body;
  const rows: unknown[] = body.items;
  const wanted = store?.trim().toLowerCase();
  const extra = mine.flatMap(queuedItems).filter((item) => {
    const shop = item.store?.trim().toLowerCase();
    return !wanted || !shop || shop === wanted;
  });
  return { ...body, items: [...rows, ...extra] };
}
