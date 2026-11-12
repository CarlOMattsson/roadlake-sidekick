import type { KeyboardEvent } from "react";
import type { EmptyAsk } from "../../mcp-apps/ui/states";
import type { ShoppingItem } from "../transport";

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
