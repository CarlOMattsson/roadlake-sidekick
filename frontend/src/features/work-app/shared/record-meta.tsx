import { RepeatIcon } from "../../mcp-apps/ui/icons";
import { relativeDue, workDate, type DueTone } from "../../mcp-apps/ui/due";
import { taskPlaceLabelsFor } from "../tasks/task-place-labels";
import type { WorkItemRecord } from "../transport/transport";
import { workKindLabel, workStatusLabel, type WorkLabels } from "./labels";

/**
 * The status in words for a Task in progress or blocked; "Att göra" and a done Task get none: the ring says done or not
 * done. `word` names a status (the work labels, or the inline labels).
 */
export function rowStatus(
  item: WorkItemRecord,
  word: (status: string) => string,
): string | null {
  return item.kind === "task" &&
    (item.status === "in_progress" || item.status === "blocked")
    ? word(item.status)
    : null;
}

/**
 * The time of a row: "9 dagar försenad" when overdue, else the date ("Fre 6 nov", "Idag"). It starts the meta line, so
 * it starts with a capital, as every line of the app does and as a Contact's or Project's Task rows (TaskDue) write it:
 * "Idag · Pågår", "Today · In progress".
 * None for a done or cancelled record, and none under "Idag" for a Task due today, as the group says it; an overdue
 * time always stands.
 */
export function rowDue(
  item: WorkItemRecord,
  now: Date,
  locale: string,
  group?: string | null,
): { text: string; tone: DueTone; at: string } | null {
  if (
    !item.due_at ||
    item.status === "completed" ||
    item.status === "cancelled"
  )
    return null;
  const due = relativeDue(
    item.due_at,
    now,
    locale.startsWith("sv") ? "sv" : "en",
  );
  if (!due.text || (group === "today" && due.tone === "today")) return null;
  return {
    text:
      due.tone === "overdue" ? due.text : workDate(item.due_at, now, locale),
    tone: due.tone,
    at: item.due_at,
  };
}

/**
 * The meta of a record row, one builder for the Agenda, Status and the inline cards: one line, the time
 * first, then the status in words, the kind (not for a Task), the "High" marker and the Project last ("9 dagar
 * försenad · Pågår · Renovering av köket"). The status is left out in Status (`inStatus`), whose sections are the
 * statuses. A Project there stands in the Projekt section, which names its kind, so it shows its own status instead
 * ("Aktivt", "Pausat"): a Project's status is not a Task status. The Project stands in both lists, whole or not at all: when the line has no room for the
 * whole name, CSS leaves it and its "·" out, so the row keeps one meta line and nothing is cut; its full name is the
 * text (screen readers) and the title. Each
 * part is a flex item and the "·" before it is drawn in CSS, so a wrapped line never starts or ends with one. The
 * inline cards take the time and the status only (`inlineMeta`).
 */
export function RecordMeta({
  item,
  labels: t,
  now,
  group,
  inStatus,
}: {
  item: WorkItemRecord;
  labels: WorkLabels;
  now: Date;
  /** The agenda group of the row; the meta never repeats it ("idag" under "Idag, …"). */
  group?: string | null;
  inStatus?: boolean;
}) {
  const projectInStatus = inStatus && item.kind === "project";
  const status = projectInStatus
    ? workStatusLabel(t, item.status)
    : inStatus
      ? null
      : rowStatus(item, (s) => workStatusLabel(t, s));
  const kind =
    item.kind === "task" || projectInStatus
      ? null
      : workKindLabel(t, item.kind);
  const marked = item.kind === "task" && item.priority === "high";
  const due = rowDue(item, now, t.dateLocale, group);
  // A Task that repeats says so after its time: "↻ varje månad".
  const repeat =
    item.kind === "task" && item.recurrence
      ? taskPlaceLabelsFor(t.dateLocale).repeatsShort(item.recurrence)
      : null;
  const project = item.project_title;
  if (!status && !kind && !project && !marked && !due && !repeat) return null;
  return (
    <p className="work-card-meta">
      {due ? (
        <span className="work-card-due">
          <time
            dateTime={due.at}
            title={workDate(due.at, now, t.dateLocale, { relative: false })}
            data-tone={due.tone}
          >
            {due.text}
          </time>
        </span>
      ) : null}
      {repeat ? (
        <span className="work-card-repeat">
          <RepeatIcon />
          {repeat}
        </span>
      ) : null}
      {status ? <span className="work-card-status">{status}</span> : null}
      {kind ? <span className="work-card-kind">{kind}</span> : null}
      {marked ? (
        <span className="work-card-priority" data-priority="high">
          {t.priorityLevel.high}
        </span>
      ) : null}
      {project ? (
        <span className="work-card-project" title={project}>
          {project}
        </span>
      ) : null}
    </p>
  );
}
