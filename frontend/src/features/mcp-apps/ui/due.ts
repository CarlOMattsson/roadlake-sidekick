/**
 * Dates for the Work app and the MCP app UI (Glance and View): one formatter, `workDate`, and the
 * overdue chip `relativeDue` built on it.
 *
 * Pure: no React and no clock reads. The caller passes `now`. The calendar day is taken in the
 * owner's time zone (`appTimeZone`, Europe/Stockholm unless the backend declares another), so the
 * result does not depend on the host time zone. `value` is either a plain `YYYY-MM-DD` date, which
 * is never shifted by a zone, or an ISO datetime with `Z` or an offset, which is converted to its
 * owner calendar day first.
 */

import { ownerDateFormat } from "../app-timezone";

export type DueLocale = "sv" | "en";

export type DueTone = "overdue" | "today" | "soon" | "later" | "none";

export interface RelativeDue {
  text: string;
  tone: DueTone;
}

/** How a date label is written: in a sentence, or on its own. */
export interface WorkDateOptions {
  /**
   * Inline: the label is a sentence part after a colon or "till", so it starts in lower case ("imorgon",
   * "tis 4 nov"). Without it the first letter is a capital ("Imorgon", "Tis 4 nov").
   */
  inline?: boolean;
  /** `false`: no "idag", "igår" or "imorgon", only the weekday and the date. */
  relative?: boolean;
  /** `false`: never a weekday, only the date ("5 nov"). "idag", "igår" and "imorgon" still read as words. */
  weekday?: boolean;
}

/** Days ahead (2..SOON_DAYS) that still count as "soon"; 1 day is "Imorgon". */
const SOON_DAYS = 6;
/** Within this many days of today a date shows its weekday ("tors 5 nov"); further out only the date. */
const WEEKDAY_DAYS = 7;
const DAY_MS = 86_400_000;
const DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;
/** ISO datetime that must carry `Z` or a `±HH:MM` offset; no offset is rejected. */
const TIMESTAMP_PATTERN =
  /^(\d{4})-(\d{2})-(\d{2})T(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d(?:\.\d+)?)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/;

const WEEKDAYS: Record<DueLocale, readonly string[]> = {
  sv: ["sön", "mån", "tis", "ons", "tors", "fre", "lör"],
  en: ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
};

const MONTHS: Record<DueLocale, readonly string[]> = {
  sv: [
    "jan",
    "feb",
    "mars",
    "apr",
    "maj",
    "juni",
    "juli",
    "aug",
    "sep",
    "okt",
    "nov",
    "dec",
  ],
  en: [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
  ],
};

/** The words for the days next to today. Stored in lower case; a capital is added at the start of a text. */
const RELATIVE: Record<
  DueLocale,
  { yesterday: string; today: string; tomorrow: string }
> = {
  sv: { yesterday: "igår", today: "idag", tomorrow: "imorgon" },
  en: { yesterday: "yesterday", today: "today", tomorrow: "tomorrow" },
};

