import { formatLongDate } from "./dates";
import { hasDaySummary } from "./day-summary";
import type { JournalLabels } from "./labels";
import type { JournalDay } from "./transport";

/** What a week list draws: a day with something to read, or a run of days with nothing, as one quiet line. */
export type WeekSegment =
  { kind: "day"; day: JournalDay } | { kind: "gap"; dates: string[] };

/** A day with something done (a task, a step or a purchase), so its «Gjort» is worth a section of its own. */
function hasDone(day: JournalDay): boolean {
  const counts = day.done?.counts;
  return (
    counts !== undefined && counts.tasks + counts.steps + counts.purchases > 0
  );
}

/** A day with no entry, no summary and nothing done. */
export function isEmptyDay(day: JournalDay): boolean {
  return (
    day.entries.length === 0 && !hasDaySummary(day.summary) && !hasDone(day)
  );
}

/** The days in order, each run of empty days folded into one gap. */
export function weekSegments(days: readonly JournalDay[]): WeekSegment[] {
  const segments: WeekSegment[] = [];
  for (const day of days) {
    if (!isEmptyDay(day)) {
      segments.push({ kind: "day", day });
      continue;
    }
    const last = segments.at(-1);
    if (last?.kind === "gap") last.dates.push(day.journal_date);
    else segments.push({ kind: "gap", dates: [day.journal_date] });
  }
  return segments;
}

/** The weekday of a date, short, from the date helper's own words: "mån" in Swedish, "Mon" in English. */
function weekdayName(date: string, locale: string): string {
  return formatLongDate(date, locale, "short").split(/[\s,]+/)[0] ?? date;
}

/**
 * The words of a gap: "Inget skrivet mån–ons", "Inget skrivet tors" for one day, and "Inget skrivet vecka 44" when
 * no day of the week has anything (`wholeWeek`, with the week's number).
 */
export function weekGapText(
  dates: readonly string[],
  labels: JournalLabels,
  wholeWeek: number | undefined,
): string {
  if (wholeWeek !== undefined) return labels.weekGapWeek(wholeWeek);
  const first = dates[0];
  const last = dates.at(-1);
  if (!first || !last) return "";
  const from = weekdayName(first, labels.dateLocale);
  const range =
    first === last ? from : `${from}–${weekdayName(last, labels.dateLocale)}`;
  return labels.weekGapNothing(range);
}
