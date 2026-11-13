import { workStatusLabel, type WorkLabels } from "./labels";
import {
  TASK_STATUSES,
  type WorkAgendaPage,
  type WorkBoardPage,
  type WorkFrame,
  type WorkItemRecord,
} from "../transport/transport";
import {
  ownerDayPlus,
  ownerDaysToNextMonday,
  ownerEndOfDay,
} from "../../mcp-apps/ui/due";

/** The agenda groups the server assigns, in the order the agenda shows them. */
export const AGENDA_GROUPS = [
  "overdue",
  "today",
  "upcoming",
  "scheduled_later",
] as const;

/** Identity of a Work record on a board or agenda: the same record is shown once. */
export function cardKey(item: WorkItemRecord): string {
  return `${item.kind}:${item.id}`;
}

/**
 * Columns of the board in board order: the Task statuses first, then any other status the server
 * returned, so a column is never silently dropped.
 */
export function boardColumns(columns: WorkBoardPage["columns"]): string[] {
  const known = TASK_STATUSES as readonly string[];
  return [
    ...known,
    ...Object.keys(columns).filter((key) => !known.includes(key)),
  ];
}

/** Key of the Projects segment of the single-column board. */
export const PROJECT_SEGMENT = "project";

/**
 * One segment of the single-column board: a Task status, or the Projects segment. `columns` lists
 * the board columns the segment shows, in board order.
 */
export type BoardSegment = {
  key: string;
  label: string;
  count: number;
  columns: string[];
};

/**
 * The records a segment shows, in board order. A Task status segment shows the Tasks of its column;
 * a Project column holds Projects, so Projects are never counted as Tasks. The Projects segment shows
 * every Project and every record in a column that is not a Task status.
 */
export function segmentItems(
  page: WorkBoardPage,
  segment: BoardSegment,
): WorkItemRecord[] {
  const known = TASK_STATUSES as readonly string[];
  const projects = segment.key === PROJECT_SEGMENT;
  return segment.columns.flatMap((column) =>
    (page.columns[column] ?? []).filter((item) =>
      projects
        ? item.kind === "project" || !known.includes(column)
        : item.kind !== "project",
    ),
  );
}

/**
 * The segments of the single-column board: the four Task statuses in fixed order, then a Projects
 * segment when the page holds any Project or any record outside the Task statuses. Every record
 * on the page is shown in exactly one segment.
 */
export function boardSegments(
  page: WorkBoardPage,
  t: WorkLabels,
): BoardSegment[] {
  const known = TASK_STATUSES as readonly string[];
  const segments: BoardSegment[] = TASK_STATUSES.map((status) => ({
    key: status,
    label: workStatusLabel(t, status),
    count: 0,
    columns: [status],
  }));
  for (const segment of segments)
    segment.count = segmentItems(page, segment).length;
  // A Project status column (such as "completed") can also be a Task status; it joins the Projects
  // segment only when it holds a Project.
  const projectColumns = boardColumns(page.columns).filter(
    (column) =>
      !known.includes(column) ||
      (page.columns[column] ?? []).some((item) => item.kind === "project"),
  );
  const projects: BoardSegment = {
    key: PROJECT_SEGMENT,
    label: t.projects,
    count: 0,
    columns: projectColumns,
  };
  projects.count = segmentItems(page, projects).length;
  if (projects.count > 0) segments.push(projects);
  return segments;
}

/**
 * The segment a board opens on. A saved column (the frame's `column`) wins when a segment shows it,
 * even when that segment is empty. Otherwise the first non-empty of "Att göra", "Pågår" and
 * "Blockerad", and otherwise "Att göra". Returns the segment key.
 */
export function defaultBoardSegment(
  segments: BoardSegment[],
  saved?: string,
): string {
  if (saved) {
    const shown = segments.find(
      (segment) => segment.key === saved || segment.columns.includes(saved),
    );
    if (shown) return shown.key;
  }
  const firstFilled = ["todo", "in_progress", "blocked"]
    .map((key) => segments.find((segment) => segment.key === key))
    .find((segment) => segment && segment.count > 0);
  return firstFilled?.key ?? TASK_STATUSES[0];
}

/**
 * Adds a later board page to the shown one. Columns keep their order and a record that is already
 * shown anywhere is not added again.
 */
export function appendBoardPage(
  shown: WorkBoardPage,
  later: WorkBoardPage,
): WorkBoardPage {
  const seen = new Set<string>();
  for (const list of Object.values(shown.columns))
    for (const item of list) seen.add(cardKey(item));
  const columns: WorkBoardPage["columns"] = {};
  for (const key of new Set([
    ...Object.keys(shown.columns),
    ...Object.keys(later.columns),
  ])) {
    const fresh = (later.columns[key] ?? []).filter((item) => {
      if (seen.has(cardKey(item))) return false;
      seen.add(cardKey(item));
      return true;
    });
    columns[key] = [...(shown.columns[key] ?? []), ...fresh];
  }
  return { ...later, columns };
}

