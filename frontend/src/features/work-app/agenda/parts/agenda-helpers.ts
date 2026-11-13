import type { CSSProperties } from "react";
import { agendaGroupLabel, type WorkLabels } from "../../shared/labels";
import { fillLabel } from "../agenda-undo";
import { parseDueDay, workDate } from "../../../mcp-apps/ui/due";
import {
  cardKey,
  triageDueAt,
  type DatedAgendaSection,
} from "../../shared/work-items";
import type { WorkItemRecord, WorkTask } from "../../transport/transport";

/**
 * A status as this view last saw or wrote it, with the version that goes with it. A due-date move
 * also keeps the due instant the reply gave (`due_at`), so the row shows the new date.
 */
export type Override = {
  status: string;
  version: number;
  due_at?: string | null;
  /** The completion on record the reply gave (a recurring Task keeps it when reopened), for the next Undo. */
  last_completed_at?: string | null;
  /**
   * The write marked a recurring Task done and the server reopened it for its next date: the row shows
   * "Klar · nästa: …", and its Ångra writes `cycle.from` back as the due date.
   */
  cycle?: RecurringCycle;
};

/** Two due instants name the same moment, or both name no date. */
export function sameDue(
  left: string | null | undefined,
  right: string | null,
): boolean {
  const a = left ?? null;
  if (a === null || right === null) return a === right;
  return Date.parse(a) === Date.parse(right);
}

/**
 * A recurring Task marked done is not left done: the server records the cycle (`last_completed_at`) and reopens the
 * same Task with its next due date in one reply. So the reply to "done" says "todo" with a new date, and the view
 * tells it apart with this check ("Klar · nästa: …"), or the tap looks as if it did nothing. `from` is the due date the
 * Task had before; Ångra writes it back.
 */
export type RecurringCycle = {
  from: string | null;
  /** The completion on record before this one (`last_completed_at`); Ångra writes it back with the due date. */
  lastCompleted?: string | null;
};

/**
 * The reply to a status write is a recorded cycle of a recurring Task: the Task repeats, is open again, has a
 * completion on record and a due date other than the one it had (`before`).
 */
export function isRecurringCycle(
  task: Pick<
    WorkTask,
    "status" | "due_at" | "recurrence" | "last_completed_at"
  >,
  before: string | null | undefined,
): boolean {
  return (
    task.status !== "completed" &&
    task.recurrence != null &&
    task.last_completed_at != null &&
    !sameDue(task.due_at, before ?? null)
  );
}

/** The line of a recorded cycle: "Klar · nästa: fre 27 nov", or "Klar · upprepas" when the reply has no next date. */
export function recurringDoneText(
  t: WorkLabels,
  next: string | null | undefined,
  now: Date,
): string {
  return next
    ? fillLabel(t.recurringDone, {
        date: workDate(next, now, t.dateLocale, { inline: true }),
      })
    : t.recurringDoneNoDate;
}

/** The row menu's date shortcuts, in their order (Idag first). */
export const DUE_SHORTCUTS = ["today", "tomorrow", "nextWeek"] as const;

/**
 * The override a reply leaves: its status and version, and its due instant for a due-date move. A status write that
 * recorded a recurring Task's cycle (`before` is the due date the row showed) also keeps the next due date and the
 * cycle; any later write ends the cycle.
 */
export function afterWrite(
  previous: Override | undefined,
  task: WorkTask,
  due: boolean,
  before?: string | null,
): Override {
  const rest = { ...previous };
  delete rest.cycle;
  const completed = { last_completed_at: task.last_completed_at ?? null };
  if (due)
    return {
      ...rest,
      status: task.status,
      version: task.version,
      due_at: task.due_at,
      ...completed,
    };
  if (isRecurringCycle(task, before))
    return {
      ...rest,
      status: task.status,
      version: task.version,
      due_at: task.due_at ?? null,
      ...completed,
      cycle: { from: before ?? null },
    };
  return { ...rest, status: task.status, version: task.version, ...completed };
}

/** The row with the override of its key applied: the status, version and (for a due move) due date it last wrote. */
export function currentWith(
  all: Record<string, Override>,
  item: WorkItemRecord,
): WorkItemRecord {
  const over = all[cardKey(item)];
  if (!over) return item;
  return {
    ...item,
    status: over.status,
    version: over.version,
    ...(over.due_at !== undefined ? { due_at: over.due_at } : {}),
    ...(over.last_completed_at !== undefined
      ? { last_completed_at: over.last_completed_at }
      : {}),
  };
}

