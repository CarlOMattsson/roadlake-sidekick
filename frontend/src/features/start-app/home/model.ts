/**
 * The home view's model (pure): what get_start answered, put in the order of urgency and in words. Nothing here
 * invents a part: a block is drawn only when the server sent it, and no count of nothing is shown.
 */
import type { RoomTarget } from "../../mcp-apps/room-types";
import { ownerClockTime, relativeDue, workDate } from "../../mcp-apps/ui/due";
import type { ToolResults } from "@/lib/mcp/tool-results.generated";
import type { HomeLabels } from "./labels";

type Generated = ToolResults["get_start"];

/** get_start's answer: `day`, then each part only when the scopes allowed it and it had something to say. */
export type StartHome = { day: string } & Partial<Omit<Generated, "day">>;
export type StartToday = NonNullable<Generated["today"]>;
export type StartTodayRow = StartToday["items"][number];
export type StartWaiting = NonNullable<Generated["waiting"]>;
export type StartWaitingRow = StartWaiting["items"][number];
export type StartReadyRow = NonNullable<Generated["ready"]>["items"][number];
export type StartSinceLast = NonNullable<Generated["since_last"]>;
export type StartPart = NonNullable<Generated["unavailable"]>[number]["part"];

type Obj = Record<string, unknown>;
const isObj = (value: unknown): value is Obj =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/** A get_start answer: a day and no list of its own (the suggestion page and the others carry `items`). */
export function isStartHome(value: unknown): value is StartHome {
  return (
    isObj(value) &&
    typeof value.day === "string" &&
    /^\d{4}-\d{2}-\d{2}$/.test(value.day) &&
    !("items" in value)
  );
}

/**
 * The parts the page names when they could not be read. The insight and the menu counts are left out: a missing
 * sentence or count is not a block of its own, and the rest of the page says what it can.
 */
const NAMED_FAILURES: readonly StartPart[] = [
  "ready",
  "suggestions",
  "today",
  "waiting",
  "since_last",
];

export function failedParts(start: StartHome): StartPart[] {
  const failed = new Set((start.unavailable ?? []).map((item) => item.part));
  return NAMED_FAILURES.filter((part) => failed.has(part));
}

/** The ready conversations still to show: those the owner has not skipped here while the page waits for the server. */
export function readyRows(
  start: StartHome,
  hidden: ReadonlySet<string>,
): StartReadyRow[] {
  return (start.ready?.items ?? []).filter((row) => !hidden.has(row.id));
}

/**
 * True when nothing on the page asks for the owner: no sentence, no ready conversation, no task of today and none
 * that waits, and no part that failed. The ways to the suggestions and the automations stay under it.
 */
export function isQuiet(start: StartHome, hidden: ReadonlySet<string>) {
  return (
    !start.insight?.text.trim() &&
    readyRows(start, hidden).length === 0 &&
    !start.today?.items.length &&
    !start.waiting?.items.length &&
    failedParts(start).length === 0
  );
}

