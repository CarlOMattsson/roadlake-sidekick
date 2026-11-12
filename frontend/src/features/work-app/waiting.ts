/**
 * The "waiting on" view of the agenda (get_work_agenda with waiting=waiting): who a Task waits on and
 * for how long. Pure helpers and the card's words; the inline summary and the fullscreen agenda
 * both read them. The words live here, not in labels.ts, so the two label sets stay untouched.
 */
import { ownerDayNumber } from "../mcp-apps/ui/due";
import type { WorkFilters, WorkItemRecord } from "./transport";

/** A wait of this many days or more is marked as long, and its reminder button is the primary one. */
export const LONG_WAIT_DAYS = 7;
/** The hour of the next morning a reminder is set to, in the owner's local time. */
const REMIND_HOUR = 9;

/** Whether an agenda was read with the waiting filter, so the waiting view is shown. */
export function isWaitingFilter(filters: WorkFilters | undefined): boolean {
  return filters?.waiting === "waiting";
}

/** The owner calendar day of an instant as a day number, or null for text that is not a date. */
function dayNumber(value: Date): number | null {
  return Number.isNaN(value.getTime()) ? null : ownerDayNumber(value);
}

/**
 * Whole calendar days a Task has waited at `now`, counted on the owner calendar (never below 0),
 * or null when the record has no usable waiting date.
 */
export function waitedDays(
  since: string | null | undefined,
  now: Date,
): number | null {
  if (!since) return null;
  const from = dayNumber(new Date(since));
  const to = dayNumber(now);
  if (from === null || to === null) return null;
  return Math.max(0, to - from);
}

/** One row of the waiting view: the record, who it waits on and how many days. */
export type WaitingRow = {
  item: WorkItemRecord;
  /** The Contact's name; null when the record names none or the session cannot read Contacts. */
  who: string | null;
  /** Days waited; null when the record has no waiting date. */
  days: number | null;
};

/** The waiting rows, the longest wait first; records without a waiting date come last in the order read. */
export function waitingRows(
  items: readonly WorkItemRecord[],
  now: Date,
): WaitingRow[] {
  const rows = items.map((item, index) => ({
    item,
    who: item.waiting_on_contact_name?.trim() || null,
    days: waitedDays(item.waiting_since, now),
    index,
  }));
  rows.sort((a, b) => {
    if (a.days === null || b.days === null) {
      if (a.days === b.days) return a.index - b.index;
      return a.days === null ? 1 : -1;
    }
    return b.days - a.days || a.index - b.index;
  });
  return rows.map(({ item, who, days }) => ({ item, who, days }));
}

/** 09:00 tomorrow in local time, as the instant a reminder is set to. */
export function remindAt(now: Date): string {
  const at = new Date(now);
  at.setDate(at.getDate() + 1);
  at.setHours(REMIND_HOUR, 0, 0, 0);
  return at.toISOString();
}

/** The words of the waiting view, Swedish or English by the date locale of the caller. */
export type WaitingLabels = {
  /** Heading of the waiting view, with the count: "Du väntar på · 3". */
  heading: (count: number) => string;
  /** The inline card's kind label. */
  kind: string;
  /** The inline count line: "3 väntar", "5+ väntar" when more exist. */
  count: (count: number, more: boolean) => string;
  empty: string;
  /** When the record names nobody, or Contacts cannot be read. */
  someone: string;
  /** "9 dagar", "1 dag", "sedan idag". */
  days: (days: number | null) => string;
  /** The button; its visible text is short, the accessible name says which task and when. */
  remind: string;
  remindName: (title: string) => string;
  /** The line under a row once its reminder is set: "Påminnelse imorgon 09:00". */
  reminded: string;
  remindFailed: string;
};

const sv: WaitingLabels = {
  heading: (count) => `Du väntar på · ${count}`,
  kind: "Väntar på",
  count: (count, more) => `${count}${more ? "+" : ""} väntar`,
  empty: "Du väntar inte på någon.",
  someone: "Någon",
  days: (days) =>
    days === null
      ? "okänd tid"
      : days === 0
        ? "sedan idag"
        : `${days} ${days === 1 ? "dag" : "dagar"}`,
  remind: "Påminn",
  remindName: (title) => `Påminn mig imorgon om ${title}`,
  reminded: "Påminnelse imorgon 09:00",
  remindFailed: "Det gick inte att sätta påminnelsen.",
};

const en: WaitingLabels = {
  heading: (count) => `Waiting on · ${count}`,
  kind: "Waiting on",
  count: (count, more) => `${count}${more ? "+" : ""} waiting`,
  empty: "You’re not waiting on anyone.",
  someone: "Someone",
  days: (days) =>
    days === null
      ? "unknown time"
      : days === 0
        ? "since today"
        : `${days} ${days === 1 ? "day" : "days"}`,
  remind: "Remind me",
  remindName: (title) => `Remind me tomorrow about ${title}`,
  reminded: "Reminder set for tomorrow at 09:00",
  remindFailed: "Couldn’t set the reminder.",
};

/** Waiting-view words for a date locale such as "sv-SE" or "en-GB"; anything not Swedish gets English. */
export function waitingLabelsFor(dateLocale: string): WaitingLabels {
  return dateLocale.startsWith("sv") ? sv : en;
}
