import { parseDueDay } from "../../mcp-apps/ui/due";
import type { RecurrenceRecord } from "../../../lib/mcp/tool-results.generated";

/**
 * The next occurrence of a repeat rule, counted in owner calendar days (epoch days, as `ownerDayNumber` gives them).
 * A mirror of `RecurrenceRule.next_due_at` in backend/src/sidekick/tasks/domain/recurrence.py: the server counts from the
 * day the Task is completed (`today` here, as if it were completed now), and a monthly rule counts its months from the
 * day the Task is due. Keep the two in step.
 */
export type NextRule = Pick<RecurrenceRecord, "frequency"> &
  Partial<
    Pick<
      RecurrenceRecord,
      "interval" | "weekdays" | "day_of_month" | "last_weekday" | "until"
    >
  >;

const DAY_MS = 86_400_000;
/** Stepping a monthly rule past a long-overdue due date stops after a century of months (as the server does). */
const MAX_MONTHLY_STEPS = 1200;

type Civil = { year: number; month: number; day: number };

function civil(day: number): Civil {
  const date = new Date(day * DAY_MS);
  return {
    year: date.getUTCFullYear(),
    month: date.getUTCMonth() + 1,
    day: date.getUTCDate(),
  };
}

function epochDay(year: number, month: number, day: number): number {
  return Math.round(Date.UTC(year, month - 1, day) / DAY_MS);
}

/** Monday is 0, as in the rule's weekdays (1970-01-01 was a Thursday). */
export function weekdayOf(day: number): number {
  return (((day + 3) % 7) + 7) % 7;
}

function lastDayOfMonth(year: number, month: number): number {
  return epochDay(year, month + 1, 1) - 1;
}

/** The occurrence `months` after the month of `base`, as the server's `_monthly_candidate`. */
function monthlyCandidate(rule: NextRule, base: Civil, months: number): number {
  const total = base.year * 12 + base.month - 1 + months;
  const year = Math.floor(total / 12);
  const month = (total % 12) + 1;
  const last = lastDayOfMonth(year, month);
  if (rule.last_weekday) return last - Math.max(0, weekdayOf(last) - 4);
  const wanted = rule.day_of_month || base.day;
  return epochDay(year, month, Math.min(wanted, civil(last).day));
}

/**
 * The day the rule next falls on if the Task is completed on `today`, or null when the rule has ended (`until` passed)
 * or its numbers are not ones the server accepts. `dueDay` is the Task's current due day (null when it has none).
 */
export function nextOccurrenceDay(
  rule: NextRule,
  today: number,
  dueDay: number | null,
): number | null {
  const interval = rule.interval ?? 1;
  if (!Number.isInteger(interval) || interval < 1 || interval > 12) return null;
  const weekdays = rule.weekdays ?? [];
  let candidate = today;
  if (rule.frequency === "daily") {
    candidate = today + interval;
  } else if (rule.frequency === "weekly") {
    const weekday = weekdayOf(today);
    if (weekdays.length === 0) {
      candidate = today + 7 * interval;
    } else if (interval > 1) {
      // Stay in this week while an allowed weekday is still ahead; otherwise jump `interval` weeks to the earliest one.
      const weekStart = today - weekday;
      const later = weekdays.filter((day) => day > weekday);
      candidate =
        later.length > 0
          ? weekStart + Math.min(...later)
          : weekStart + 7 * interval + Math.min(...weekdays);
    } else {
      for (let ahead = 1; ahead <= 14; ahead += 1) {
        if (weekdays.includes(weekdayOf(today + ahead))) {
          candidate = today + ahead;
          break;
        }
      }
    }
  } else if (rule.frequency === "monthly") {
    // The months count from the one the Task is due in; an occurrence on or before today has already passed.
    const base = civil(dueDay ?? today);
    for (let steps = 1; steps <= MAX_MONTHLY_STEPS; steps += 1) {
      candidate = monthlyCandidate(rule, base, steps * interval);
      if (candidate > today) break;
    }
  } else if (rule.frequency === "yearly") {
    const from = civil(today);
    const year = from.year + interval;
    const same = epochDay(year, from.month, from.day);
    // 29 February in a year without one falls on the 28th.
    candidate =
      civil(same).month === from.month ? same : epochDay(year, from.month, 28);
  }
  const until = parseDueDay(rule.until ?? null);
  return until !== null && candidate > until ? null : candidate;
}

/** The owner calendar day as `YYYY-MM-DD`, the form `workDate` reads. */
export function dayText(day: number): string {
  return new Date(day * DAY_MS).toISOString().slice(0, 10);
}
