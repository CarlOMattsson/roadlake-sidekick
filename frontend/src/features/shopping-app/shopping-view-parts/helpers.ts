import type { KeyboardEvent } from "react";
import type { EmptyAsk } from "../../mcp-apps/ui/states";
import type { ShoppingItem } from "../transport";
import type { ShoppingLabels } from "../labels";
import { workDate } from "../../mcp-apps/ui/due";

/** The most item names one add may carry (the tool's limit). */
export const MAX_ADD_ITEMS = 50;

/**
 * The item names typed in an add field: commas and line breaks separate them, each is trimmed and empty
 * ones are dropped. The batch field, the create field and the inline card's quick add all read their text this way.
 */
export function splitItemNames(text: string): string[] {
  return text
    .split(/[,\r\n]+/)
    .map((line) => line.trim())
    .filter(Boolean);
}

/**
 * The empty state's "tell Claude" example: shown as text, and a button that sends it when the host offers
 * messages (`sendMessage` is absent on the phone).
 */
export function emptyAsk(
  locale: string,
  example: string,
  sendMessage?: (text: string) => Promise<boolean>,
): EmptyAsk {
  return {
    locale,
    example,
    ...(sendMessage ? { onSend: () => void sendMessage(example) } : {}),
  };
}

/*
 * The tip of the store view (designsystem §3 "Listrad", one once-only tip): "Tryck på
 * ringen för att markera köpt, på varan för att ändra." stands after the last shop until a ring is first tapped or a
 * row's change form is first opened (tap, long press or Shift+F10), and is gone for good after that. The frame's storage keeps it when the host allows it; the document's `data-shopping-hold`
 * keeps it for the session when not, and hides a tip that is still drawn (shopping.css).
 */
const HOLD_KEY = "sidekick.shoppingHoldUsed";
const holdSeen = document.documentElement.dataset;
export function holdUsed() {
  holdSeen.shoppingHold = "1";
  try {
    localStorage[HOLD_KEY] = "1";
  } catch {
    // No storage in this frame: the document keeps the answer for the session.
  }
}
export function wasHoldUsed(): boolean {
  let used = holdSeen.shoppingHold;
  try {
    used ||= localStorage[HOLD_KEY];
  } catch {
    // No storage: only this session's answer counts.
  }
  return Boolean(used);
}

const STORE_COLLATOR = new Intl.Collator("sv");

const storeKey = (item: ShoppingItem) => item.store?.trim() || null;

/**
 * The order of store groups: the store with the most items on the list first (bought ones count too, so a store does
 * not move while its items are ticked off in it), then Swedish alphabetical order. The group without a store is last.
 */
export function compareStoreGroups(
  a: string | null,
  b: string | null,
  weight: (store: string) => number,
): number {
  if (a === b) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  return weight(b) - weight(a) || STORE_COLLATOR.compare(a, b);
}

/**
 * Items grouped by `store`, in the order of `compareStoreGroups`. `all` is every item of the list, bought ones
 * included, and gives each store its weight; without it the grouped items do.
 */
