import { ownerDateFormat } from "../mcp-apps/app-timezone";
import { workDate } from "../mcp-apps/ui/due";
import { AppFrame } from "../mcp-apps/ui/layout";
import { CardFoot } from "../mcp-apps/ui/card";
import type { ShoppingLabels } from "./labels";
import { OpenListButton, quantityText } from "./shopping-card";
import type { ShoppingItem } from "./transport";

/**
 * An add_shopping_items result (items) or an update_shopping_item result (one item).
 * list is the list's name when the result carries a non-empty list_name; listId is the list the
 * items belong to, so Open can show that list.
 */
export type BatchSummary = {
  kind: "added" | "updated";
  /** When the list was last written: the newest updated_at of the result's items. */
  at?: string;
  items: ShoppingItem[];
  /** Aligned with items: true when the input was folded into an existing item (merge_duplicates). */
  merged: boolean[];
  list?: string;
  listId?: string;
  /** The list's open items after the write, when the result carries open_count: the `updatedKicker` line. */
  open?: number;
};

/**
 * Rows in a batch card (designsystem §3: at most three rows in an inline card's body). A longer batch shows three names
 * and counts the rest in the Open button's foot ("· N more"); a card with no Open button shows two names and "+N more"
 * as the third row. Either way the card stays at most 240 px high.
 */
const BATCH_ITEM_COUNT = 3;

/** The list_name of a batch or item result, when it is a non-empty string. */
function listNameOf(data: object): string | undefined {
  const name = (data as { list_name?: unknown }).list_name;
  return typeof name === "string" && name.trim() !== "" ? name : undefined;
}

/** The result's open_count, when it is a whole number of zero or more. */
function openCountOf(data: object): number | undefined {
  const count = (data as { open_count?: unknown }).open_count;
  return Number.isInteger(count) && (count as number) >= 0
    ? (count as number)
    : undefined;
}

/** The list_id of a batch's items. Every item of one batch belongs to the same list. */
function listIdOf(items: ShoppingItem[]): string | undefined {
  const id = items[0]?.list_id;
  return typeof id === "string" && id !== "" ? id : undefined;
}

/**
 * Whether the item has an amount to show. The backend stores 1 when no quantity was given, so 1
 * (as "1" or "1.000") is left out and the line names the item only.
 */
function hasAmount(item: ShoppingItem): boolean {
  const value = Number(item.quantity);
  return Number.isFinite(value) && value > 0 && value !== 1;
}

/** "Potatis, 2 kg" when the item has an amount, otherwise the name alone. The batch card uses commas only. */
function batchLine(item: ShoppingItem, locale: string): string {
  return hasAmount(item)
    ? `${item.name}, ${quantityText(item, locale)}`
    : item.name;
}

/** The newest updated_at among the items, the moment the batch was written. */
function writtenAt(items: ShoppingItem[]): string | undefined {
  return items
    .map((item) => (item as { updated_at?: unknown }).updated_at)
    .filter(
      (at): at is string =>
        typeof at === "string" && !Number.isNaN(Date.parse(at)),
    )
    .sort()
    .at(-1);
}

/** "10:22" in the owner's time zone, the clock the list is kept in. */
function clock(at: string, locale: string): string {
  return ownerDateFormat(locale, {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(at));
}

/**
 * When the list was written, with its day: the `today` or `yesterday` word and the time, else the short date and the time (the
 * day as every date in the app reads it), so a card read later does not pass yesterday's time off as today's.
 */
function updatedWhen(at: string, t: ShoppingLabels): string {
  const day = workDate(at, new Date(), t.dateLocale, { inline: true });
  const time = clock(at, t.dateLocale);
  return day ? t.dayAt(day, time) : time;
}

/** Recognises a batch result. A list detail has shopping_list and is never a batch. */
export function batchSummary(data: unknown): BatchSummary | undefined {
  if (typeof data !== "object" || data === null || "shopping_list" in data) {
    return undefined;
  }
  const result = data as {
    items?: { item: ShoppingItem; merged?: boolean }[];
    item?: ShoppingItem;
  };
  const list = listNameOf(data);
  const open = openCountOf(data);
  if (Array.isArray(result.items)) {
    const items = result.items.map((added) => added.item);
    const merged = result.items.map((added) => added.merged === true);
    return items.length > 0
      ? {
          kind: "added",
          items,
          merged,
          list,
          listId: listIdOf(items),
          at: writtenAt(items),
          open,
        }
      : undefined;
  }
  return result.item
    ? {
        kind: "updated",
        items: [result.item],
        merged: [false],
        list,
        listId: listIdOf([result.item]),
        at: writtenAt([result.item]),
        open,
      }
    : undefined;
}

/**
 * Small inline card after an add or update: the kicker "Shopping · updated", the list's name as the title, one row per item ("Added: Milk" for
 * an added item, "Updated: Milk, now 2 l" for an updated or merged one ("Already there: Milk" without an amount); eight at most, then "+N more"), and
 * "Open list" only when the host offers fullscreen. The full list is not shown here.
 */
export function BatchCard({
  summary,
  labels: t,
  onOpen,
}: {
  summary: BatchSummary;
  labels: ShoppingLabels;
  onOpen?: () => void;
}) {
  const count = summary.items.length;
  // With an Open button the names left out are counted in its foot ("Open list · 4 more"); without one the
  // last row says "+4 more" instead.
  const shown = summary.items.slice(
    0,
    onOpen || count <= BATCH_ITEM_COUNT
      ? BATCH_ITEM_COUNT
      : BATCH_ITEM_COUNT - 1,
  );
  const more = count - shown.length;
  return (
    <section className="sidekick-shopping shopping-card" aria-label={t.title}>
      <AppFrame mode="inline">
        <div className="shopping-card-body shopping-batch-body sk-card">
          <p className="sk-eyebrow">
            {t.updatedKicker(
              summary.at ? updatedWhen(summary.at, t) : undefined,
              summary.open,
            )}
          </p>
          <h2 className="shopping-card-title sk-card__title">
            {summary.list ?? t.listFallback}
          </h2>
          <ul className="shopping-batch-names">
            {shown.map((item, index) => {
              const merged = summary.merged[index] === true;
              const updated = summary.kind === "updated";
              // One pattern, outcome prefix then item and detail: `newItemPrefix` (or `updatedPrefix`) with the item and its amount. A
              // merged item (the result's `merged`, a flag without the amount before) is `updatedPrefix` with its amount, or
              // `existedPrefix` and the item without one: whether the amount grew cannot be told from the result.
              const amount = hasAmount(item)
                ? quantityText(item, t.dateLocale)
                : undefined;
              return (
                <li
                  key={`${index}:${item.id}`}
                  className="shopping-receipt-line"
                >
                  {updated || merged ? (
                    <>
                      <span className="shopping-receipt-label">
                        {merged && !amount ? t.existedPrefix : t.updatedPrefix}
                      </span>{" "}
                      {amount
                        ? `${item.name}, ${t.nowAmount(amount)}`
                        : item.name}
                    </>
                  ) : (
                    <>
                      <span className="shopping-receipt-label">
                        {t.newItemPrefix}
                      </span>{" "}
                      {batchLine(item, t.dateLocale)}
                    </>
                  )}
                </li>
              );
            })}
            {more > 0 && !onOpen ? <li>{t.moreItems(more)}</li> : null}
          </ul>
          {onOpen ? (
            <CardFoot>
              <OpenListButton
                labels={t}
                hidden={more}
                hiddenText={t.hiddenAdded}
                onOpen={onOpen}
              />
            </CardFoot>
          ) : null}
        </div>
      </AppFrame>
    </section>
  );
}