function ownerDay(): Intl.DateTimeFormat {
  return ownerDateFormat("en-CA", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}

/** Epoch day for a civil date, or null if it does not exist. Pure UTC arithmetic, so DST never shifts the count. */
function civilDay(year: number, month: number, day: number): number | null {
  const date = new Date(Date.UTC(year, month - 1, day));
  // Reject impossible dates such as 2026-02-30 by checking the round trip.
  if (
    date.getUTCFullYear() !== year ||
    date.getUTCMonth() !== month - 1 ||
    date.getUTCDate() !== day
  ) {
    return null;
  }
  return Math.round(date.getTime() / DAY_MS);
}

/**
 * Epoch day of the owner calendar day for `value`: a plain `YYYY-MM-DD`
 * date as written, or an ISO datetime converted to the owner zone.
 */
export function parseDueDay(value: string | null | undefined): number | null {
  if (!value) return null;
  const date = DATE_PATTERN.exec(value);
  if (date) {
    return civilDay(Number(date[1]), Number(date[2]), Number(date[3]));
  }
  const timestamp = TIMESTAMP_PATTERN.exec(value);
  if (!timestamp) return null;
  const written = civilDay(
    Number(timestamp[1]),
    Number(timestamp[2]),
    Number(timestamp[3]),
  );
  // Safari does not parse more than three fractional digits, so the rest is cut before parsing.
  const instant = Date.parse(value.replace(/(\.\d{3})\d+/, "$1"));
  if (written === null || Number.isNaN(instant)) return null;
  return ownerDayNumber(new Date(instant));
}

function ownerClock(): Intl.DateTimeFormat {
  return ownerDateFormat("en-CA", {
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Milliseconds the owner zone is ahead of UTC at `instant` (3 600 000 for Stockholm in winter, 7 200 000 in summer). */
function ownerOffset(instant: number): number {
  const parts = ownerClock().formatToParts(new Date(instant));
  const part = (type: string): number =>
    Number(parts.find((p) => p.type === type)?.value);
  const shown = Date.UTC(
    part("year"),
    part("month") - 1,
    part("day"),
    part("hour"),
    part("minute"),
  );
  return shown - Math.floor(instant / 60_000) * 60_000;
}

/**
 * The instant 23:59 on the owner calendar day `day` (`YYYY-MM-DD`) ends, as an ISO string: the same zone the
 * app shows dates in, whatever the browser's own zone is. `day` must be a complete, existing date.
 */
export function ownerEndOfDay(day: string): string {
  const [year, month, date] = day.split("-").map(Number) as [
    number,
    number,
    number,
  ];
  const wall = Date.UTC(year, month - 1, date, 23, 59);
  // Two passes settle the offset at the instant itself, not at the wall time read as UTC.
  let instant = wall - ownerOffset(wall);
  instant = wall - ownerOffset(instant);
  return new Date(instant).toISOString();
}

/** The owner calendar day `days` after the one `instant` falls on, as `YYYY-MM-DD`. */
export function ownerDayPlus(instant: Date, days: number): string {
  return new Date((ownerDayNumber(instant) + days) * DAY_MS)
    .toISOString()
    .slice(0, 10);
}

/** Days from the owner day of `instant` to the Monday that starts next week: 7 on a Monday, 1 on a Sunday. */
export function ownerDaysToNextMonday(instant: Date): number {
  const weekday = new Date(ownerDayNumber(instant) * DAY_MS).getUTCDay();
  return 7 - ((weekday + 6) % 7);
}

/** Epoch day of the owner calendar day that `instant` falls on. */
export function ownerDayNumber(instant: Date): number {
  const parts = ownerDay().formatToParts(instant);
  const part = (type: string): number =>
    Number(parts.find((p) => p.type === type)?.value);
  const date = new Date(Date.UTC(part("year"), part("month") - 1, part("day")));
  return Math.round(date.getTime() / DAY_MS);
}

/** The owner calendar year of `instant`. */
function ownerYear(instant: Date): number {
  const year = ownerDay()
    .formatToParts(instant)
    .find((p) => p.type === "year");
  return Number(year?.value);
}

function capitalize(text: string): string {
  return text.charAt(0).toLocaleUpperCase() + text.slice(1);
}

/**
 * The one date label of the Work app, for a `YYYY-MM-DD` date or an ISO datetime (`Z` or offset),
 * relative to `now` in the owner zone:
 * - the days next to today read "idag", "imorgon" and "igår" (not with `relative: false`);
 * - a day within a week reads with its weekday: "tors 5 nov" (not with `weekday: false`);
 * - any other day reads as "5 nov", with the year only when it is not the current year.
 * `locale` is a work label locale ("sv-SE", "en-GB"); Swedish reads in Swedish, anything else in English.
 * Missing or invalid input gives an empty label.
 */
export function workDate(
  value: string | null | undefined,
  now: Date,
  locale: string,
  options: WorkDateOptions = {},
): string {
  const due = parseDueDay(value);
  if (due === null || Number.isNaN(now.getTime())) return "";

  const lang: DueLocale = locale.startsWith("sv") ? "sv" : "en";
  const diff = due - ownerDayNumber(now);
  const words = RELATIVE[lang];
  const relativeWord =
    options.relative === false
      ? undefined
      : diff === -1
        ? words.yesterday
        : diff === 0
          ? words.today
          : diff === 1
            ? words.tomorrow
            : undefined;
  if (relativeWord !== undefined) {
    return options.inline ? relativeWord : capitalize(relativeWord);
  }

  const date = new Date(due * DAY_MS);
  const day = `${date.getUTCDate()} ${MONTHS[lang][date.getUTCMonth()]}`;
  const named =
    options.weekday !== false && Math.abs(diff) <= WEEKDAY_DAYS
      ? `${WEEKDAYS[lang][date.getUTCDay()]} ${day}`
      : day;
  const text =
    date.getUTCFullYear() === ownerYear(now)
      ? named
      : `${named} ${date.getUTCFullYear()}`;
  return options.inline ? text : capitalize(text);
}

/** "5 dagar försenad" or "5 days overdue"; one day is singular: "1 dag försenad", "1 day overdue". */
function overdueText(days: number, sv: boolean): string {
  if (sv) return `${days} ${days === 1 ? "dag" : "dagar"} försenad`;
  return `${days} ${days === 1 ? "day" : "days"} overdue`;
}

function none(): RelativeDue {
  return { text: "", tone: "none" };
}

/**
 * The due text of a row: an overdue day reads "5 dagar försenad" (or "5 days overdue"; one day is singular),
 * any other day the `workDate` label (lower case from tomorrow on, "fre 6 nov"), with a tone. Missing or
 * invalid input gives an empty label with tone `none`.
 */
export function relativeDue(
  value: string | null | undefined,
  now: Date,
  locale: DueLocale,
): RelativeDue {
  const due = parseDueDay(value);
  if (due === null || Number.isNaN(now.getTime())) return none();

  const diff = due - ownerDayNumber(now);
  const sv = locale === "sv";

  if (diff < 0) {
    return { text: overdueText(-diff, sv), tone: "overdue" };
  }
  const tone: DueTone =
    diff === 0 ? "today" : diff <= SOON_DAYS ? "soon" : "later";
  // A chip reads "Idag" and "Imorgon" on their own; any other day is lower case: "fre 6 nov".
  const word = diff === 0 || diff === 1;
  return { text: workDate(value, now, locale, { inline: !word }), tone };
}
