/**
 * The "waiting on" view of the agenda (get_work_agenda with waiting=waiting): who a Task waits on and
 * for how long. Pure helpers and the card's words; the inline summary and the fullscreen agenda
 * both read them. The words live here, not in labels.ts, so the two label sets stay untouched.
 */
import {
  ownerDayNumber,
  ownerDayPlus,
  ownerDueAt,
  parseDueDay,
  workDate,
} from "../../mcp-apps/ui/due";
import type { WorkFilters, WorkItemRecord } from "../transport/transport";

/** A wait of this many days or more is marked as long, and its reminder button is the primary one. */
export const LONG_WAIT_DAYS = 7;
/** The hour of the next morning a reminder is set to, in the owner's local time. */
const REMIND_HOUR = 9;

/** Whether an agenda was read with the waiting filter, so the waiting view is shown. */
export function isWaitingFilter(filters: WorkFilters | undefined): boolean {
  return filters?.waiting === "waiting";
}

/** The filters with the waiting view turned on or off; every other filter (the chosen tags) stays. */
export function withWaitingView(
  filters: WorkFilters | undefined,
  on: boolean,
): WorkFilters {
  const next: WorkFilters = { ...filters };
  delete next.waiting;
  return on ? { ...next, waiting: "waiting" } : next;
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
  /** Heading of the waiting view, with the count. */
  heading: (count: number) => string;
  /** The inline card's kind label. */
  kind: string;
  /** The inline count line: the count and the waiting word, with a + when more exist. */
  count: (count: number, more: boolean) => string;
  empty: string;
  /** When the record names nobody, or Contacts cannot be read. */
  someone: string;
  /** How long it has waited: in days, or since today. */
  days: (days: number | null) => string;
  /** The button; its visible text is short, the accessible name says which task and when. */
  remind: string;
  remindName: (title: string) => string;
  /** The line under a row once its reminder is set: `reminded` with the day and time. */
  reminded: string;
  remindFailed: string;
  /** "Väntar på Anders sedan 13 nov": who and since when, each part left out when unknown. `since` is a short date. */
  line: (who: string | null, since: string | null) => string;
  /** "följ upp 17 nov"; `day` is a short date or the word for today or yesterday. */
  followUp: (day: string) => string;
  /** "förfaller imorgon": the due day on a waiting line whose row the follow-up places; `day` as for `followUp`. */
  dueOn: (day: string) => string;
  /** The agenda's switch to the waiting view, and the way back to the dated agenda. */
  showWaiting: string;
  showAgenda: string;
  /** The Task's waiting section, a row of the property list: its value when nobody is waited on, since when, changing who, ending the wait and the follow-up day. */
  none: string;
  /** "sedan 13 nov"; `day` is a short date or the word for today or yesterday. */
  since: (day: string) => string;
  changeWho: string;
  stop: string;
  pickWho: string;
  followUpDay: string;
  clearFollowUp: string;
  inThreeDays: string;
  tomorrow: string;
  nextWeek: string;
  /** The editor's fields. */
  editWho: string;
  editWhoNone: string;
  editSince: string;
  editFollowUp: string;
  clearSince: string;
  clearWho: string;
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
  line: (who, since) =>
    `Väntar på ${who ?? "någon"}${since ? ` sedan ${since}` : ""}`,
  followUp: (day) => `följ upp ${day}`,
  dueOn: (day) => `förfaller ${day}`,
  showWaiting: "Väntar på",
  showAgenda: "Visa hela agendan",
  none: "Ingen",
  since: (day) => `sedan ${day}`,
  changeWho: "Byt person",
  stop: "Jag väntar inte längre",
  pickWho: "Väntar på vem?",
  followUpDay: "Uppföljningsdag",
  clearFollowUp: "Ta bort uppföljning",
  inThreeDays: "Om 3 dagar",
  tomorrow: "Imorgon",
  nextWeek: "Nästa vecka",
  editWho: "Väntar på (kontakt)",
  editWhoNone: "Ingen vald",
  editSince: "Väntar sedan",
  editFollowUp: "Följ upp",
  clearSince: "Väntar inte längre",
  clearWho: "Ta bort kontakt",
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
  line: (who, since) =>
    `Waiting on ${who ?? "someone"}${since ? ` since ${since}` : ""}`,
  followUp: (day) => `follow up ${day}`,
  dueOn: (day) => `due ${day}`,
  showWaiting: "Waiting on",
  showAgenda: "Show the whole agenda",
  none: "No one",
  since: (day) => `since ${day}`,
  changeWho: "Change person",
  stop: "I’m no longer waiting",
  pickWho: "Waiting on whom?",
  followUpDay: "Follow-up day",
  clearFollowUp: "Remove follow-up",
  inThreeDays: "In 3 days",
  tomorrow: "Tomorrow",
  nextWeek: "Next week",
  editWho: "Waiting on (contact)",
  editWhoNone: "None chosen",
  editSince: "Waiting since",
  editFollowUp: "Follow up",
  clearSince: "No longer waiting",
  clearWho: "Remove contact",
};