/** "Måndag 23 november", "Monday 23 November": the day get_start is for, as the page's title. */
export function homeHeading(day: string, locale: string): string {
  const [year, month, date] = day.split("-").map(Number);
  if (!year || !month || !date) return day;
  // A plain date: formatted at noon UTC in UTC, so no zone moves it to another day.
  const text = new Intl.DateTimeFormat(locale, {
    weekday: "long",
    day: "numeric",
    month: "long",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(year, month - 1, date, 12)));
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** "17:00" from the cadence's local time ("17:00" or "17:00:00"); anything else is shown as it came. */
export function readyTime(localTime: string): string {
  const match = /^(\d{1,2}):(\d{2})/.exec(localTime);
  return match ? `${match[1]!.padStart(2, "0")}:${match[2]}` : localTime;
}

/** How many of today's tasks (overdue included) the rows do not show. */
export function todayMore(today: StartToday): number {
  return Math.max(
    0,
    today.overdue_count + today.today_count - today.items.length,
  );
}

/** The record a row opens: a Task or a Project in Work. Another kind opens nothing. */
export function recordTarget(item: {
  kind: string;
  id: string;
  title: string;
}): RoomTarget | undefined {
  if (item.kind === "task")
    return { room: "work", view: "task", id: item.id, label: item.title };
  if (item.kind === "project")
    return { room: "work", view: "project", id: item.id, label: item.title };
  return undefined;
}

/** A waiting row opens its Task. */
export function waitingTarget(row: StartWaitingRow): RoomTarget {
  return { room: "work", view: "task", id: row.id, label: row.title };
}

/**
 * The meta line of a row of today: how late it is ("8 dagar försenad", the overdue tone) or "Idag" with its time, then
 * the project when the scope gave it.
 */
export function todayMeta(
  row: StartTodayRow,
  now: Date,
  t: HomeLabels,
): { due: string; overdue: boolean; project?: string } {
  const sv = t.dateLocale.startsWith("sv");
  const project = row.project_title ?? undefined;
  if (row.agenda_group === "overdue") {
    const due = relativeDue(row.due_at, now, sv ? "sv" : "en");
    return { due: due.text || t.dueToday, overdue: due.text !== "", project };
  }
  const time = ownerClockTime(row.due_at);
  return {
    due: time ? `${t.dueToday} ${time}` : t.dueToday,
    overdue: false,
    project,
  };
}

/** "Erik Sjöstrand · sedan 13 nov", or "sedan 13 nov" when the contact's name was not readable. */
export function waitingMeta(
  row: StartWaitingRow,
  now: Date,
  t: HomeLabels,
): string {
  const since = t.waitingSince(
    workDate(row.waiting_since, now, t.dateLocale, {
      inline: true,
      weekday: false,
    }),
  );
  return row.contact_name ? `${row.contact_name} · ${since}` : since;
}

/** How many waiting tasks the rows do not show. */
export function waitingMore(waiting: StartWaiting): number {
  return Math.max(0, waiting.total - waiting.items.length);
}

/**
 * What the automations did since the owner last looked, in one line: "Sedan sist: 3 körningar · 1 misslyckades · 5 nya
 * förslag". A count of nothing is left out, and a window with nothing in it gives undefined.
 */
export function sinceLastLine(
  since: StartSinceLast | undefined | null,
  t: HomeLabels,
): string | undefined {
  if (!since) return undefined;
  const parts = [
    since.runs > 0 ? t.runs(since.runs) : null,
    since.failed_runs > 0 ? t.failedRuns(since.failed_runs) : null,
    since.suggestions_created > 0 ? t.created(since.suggestions_created) : null,
    since.suggestions_decided > 0 ? t.decided(since.suggestions_decided) : null,
  ].filter((part): part is string => part !== null);
  return parts.length ? `${t.sinceLast}: ${parts.join(" · ")}` : undefined;
}

/**
 * The automations row's line: what failed today first (it asks for the owner), else what happened since the last
 * look. Nothing when neither has anything to say.
 */
export function automationsMeta(
  start: StartHome,
  t: HomeLabels,
): { text: string; failed: boolean } | undefined {
  const failed = start.more?.automations_failed_today ?? 0;
  if (failed > 0) return { text: t.failedToday(failed), failed: true };
  const line = sinceLastLine(start.since_last, t);
  return line ? { text: line, failed: false } : undefined;
}

/** The suggestions row's line, when suggestions wait: "5 väntar på ditt svar" (one line, also at 320). */
export function suggestionsMeta(
  start: StartHome,
  t: HomeLabels,
): string | undefined {
  const pending = start.suggestions?.pending_count ?? 0;
  if (pending <= 0) return undefined;
  return t.suggestionsWaiting(pending);
}

/** The longest a title may be in the phrase sent to Claude; the rest is cut at a word with "…". */
export const PHRASE_TITLE_MAX = 80;

/**
 * The title as it stands in the phrase: on one line, without the quotes the phrase puts around it, and cut when long.
 * The title is the owner's or Claude's own words; the phrase names the conversation and asks for nothing more.
 */
export function phraseTitle(title: string): string {
  const flat = title.replace(/\s+/g, " ").replace(/[”“"]/g, "'");
  const clean = flat.trim();
  if (clean.length <= PHRASE_TITLE_MAX) return clean;
  const cut = clean.slice(0, PHRASE_TITLE_MAX);
  const space = cut.lastIndexOf(" ");
  return `${(space > 40 ? cut.slice(0, space) : cut).trimEnd()}…`;
}