/** Adds a later agenda page to the shown one, without showing a record twice. */
export function appendAgendaPage(
  shown: WorkAgendaPage,
  later: WorkAgendaPage,
): WorkAgendaPage {
  const seen = new Set(shown.items.map(cardKey));
  const fresh = later.items.filter((item) => !seen.has(cardKey(item)));
  return { items: [...shown.items, ...fresh], next_cursor: later.next_cursor };
}

/** One heading of the agenda; a null group means the records are listed without a heading. */
export type AgendaSection = { group: string | null; items: WorkItemRecord[] };

/**
 * Groups the agenda by the agenda_group the server returned, in the server's order inside each
 * group. When no record carries a group, the list stays flat in the order it arrived.
 */
export function groupAgenda(items: WorkItemRecord[]): AgendaSection[] {
  if (!items.some((item) => item.agenda_group))
    return items.length ? [{ group: null, items }] : [];
  const sections: AgendaSection[] = [];
  for (const group of [...AGENDA_GROUPS, "other"]) {
    const members = items.filter((item) =>
      group === "other"
        ? !(AGENDA_GROUPS as readonly string[]).includes(
            item.agenda_group ?? "",
          )
        : item.agenda_group === group,
    );
    if (members.length) sections.push({ group, items: members });
  }
  return sections;
}

/**
 * A heading of the fullscreen agenda. The server marks overdue and today; the rest is split by the
 * due date in the local calendar, Monday to Sunday. Records without a due date are "undated".
 */
export type AgendaBucket =
  | "overdue"
  | "today"
  | "thisWeek"
  | "nextWeek"
  | "later"
  | "undated";

/** A fullscreen agenda section: its bucket, its records, and the dates of the heading ("28 okt–1 nov"). */
export type DatedAgendaSection = {
  group: AgendaBucket;
  items: WorkItemRecord[];
  /** Absent for "undated" and when a section has no dates to show. */
  range?: string;
};

function startOfDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function addDays(date: Date, days: number): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() + days);
}

/**
 * The Monday that starts the week of `today`, and the Mondays after the next two weeks. Both are
 * local midnights; `today` must already be a start of day.
 */
function weekBounds(today: Date) {
  const monday = addDays(today, -((today.getDay() + 6) % 7));
  return { nextMonday: addDays(monday, 7), weekAfter: addDays(monday, 14) };
}

/**
 * The fullscreen agenda group of one record at `now`. The server's "overdue" and "today" win; a
 * record the server left ungrouped is overdue when its due instant has passed. Records with a
 * due date before today (only "scheduled later" records can have one) are listed as later.
 */
export function agendaBucket(item: WorkItemRecord, now: Date): AgendaBucket {
  if (item.agenda_group === "overdue") return "overdue";
  if (item.agenda_group === "today") return "today";
  if (!item.due_at) return "undated";
  const due = new Date(item.due_at);
  if (!item.agenda_group && due < now) return "overdue";
  const day = startOfDay(due);
  const today = startOfDay(now);
  if (day < today) return "later";
  if (day.getTime() === today.getTime()) return "today";
  const { nextMonday, weekAfter } = weekBounds(today);
  if (day < nextMonday) return "thisWeek";
  if (day < weekAfter) return "nextWeek";
  return "later";
}

/** A date range as the agenda shows it: "28 okt–1 nov", or one date when both ends are the same day. */
function formatRange(start: Date, end: Date, locale: string): string {
  const format = new Intl.DateTimeFormat(locale, {
    day: "numeric",
    month: "short",
  });
  // sv-SE abbreviates with a period ("28 okt."); the heading drops it.
  const short = (date: Date) => format.format(date).replace(/\.$/, "");
  return start.getTime() === end.getTime()
    ? short(start)
    : `${short(start)}–${short(end)}`;
}

/**
 * Groups the agenda by bucket, in the order the agenda shows them. A bucket with no records is left
 * out. "today" and the two week buckets carry their calendar span; "overdue" and "later" carry the
 * span of their own due dates.
 */