/** Waiting-view words for a date locale such as "sv-SE" or "en-GB"; anything not Swedish gets English. */
export function waitingLabelsFor(dateLocale: string): WaitingLabels {
  return dateLocale.startsWith("sv") ? sv : en;
}

/** The Task fields a waiting line reads; a list record and a Task read from get_task both carry them. */
export type WaitingFields = {
  waiting_since?: string | null;
  follow_up_at?: string | null;
  due_at?: string | null;
};

/** A day as words, lower case: "idag" or "igår" next to today, else a short date ("13 nov"). */
export function shortDay(value: string, now: Date, dateLocale: string): string {
  return workDate(value, now, dateLocale, { inline: true, weekday: false });
}

/** What a waiting Task says about its wait: the line, and the follow-up with whether its day has come. */
export type WaitingSummary = {
  /** "Väntar på Anders sedan 13 nov". */
  line: string;
  /** "följ upp 17 nov"; null when no follow-up day is set. */
  followUp: string | null;
  /** "förfaller imorgon"; null when the Task has no due date. */
  due: string | null;
  /** The follow-up day is today or has passed. */
  reached: boolean;
  /** The agenda date of the Task comes from its follow-up: it has no due date, or a later one. */
  followUpFirst: boolean;
};

/**
 * The waiting line of a Task in words, Swedish or English by `dateLocale`. `who` is the Contact's name, or null when
 * the Task names nobody (or Contacts cannot be read). Null when the Task is not waiting.
 */
export function waitingSummary(
  fields: WaitingFields,
  who: string | null,
  now: Date,
  dateLocale: string,
): WaitingSummary | null {
  if (!fields.waiting_since) return null;
  const wt = waitingLabelsFor(dateLocale);
  const followDay = parseDueDay(fields.follow_up_at);
  const dueDay = parseDueDay(fields.due_at);
  const since = shortDay(fields.waiting_since, now, dateLocale);
  return {
    line: wt.line(who, since || null),
    followUp:
      fields.follow_up_at && followDay !== null
        ? wt.followUp(shortDay(fields.follow_up_at, now, dateLocale))
        : null,
    due:
      fields.due_at && dueDay !== null
        ? wt.dueOn(shortDay(fields.due_at, now, dateLocale))
        : null,
    reached: followDay !== null && followDay <= ownerDayNumber(now),
    followUpFirst:
      followDay !== null && (dueDay === null || followDay < dueDay),
  };
}

/** The text with a capital first letter, for a part that starts a line. */
export function capital(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** The waiting summary of an open waiting Task as a list or agenda row shows it; null for anything else. */
export function itemWaitingSummary(
  item: WorkItemRecord,
  now: Date,
  dateLocale: string,
): WaitingSummary | null {
  if (
    item.kind !== "task" ||
    !item.waiting ||
    item.status === "completed" ||
    item.status === "cancelled"
  )
    return null;
  return waitingSummary(
    item,
    item.waiting_on_contact_name?.trim() || null,
    now,
    dateLocale,
  );
}

/**
 * Whether the follow-up leads the row of an agenda group: the server groups a waiting Task by the earlier of its due
 * date and its follow-up (`group` is given only where that grouping stands), so when the follow-up is the earlier one the
 * row leads with it ("Följ upp igår") and the due date moves to the waiting line. One rule for both lines.
 */
export function followUpLeads(
  summary: WaitingSummary | null,
  group: string | null | undefined,
): boolean {
  return !!group && !!summary?.followUp && summary.followUpFirst;
}

/** The time slot of a row the follow-up leads (see `followUpLeads`): the follow-up in words, in the overdue tone once reached. */
export function followUpLead(
  item: WorkItemRecord,
  now: Date,
  dateLocale: string,
  group: string | null | undefined,
): { text: string; tone: "overdue" | "none"; at: string } | null {
  const summary = itemWaitingSummary(item, now, dateLocale);
  if (
    !summary?.followUp ||
    !item.follow_up_at ||
    !followUpLeads(summary, group)
  )
    return null;
  return {
    text: capital(summary.followUp),
    tone: summary.reached ? "overdue" : "none",
    at: item.follow_up_at,
  };
}

/** The time of day a follow-up day is set to, in the owner's zone: the morning, when the agenda is read. */
const FOLLOW_UP_TIME = "09:00";

/** The instant a follow-up on `day` (`YYYY-MM-DD`) is stored as. */
export function followUpAtOf(day: string): string {
  return ownerDueAt(day, FOLLOW_UP_TIME);
}

/** The instant a wait that began on `day` is stored as: now when it began today, else that morning. */
export function waitingSinceOf(day: string, now: Date): string {
  return day === ownerDayPlus(now, 0)
    ? now.toISOString()
    : ownerDueAt(day, FOLLOW_UP_TIME);
}
