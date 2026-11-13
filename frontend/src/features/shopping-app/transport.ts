/** Shared command contract for the browser and the MCP host bridge. */
import type { Item, WithOptional } from "../../lib/mcp/derived";
import type { OfflineSupport } from "../mcp-apps/room-types";
import { isConflict as isConflictCode } from "../../lib/mcp/errors";
import type {
  ToolInputs,
  ToolResults,
} from "../../lib/mcp/tool-results.generated";

type ItemRecord = Item<ToolResults["get_shopping_list"]["items"]>;
/**
 * One item row as the shopping tools return it. The profile fields are optional because an older
 * server leaves them out; the offer's decimals arrive as strings.
 */
export type ShoppingItem = WithOptional<
  ItemRecord,
  | "unit"
  | "note"
  | "store"
  | "product_url"
  | "recipient_contact_id"
  | "recipient_contact_name"
  | "occasion"
  | "target_date"
  | "offer"
>;
/** A recorded offer as the tools return it. */
export type ShoppingOffer = NonNullable<ItemRecord["offer"]>;
/**
 * A list. The page of lists (`list_shopping_lists`) also counts its open items; a created, renamed or read list
 * does not, so the count is optional here.
 */
export type ShoppingList =
  ToolResults["create_shopping_list"]["shopping_list"] & {
    open_count?: number;
  };
type ListRead = ToolResults["get_shopping_list"];
/** One list with a page of its items; `store` is only sent for the shop view. */
export type ShoppingDetail = Omit<ListRead, "items" | "store"> & {
  items: ShoppingItem[];
  store?: ListRead["store"];
};
/** A page of lists. */
export type ShoppingLists = ToolResults["list_shopping_lists"];
/** The writable fields of one item (`update_shopping_item`); a new item needs a name and a quantity. */
export type ShoppingInput = ToolInputs["update_shopping_item"]["item"] &
  Required<
    Pick<ToolInputs["update_shopping_item"]["item"], "name" | "quantity">
  >;
/** An offer as the editor sends it: a price may be a number or a string. */
export type ShoppingOfferInput = NonNullable<ShoppingInput["offer"]>;
export type AddOptions = { store?: string; mergeDuplicates?: boolean };
export type ShoppingTransport = {
  /** Absent when the host cannot search Contacts (the mobile app): the editor then offers no recipient search. */
  contacts?: (
    q: string,
  ) => Promise<{ contacts: { id: string; display_name: string }[] }>;
  lists: (offset: number) => Promise<ShoppingLists>;
  /** `store` keeps that shop's items plus the items with no shop (the shop view). */
  get: (id: string, offset: number, store?: string) => Promise<ShoppingDetail>;
  create: (
    name: string,
    key: string,
  ) => Promise<{ shopping_list: ShoppingList }>;
  rename: (
    list: ShoppingList,
    name: string,
    archived: boolean,
    key: string,
  ) => Promise<unknown>;
  /**
   * Adds one item per name. `store` puts the new items in that shop (the store view); `mergeDuplicates`
   * adds the quantity to an open item with the same name and unit instead of a new row. The MCP tool
   * takes merge_duplicates.
   */
  add: (
    id: string,
    names: string[],
    key: string,
    options?: AddOptions,
  ) => Promise<unknown>;
  update: (
    item: ShoppingItem,
    input: ShoppingInput,
    key: string,
  ) => Promise<unknown>;
  /** Sets the item bought or open (the opposite of its `purchased`); resolves the item as stored, with its new version. */
  purchase: (
    item: ShoppingItem,
    key: string,
  ) => Promise<{ item: ShoppingItem }>;
  /** The host's offline help (the mobile app): the offline copy's time and the queued purchases. Absent in Claude. */
  offline?: OfflineSupport;
};

/**
 * A purchase that got no answer and now waits in the phone's outbox (the mobile transport's CompanionQueuedError).
 * Matched by name, so the room needs nothing from the mobile code. `purchased` is the state that will be sent.
 */
export function queuedPurchase(error: unknown): { purchased: boolean } | null {
  if (!(error instanceof Error) || error.name !== "CompanionQueuedError")
    return null;
  const purchased = (error as Error & { purchased?: unknown }).purchased;
  return typeof purchased === "boolean" ? { purchased } : null;
}
/**
 * Whether a write was refused because the stored version moved on (another device changed the row).
 * The MCP host reports the closed code "conflict"; an HTTP 409 counts the same.
 */
export function isConflict(error: unknown): boolean {
  const failure = error as { status?: unknown } | null | undefined;
  return isConflictCode(error) || failure?.status === 409;
}

export function localDay(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

/** Sandboxed opaque frames may expose getRandomValues without randomUUID. */
export function writeKey(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6]! & 15) | 64;
  bytes[8] = (bytes[8]! & 63) | 128;
  const hex = Array.from(bytes, (value) =>
    value.toString(16).padStart(2, "0"),
  ).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
