import { useContext } from "react";
import { RepeatIcon } from "../../mcp-apps/ui/icons";
import { TagChips } from "../../mcp-apps/ui/tags";
import { relativeDue, workDate, type DueTone } from "../../mcp-apps/ui/due";
import { taskPlaceLabelsFor } from "../tasks/task-place-labels";
import type { WorkItemRecord } from "../transport/transport";
import { workKindLabel, workStatusLabel, type WorkLabels } from "./labels";
import { KnownTags } from "./work-tags";

/**
 * The status in words for a Task in progress or blocked; `todo` and a done Task get none: the ring says done or not
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
 * The time of a row: how late it is when overdue, else the date (a short date, or the `today` word). It starts the meta line, so
 * it starts with a capital, as every line of the app does and as a Contact's or Project's Task rows (TaskDue) write it:
 * The due word, then the status.
 * None for a done or cancelled record, and none under `today` for a Task due today, as the group says it; an overdue
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
 * first, then the status in words, the kind (not for a Task), the "High" marker, two tags and "+N", and the Project
 * last ("9 dagar försenad · Pågår [kund] [viktig] +1 · Renovering av köket"; a pill needs no dot before it). The status is left out in Status (`inStatus`), whose sections are the
 * statuses. A Project there stands in the Projekt section, which names its kind, so it shows its own status instead
 * (`active`, `paused`): a Project's status is not a Task status. The Project stands in both lists, whole or not at all: when the line has no room for the
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
  /** The agenda group of the row; the meta never repeats it (the `today` word under the group heading). */
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
  // A finished Task has no use for a warning: "High" would draw the eye to what is already done.
  const marked =
    item.kind === "task" &&
    item.priority === "high" &&
    item.status !== "completed" &&
    item.status !== "cancelled";
  const due = rowDue(item, now, t.dateLocale, group);
  // A Task that repeats says so after its time (the repeat glyph and the rule in words).
  const repeat =
    item.kind === "task" && item.recurrence
      ? taskPlaceLabelsFor(t.dateLocale).repeatsShort(item.recurrence)
      : null;
  const project = item.project_title;
  const tags = item.tags ?? [];
  const known = useContext(KnownTags);
  if (
    !status &&
    !kind &&
    !project &&
    !marked &&
    !due &&
    !repeat &&
    tags.length === 0
  )
    return null;
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
      {/* Two tags and "+N" before the Project: they stand whole or not at all, and the Project gives way first. */}
      <TagChips tags={tags} known={known} max={2} locale={t.dateLocale} />
      {project ? (
        <span className="work-card-project" title={project}>
          {project}
        </span>
      ) : null}
    </p>
  );
}