export function agendaSections(
  items: WorkItemRecord[],
  now: Date,
  locale: string,
): DatedAgendaSection[] {
  const today = startOfDay(now);
  const { nextMonday, weekAfter } = weekBounds(today);
  const buckets = new Map<AgendaBucket, WorkItemRecord[]>();
  for (const item of items) {
    const bucket = agendaBucket(item, now);
    buckets.set(bucket, [...(buckets.get(bucket) ?? []), item]);
  }
  // Idag before Försenade, the order the inline card (01) already reads.
  const order: AgendaBucket[] = [
    "today",
    "overdue",
    "thisWeek",
    "nextWeek",
    "later",
    "undated",
  ];
  return order.flatMap((group) => {
    const members = buckets.get(group);
    if (!members?.length) return [];
    const range = agendaRange(
      group,
      members,
      today,
      nextMonday,
      weekAfter,
      locale,
    );
    return [{ group, items: members, range }];
  });
}

function agendaRange(
  group: AgendaBucket,
  members: WorkItemRecord[],
  today: Date,
  nextMonday: Date,
  weekAfter: Date,
  locale: string,
): string | undefined {
  if (group === "undated") return undefined;
  if (group === "today") return formatRange(today, today, locale);
  if (group === "thisWeek")
    return formatRange(today, addDays(nextMonday, -1), locale);
  if (group === "nextWeek")
    return formatRange(nextMonday, addDays(weekAfter, -1), locale);
  const days = members.flatMap((item) =>
    item.due_at ? [startOfDay(new Date(item.due_at)).getTime()] : [],
  );
  if (!days.length) return undefined;
  return formatRange(
    new Date(Math.min(...days)),
    new Date(Math.max(...days)),
    locale,
  );
}

/**
 * The due instant a morning triage move gives an overdue Task: 23:59 in the owner zone on today, tomorrow, or on the
 * Monday that starts next week (the "Next week" bucket's first day), counted on the owner calendar the dates are
 * shown in, whatever the browser's own zone is. The instant is an ISO string.
 */
export function triageDueAt(
  now: Date,
  target: "today" | "tomorrow" | "nextWeek",
): string {
  const days =
    target === "today"
      ? 0
      : target === "tomorrow"
        ? 1
        : ownerDaysToNextMonday(now);
  return ownerEndOfDay(ownerDayPlus(now, days));
}

/**
 * What an inline card's foot says it leaves out: every row of the view the foot opens, minus the rows the
 * card shows. One count for both feet, "Öppna Agenda · 7 fler" (10 − 3) and "Öppna Status · 10 fler" (13 − 3).
 */
export function hiddenRows(target: number, shown: number): number {
  return Math.max(0, target - shown);
}

/**
 * The frame a record opens: a Task or a Project. Other kinds (Domain, Process, Step, Action) are
 * shown without navigation, because the app has no frame for them.
 */
export function frameFor(item: WorkItemRecord): WorkFrame | undefined {
  if (item.kind === "task") return { kind: "task", id: item.id };
  if (item.kind === "project") return { kind: "project", id: item.id };
  // A Step opens its Task, where it is listed and checked.
  if (item.kind === "step" && item.task_id)
    return { kind: "task", id: item.task_id };
  return undefined;
}

/**
 * A Status column (or the phone's section) in the order it shows: by due date, so the overdue come
 * first and the oldest first, the undated last in the server's order; a column the user has ordered (`manually_ordered`)
 * keeps the server's order, which is the user's. Infinity − Infinity is NaN, which sort reads as equal.
 */
export function shownOrder(
  page: WorkBoardPage,
  status: string,
  items: WorkItemRecord[],
): WorkItemRecord[] {
  const at = (item: WorkItemRecord) =>
    item.due_at ? Date.parse(item.due_at) : Infinity;
  return page.manually_ordered?.includes(status)
    ? items
    : [...items].sort((a, b) => at(a) - at(b));
}

/**
 * Status's list order for Steps: a Step whose Task is in the same list stands right after it (after the
 * Task's earlier Steps), in their order; a Step whose Task is not there keeps its place. The Tasks keep their order.
 */
export function nestSteps(items: WorkItemRecord[]): WorkItemRecord[] {
  const tasks = new Set(
    items.flatMap((i) => (i.kind === "task" ? [i.id] : [])),
  );
  const nested = (i: WorkItemRecord) =>
    i.kind === "step" && !!i.task_id && tasks.has(i.task_id);
  return items.flatMap((item) =>
    nested(item)
      ? []
      : item.kind === "task"
        ? [item, ...items.filter((s) => nested(s) && s.task_id === item.id)]
        : [item],
  );
}

/**
 * A title or search text as the server compares them (`fold_text`): NFKC, lower case, then ß as ss, a final sigma as
 * a plain one and a dotted i as i. The board's search holds the loaded cards to the same match the server made.
 */
export function foldSearchText(text: string): string {
  return text
    .normalize("NFKC")
    .toLowerCase()
    .replaceAll("\u00df", "ss")
    .replaceAll("\u03c2", "\u03c3")
    .replaceAll("i\u0307", "i");
}
