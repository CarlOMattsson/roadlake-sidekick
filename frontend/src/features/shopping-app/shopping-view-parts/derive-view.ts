import type { ShoppingDetail, ShoppingItem } from "../transport";
import type { ShoppingLabels } from "../labels";
import { COMPACT_ROWS, compactGroups, groupByStore } from "./helpers";

type Params = {
  labels: ShoppingLabels;
  detail?: ShoppingDetail;
  id: string;
  wanted: Record<string, boolean>;
  /** Purchases waiting in the phone's outbox: drawn in the state that will be sent. */
  waiting?: Record<string, boolean>;
  held: Record<string, ShoppingItem>;
  fullscreen: boolean;
  compact: boolean;
  store?: string;
  editOpen: boolean;
  expanded: boolean;
};

/** When an item was bought, in ms; an item with no recorded time counts as the oldest. */
const boughtAt = (item: ShoppingItem) =>
  item.purchased_at ? Date.parse(item.purchased_at) || 0 : 0;

/** What the view draws, derived from the list read, the asked purchases and the open panels. */
export function deriveView({
  labels: t,
  detail,
  id,
  wanted,
  waiting = {},
  held,
  fullscreen,
  compact,
  store,
  editOpen,
  expanded,
}: Params) {
  const list = detail?.shopping_list;
  // The items as they are drawn: a purchase asked for shows at once, before the server has answered, and one waiting
  // in the outbox shows the state it will send.
  const items =
    detail?.items.map((item) =>
      item.id in wanted
        ? { ...item, purchased: wanted[item.id]! }
        : item.id in waiting
          ? { ...item, purchased: waiting[item.id]! }
          : item,
    ) ?? [];
  const open = items.filter((item) => !item.purchased);
  const purchased = items.filter((item) => item.purchased);
  // The rows of the open groups: the open items, and the bought ones whose Undo still holds ("Köpt"), in the list's order.
  const rows = items.filter(
    (item) => !item.purchased || held[item.id]?.purchased,
  );
  // "Köpta (n)": the bought items that are settled, the newest first. A bought item still held with its Undo stands in
  // the open rows and joins the fold only when the time to undo is up, so the count never moves while Undo is offered.
  // The progress ("2 av 7 köpta") counts every bought item, held ones too.
  const settled = purchased
    .filter((item) => !held[item.id]?.purchased)
    .sort((a, b) => boughtAt(b) - boughtAt(a));
  // The store view is shown in fullscreen until "Edit list" opens the forms; it needs a list to show.
  const storeMode =
    (fullscreen || Boolean(store)) && Boolean(list) && !editOpen;
  // "+ Add item" opens the store view, before the first shop (designsystem §3 Skapa), also in an empty list.
  const canAdd = storeMode && !list?.archived;
  // The folded compact view: the first open rows, the list forms and the hint left out until "Show all".
  // Without a list read yet there is nothing to fold, so the full view (with the create-list form) shows.
  const folded =
    compact && !expanded && !fullscreen && !store && Boolean(detail);
  // A chosen list whose read has not answered yet: the loading line only, no forms and no hint.
  const reading = Boolean(id) && !list;
  // The shop view names its shop: "ICA · 8 kvar". The filter ignores case, so the spelling the items
  // already use wins over the spelling that was asked for.
  const shopName = storeMode ? store?.trim() || undefined : undefined;
  const shopLabel = shopName
    ? (detail?.items
        .find(
          (item) => item.store?.trim().toLowerCase() === shopName.toLowerCase(),
        )
        ?.store?.trim() ?? shopName)
    : undefined;
  // The header row's title: the shop with its open count, or else the list name.
  const headerTitle = shopLabel
    ? t.storeRemaining(shopLabel, open.length)
    : list?.name;
  // The open groups, with the held rows in their places. Folded, the rows shown are the first COMPACT_ROWS of
  // the open list; the bought row may be out of sight, so its Undo line goes after the shown rows instead of among them.
  const groups = groupByStore(rows, items);
  const shownGroups = compactGroups(groups, folded ? COMPACT_ROWS : Infinity);
  const shownCount = shownGroups.reduce(
    (sum, group) => sum + group.shown.length,
    0,
  );
  return {
    list,
    items,
    purchased,
    settled,
    rows,
    storeMode,
    canAdd,
    folded,
    reading,
    shopLabel,
    headerTitle,
    shownGroups,
    shownCount,
  };
}
