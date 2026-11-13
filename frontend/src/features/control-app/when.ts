/**
 * A time as a person would say it: "nyss", "för 12 min sedan", "idag 14:30", "igår 09:05", "30 okt".
 * Only today and yesterday carry a clock; older times show the date alone. Never an ISO string. The
 * calendar day is the owner's (the zone the backend declares, Stockholm by default), like the other
 * Sidekick apps, so the words do not depend on the host's time zone. Pure: the caller passes `now`.
 */
import { ownerDateFormat } from "../mcp-apps/app-timezone";

export type WhenLocale = "sv" | "en";

const DAY_MS = 86_400_000;

const MONTHS: Record<WhenLocale, readonly string[]> = {
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

const WORDS = {
  sv: {
    now: "nyss",
    minutes: (n: number) => `för ${n} min sedan`,
    today: "idag",
    yesterday: "igår",
    dayAt: (day: string, clock: string) => `${day} ${clock}`,
  },
  en: {
    now: "just now",
    minutes: (n: number) => `${n} min ago`,
    today: "today",
    yesterday: "yesterday",
    dayAt: (day: string, clock: string) => `${day} at ${clock}`,
  },
};

function formatter(): Intl.DateTimeFormat {
  return ownerDateFormat("en-CA", {
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

type Stamp = {
  year: number;
  month: number;
  day: number;
  hour: string;
  minute: string;
};

function stampOf(date: Date): Stamp {
  const found: Record<string, string> = {};
  for (const part of formatter().formatToParts(date))
    found[part.type] = part.value;
  return {
    year: Number(found.year),
    month: Number(found.month),
    day: Number(found.day),
    hour: found.hour ?? "00",
    minute: found.minute ?? "00",
  };
}

function dayNumber(stamp: Stamp): number {
  return Math.round(Date.UTC(stamp.year, stamp.month - 1, stamp.day) / DAY_MS);
}

/** The time as spoken text, or "" when `value` is missing or not a valid timestamp. */
export function whenText(
  value: string | null | undefined,
  now: Date,
  locale: WhenLocale,
): string {
  if (!value) return "";
  const then = new Date(value);
  if (Number.isNaN(then.getTime())) return "";
  const words = WORDS[locale];
  const ageMinutes = Math.floor((now.getTime() - then.getTime()) / 60_000);
  if (ageMinutes < 1) return words.now;
  if (ageMinutes < 60) return words.minutes(ageMinutes);
  const stamp = stampOf(then);
  const clock = `${stamp.hour}:${stamp.minute}`;
  // Today and yesterday, by the owner calendar, keep the clock; anything older is only a date.
  const daysAgo = dayNumber(stampOf(now)) - dayNumber(stamp);
  if (daysAgo <= 0) return words.dayAt(words.today, clock);
  if (daysAgo === 1) return words.dayAt(words.yesterday, clock);
  const month = MONTHS[locale][stamp.month - 1] ?? "";
  const year = stamp.year === stampOf(now).year ? "" : ` ${stamp.year}`;
  return `${stamp.day} ${month}${year}`;
}
