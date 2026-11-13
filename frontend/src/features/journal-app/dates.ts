/** Calendar dates (YYYY-MM-DD) are moved and shown in UTC so no local time zone can shift them. */

/** The date `delta` days from a calendar date; malformed input is returned unchanged. */
export function shiftDate(value: string, delta: number): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return value;
  const day = new Date(
    Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]) + delta),
  );
  return day.toISOString().slice(0, 10);
}

/** A calendar date shown as the day it names, whatever the time zone. */
export function formatCalendarDate(value: string, locale: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return value;
  return new Date(
    Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])),
  ).toLocaleDateString(locale, {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

/** An instant shown as a local time of day. */
export function formatTime(value: string, locale: string): string {
  return new Date(value).toLocaleTimeString(locale, {
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * A calendar date as day and short month, without the year and without a trailing period: "26 okt". English gives
 * every month three letters ("14 Sep"), where en-GB alone writes "Sept" beside "3 Nov".
 */
export function formatShortDate(value: string, locale: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return value;
  return new Date(
    Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])),
  )
    .toLocaleDateString(locale, {
      day: "numeric",
      month: "short",
      timeZone: "UTC",
    })
    .replace(/\.$/, "")
    .replace(/\bSept\b/, "Sep");
}

/**
 * A calendar date with its weekday and full month, in lower case: "tisdag 3 november" in Swedish. Used for
 * the day buttons' names, so a screen reader says the whole date. `weekday: "short"` gives "ons 4 november".
 */
export function formatLongDate(
  value: string,
  locale: string,
  weekday: "long" | "short" = "long",
): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return value;
  return new Date(
    Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])),
  ).toLocaleDateString(locale, {
    weekday,
    day: "numeric",
    month: "long",
    timeZone: "UTC",
  });
}

/**
 * A calendar date with its weekday, as a heading: "Tisdag 3 november" in Swedish, "Tuesday 3 November" in
 * English. The year is added only when the date is not in the year of `today`: "Tisdag 3 november 2025".
 * `weekday: "short"` is the form for a title row too narrow for the long one: "Ons 4 november", "Wed 4 November".
 */
export function formatDayHeading(
  value: string,
  locale: string,
  today: string,
  weekday: "long" | "short" = "long",
): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return value;
  const long = formatLongDate(value, locale, weekday);
  const capitalized = long.charAt(0).toLocaleUpperCase(locale) + long.slice(1);
  const sameYear = value.slice(0, 4) === today.slice(0, 4);
  return sameYear ? capitalized : `${capitalized} ${value.slice(0, 4)}`;
}

/** A short date ("26 okt") that adds the year only when the date is not in the year of `today`. */
export function formatShortDateWithYear(
  value: string,
  locale: string,
  today: string,
): string {
  const short = formatShortDate(value, locale);
  const sameYear = value.slice(0, 4) === today.slice(0, 4);
  return sameYear || !/^\d{4}-/.test(value)
    ? short
    : `${short} ${value.slice(0, 4)}`;
}

/** "today" or "yesterday" when the calendar date is one of those days, otherwise undefined. */
export function relativeDay(
  value: string,
  today: string,
): "today" | "yesterday" | undefined {
  if (value === today) return "today";
  if (value === shiftDate(today, -1)) return "yesterday";
  return undefined;
}

/** A whole number with the locale's grouping separator: "1 840" in Swedish, "11,405" in English. */
export function formatCount(value: number, locale: string): string {
  return new Intl.NumberFormat(locale).format(value);
}
