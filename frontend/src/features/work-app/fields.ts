/** Title limit of the update_task and update_project schemas (200 characters). */
export const TITLE_MAX_LENGTH = 200;

export type TitleProblem = "required" | "tooLong";

export function titleProblem(title: string): TitleProblem | undefined {
  const value = title.trim();
  if (!value) return "required";
  if (Array.from(value).length > TITLE_MAX_LENGTH) return "tooLong";
  return undefined;
}

/** Local midnight of a calendar day; setFullYear keeps years 0-99 instead of mapping them to 19xx. */
export function localMidnight(year: number, month: number, day: number): Date {
  const date = new Date(2000, 0, 1);
  date.setFullYear(year, month - 1, day);
  date.setHours(0, 0, 0, 0);
  return date;
}

/** A complete YYYY-MM-DD with a four-digit year from 1000 on that exists in the calendar. */
export function isCompleteDate(value: string): boolean {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return false;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (year < 1000) return false;
  const date = localMidnight(year, month, day);
  return date.getMonth() === month - 1 && date.getDate() === day;
}

/**
 * After a reload a draft keeps the value of each field the user changed and follows the latest
 * value for every other field. `current` is the draft as it was before the reload.
 */
export function keepEdits<V extends Record<string, string>>(
  current: { values: V; base: V },
  fresh: V,
): V {
  const merged: V = { ...fresh };
  for (const key of Object.keys(fresh) as (keyof V)[]) {
    if (current.values[key] !== current.base[key])
      merged[key] = current.values[key];
  }
  return merged;
}