export function groupByStore(
  items: ShoppingItem[],
  all: ShoppingItem[] = items,
): [string | null, ShoppingItem[]][] {
  const groups = new Map<string | null, ShoppingItem[]>();
  for (const item of items) {
    const key = storeKey(item);
    groups.set(key, [...(groups.get(key) ?? []), item]);
  }
  const counts = new Map<string, number>();
  for (const item of all) {
    const key = storeKey(item);
    if (key !== null) counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  const weight = (store: string) => counts.get(store) ?? 0;
  return [...groups.entries()].sort(([a], [b]) =>
    compareStoreGroups(a, b, weight),
  );
}

/** A calendar date (YYYY-MM-DD) shown as the day it names, whatever the host time zone. */
export function formatCalendarDate(value: string, locale: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return value;
  const date = new Date(
    Number(match[1]),
    Number(match[2]) - 1,
    Number(match[3]),
  );
  return date.toLocaleDateString(locale, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

/** A calendar date without the year ("20 nov"), for the row's meta line where the year only costs width. */
function formatShortDate(value: string, locale: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return value;
  return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
    .toLocaleDateString(locale, { month: "short", day: "numeric" })
    .replace(/\.$/, "");
}

/** A price in the locale's currency format without empty decimals: "199 kr" in Swedish, "SEK 199" in English. */
function formatPrice(value: string, currency: string, locale: string): string {
  const number = Number(value);
  if (!Number.isFinite(number)) return `${value} ${currency}`;
  try {
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency,
      minimumFractionDigits: Number.isInteger(number) ? 0 : 2,
    }).format(number);
  } catch {
    return `${value} ${currency}`;
  }
}

/**
 * "bought 3 Nov": the day a bought item was ticked off, read as every date in the app is ("bought yesterday", "bought
 * Thu 5 Nov"). Nothing when the server recorded no day.
 */
export function boughtOnText(
  item: ShoppingItem,
  t: ShoppingLabels,
  now = new Date(),
): string {
  if (!item.purchased) return "";
  const day = workDate(item.purchased_at, now, t.dateLocale, { inline: true });
  return day ? t.boughtOn(day) : "";
}

/**
 * The closed offer fold's line, "Offer: SEK 199 until 30 Nov": the saved offer's price and the day it ends. The plain
 * word "Offer" when the item has none.
 */
export function offerSummary(item: ShoppingItem, t: ShoppingLabels): string {
  const { offer } = item;
  if (!offer) return t.offer;
  return t.offerSummary(
    formatPrice(offer.price, offer.currency, t.dateLocale),
    offer.valid_until ? formatShortDate(offer.valid_until, t.dateLocale) : "",
  );
}

/**
 * What a store-view row says besides its name and amount, as one muted line: the offer ("199 kr (ord. 289 kr)", marked when it is
 * not current), the date it is wanted by, the occasion and the note. Empty when the item has none of them.
 */
export function itemMeta(item: ShoppingItem, t: ShoppingLabels): string {
  const { offer } = item;
  const price = (value: string, currency: string) =>
    formatPrice(value, currency, t.dateLocale);
  const offerText = offer
    ? [
        price(offer.price, offer.currency) +
          (offer.regular_price
            ? ` (${t.regularShort(price(offer.regular_price, offer.currency))})`
            : ""),
        item.offer_status === "current"
          ? ""
          : t[item.offer_status].toLocaleLowerCase(t.dateLocale),
      ]
        .filter(Boolean)
        .join(" · ")
    : "";
  return [
    offerText,
    item.target_date &&
      t.untilDate(formatShortDate(item.target_date, t.dateLocale)),
    item.occasion,
    item.note,
  ]
    .filter(Boolean)
    .join(" · ");
}

/**
 * Lines shown in the compact inline view (a host that offers no fullscreen): each shown store heading
 * and each shown row counts as one line. The rest is "Show all (N)", which expands the whole view in
 * place. A 560 px card at 320 px width must hold the worst case (one store heading and rows with long
 * names); five lines leave room for a wrapped name. Check with the one-screen shopping fixtures.
 */
export const COMPACT_ROWS = 5;

/**
 * The open groups for the compact view, in store order, within a budget of `limit` lines. A shown group
 * costs one line for its heading plus one per shown row, so a group is shown only when its heading and at
 * least one row fit. A group past the budget shows no rows; a group that is shown keeps its full count in
 * its heading.
 */
export function compactGroups<T>(
  groups: [string | null, T[]][],
  limit: number,
): { store: string | null; rows: T[]; shown: T[] }[] {
  let budget = limit;
  return groups.map(([store, rows]) => {
    const shown = budget >= 2 ? rows.slice(0, budget - 1) : [];
    budget -= shown.length > 0 ? shown.length + 1 : 0;
    return { store, rows, shown };
  });
}

/** Enter is handled by the view, not by the browser: the sandboxed App cannot submit forms. */
export function isEnter(event: KeyboardEvent<HTMLElement>): boolean {
  return event.key === "Enter" && !event.nativeEvent.isComposing;
}

// The conflict notice scrolls into sight once, when it appears (the list may be scrolled down). A stable ref
// callback, so a later render does not scroll again.
export const intoView = (el: HTMLElement | null) =>
  el?.scrollIntoView?.({ block: "nearest" });