/**
 * A group heading stays at the top while its records scroll under it. The top sits under the host's
 * overlaid navigation (--sk-sticky-top, see the design tokens), so a heading does not slide under it.
 */
export const stickyHeading: CSSProperties = {
  position: "sticky",
  top: "var(--sk-sticky-top, 0px)",
  zIndex: 1,
  // The page's own colour (as the board's sticky chips): --sk-bg has a different dark fallback and showed as a band.
  background: "var(--color-background-primary, Canvas)",
};

/** The outline of the row the keys have selected. */
export const selectedRow: CSSProperties = {
  outline: "2px solid currentColor",
  outlineOffset: 2,
};

/** How long a done row takes to fold away once its Undo has run out. */
export const LEAVE_MS = 200;

/**
 * The note under an overdue Task that a triage button changed, until the list is read again: "Klar" when
 * it is done, else "Flyttad till <date>" with its new due date.
 */
export function triagedNote(
  t: WorkLabels,
  item: WorkItemRecord,
  now: Date,
): string | undefined {
  if (item.status === "completed") return t.taskStatus.completed;
  if (!item.due_at) return undefined;
  return fillLabel(t.movedTo, {
    status: workDate(item.due_at, now, t.dateLocale, { inline: true }),
  });
}

/** The day of a heading with its weekday: "ons 28 okt" in Swedish, "Wed 28 Oct" in English. */
function headingDay(date: Date, locale: string): string {
  return new Intl.DateTimeFormat(locale, {
    weekday: "short",
    day: "numeric",
    month: "short",
  })
    .format(date)
    .replace(/\.$/, "");
}

/**
 * A section heading. Only Försenade has a count ("Försenade (2)"), since there the count bears a decision; time
 * groups have none (designsystem §3). Today's heading also names the day ("Idag, ons 28 okt"). `count` is the open
 * rows, the same number "Flytta N" moves: a row standing for its Ångra no longer counts, so "Försenade (4)" and
 * "Flytta 4" agree.
 */
export function sectionHeading(
  t: WorkLabels,
  section: DatedAgendaSection,
  now: Date,
  count: number,
): string {
  const name = agendaGroupLabel(t, section.group);
  const head =
    section.group === "today"
      ? `${name}, ${headingDay(now, t.dateLocale)}`
      : name;
  return section.group === "overdue" ? `${head} (${count})` : head;
}

/** `YYYY-MM-DD` of an epoch day (parseDueDay's count): the date field's value. */
export function epochDayIso(day: number): string {
  return new Date(day * 86_400_000).toISOString().slice(0, 10);
}

/** Keys that edit a segment of the date field: a digit, a separator, the arrows up/down, Backspace and the like. */
export function editsDate(key: string): boolean {
  return (
    (key.length === 1 && key !== " ") ||
    [
      "ArrowUp",
      "ArrowDown",
      "PageUp",
      "PageDown",
      "Backspace",
      "Delete",
    ].includes(key)
  );
}

/**
 * The overdue group, oldest due date first (A4); a row without a date goes last. It sorts by the date as read, so
 * a row a triage move changed keeps its place until the list is read again (otherwise the moved row jumped to the end).
 */
export function oldestFirst(records: WorkItemRecord[]): WorkItemRecord[] {
  const time = (record: WorkItemRecord) => {
    const at = Date.parse(record.due_at ?? "");
    return Number.isNaN(at) ? Number.MAX_SAFE_INTEGER : at;
  };
  return [...records].sort((a, b) => time(a) - time(b));
}

/**
 * A Task's due day against the row menu's three shortcuts, so the menu shows the current date as chosen:
 * the day (null for none), the shortcut that names it, and the folded Datum group's meta at large text (the chosen
 * chip's text).
 */
export function dueChoiceOf(item: WorkItemRecord, now: Date, t: WorkLabels) {
  const dueDay = parseDueDay(item.due_at);
  const dueShortcut =
    dueDay === null
      ? undefined
      : DUE_SHORTCUTS.find(
          (target) => parseDueDay(triageDueAt(now, target)) === dueDay,
        );
  const dueMeta =
    dueDay === null
      ? undefined
      : dueShortcut === "today"
        ? t.agendaGroup.today
        : dueShortcut === "tomorrow"
          ? t.triageTomorrow
          : dueShortcut === "nextWeek"
            ? t.triageNextWeek
            : workDate(item.due_at, now, t.dateLocale);
  return { dueDay, dueShortcut, dueMeta };
}
