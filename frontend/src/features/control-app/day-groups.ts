import { ownerDayNumber, workDate } from "../mcp-apps/ui/due";
import type { WhenLocale } from "./when";

const DAY_MS = 86_400_000;

/** The rows of one calendar day (the owner's) under its heading. A row whose time cannot be read has no heading. */
export type DayGroup<T> = {
  key: string;
  /** "Idag", "Igår", "tis 17 nov" ("Today", "Yesterday", "Tue 17 Nov"); "" for rows with no readable time. */
  heading: string;
  rows: T[];
};

/**
 * Splits rows that are already newest first into one group per calendar day, in order. The day is the owner's, as every
 * time in the app (`workDate`), so the words do not depend on the host's zone. A time ahead of `now` (a clock that runs
 * fast) counts as today, never as "tomorrow". Pure: the caller passes `now`.
 */
export function groupByDay<T>(
  rows: readonly T[],
  timeOf: (row: T) => string,
  now: Date,
  locale: WhenLocale,
): DayGroup<T>[] {
  const today = ownerDayNumber(now);
  const groups: DayGroup<T>[] = [];
  for (const row of rows) {
    const at = new Date(timeOf(row));
    const day = Number.isNaN(at.getTime())
      ? null
      : Math.min(ownerDayNumber(at), today);
    const key = day === null ? "unknown" : String(day);
    const last = groups[groups.length - 1];
    if (last?.key === key) {
      last.rows.push(row);
      continue;
    }
    groups.push({
      key,
      heading:
        day === null
          ? ""
          : workDate(
              new Date(day * DAY_MS).toISOString().slice(0, 10),
              now,
              locale,
              // "Idag" and "Igår" start a heading with a capital; a weekday date ("tis 17 nov") stays as it is spoken.
              { inline: day < today - 1 },
            ),
      rows: [row],
    });
  }
  return groups;
}
