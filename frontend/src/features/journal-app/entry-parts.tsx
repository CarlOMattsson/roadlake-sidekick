import type { ComponentProps } from "react";
import { ownerToday } from "../mcp-apps/app-timezone";
import { PenIcon, PlusIcon } from "../mcp-apps/ui/icons";
import { formatDayHeading, formatTime } from "./dates";
import { EntryLinks } from "./entry-links";
import { EntryTasks } from "./entry-tasks";
import type { JournalLabels } from "./labels";
import type { JournalEntry, JournalTransport, WriteFailure } from "./transport";

/** The Projects and Contacts that are only counted (an older server names none), as the view always showed them. */
export type LinkCount = { label: string; count: number };

/**
 * What the entry is linked to: the "Linked" heading, the named links (each with a × that asks before it removes the
 * link, once `removable`), the Tasks by title and the counts of a record that names no links. The inline card shows
 * the links as text only, so the entry's own view is where a link is removed. EntryLinks is drawn whenever the entry
 * carries its links, so its Undo line stays after the last link is removed.
 */
export function EntryLinked({
  entry,
  labels: t,
  counts,
  transport,
  ...links
}: {
  entry: JournalEntry;
  labels: JournalLabels;
  counts: LinkCount[];
  transport: JournalTransport;
} & Pick<
  ComponentProps<typeof EntryLinks>,
  | "receipt"
  | "onOpenContact"
  | "onOpenProject"
  | "onChanged"
  | "onEmptied"
  | "onConflict"
  | "removable"
> & { onOpenTask?: (id: string) => void }) {
  const { onOpenTask, ...rest } = links;
  return (
    <>
      <h3>{t.linked}</h3>
      {entry.links !== undefined && (
        <EntryLinks entry={entry} labels={t} transport={transport} {...rest} />
      )}
      <EntryTasks
        taskIds={entry.task_ids ?? []}
        labels={t}
        getTaskTitle={transport.getTaskTitle}
        onOpenTask={onOpenTask}
      />
      {counts.length > 0 && (
        <ul className="journal-list">
          {counts.map((link) => (
            <li key={link.label}>
              {link.label}: {link.count}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

/**
 * The day the entry belongs to with its weekday, then its time and, while its write waits in the phone's outbox, the
 * word for that: "Friday 20 November · 21:40". Quiet, one line; the tags follow on the same line when there is room.
 */
export function EntryWhen({
  entry,
  labels: t,
  queued,
}: {
  entry: JournalEntry;
  labels: JournalLabels;
  queued: boolean;
}) {
  return (
    <p>
      {formatDayHeading(entry.journal_date, t.dateLocale, ownerToday())}
      {entry.occurred_at && (
        <>
          {" · "}
          <time dateTime={entry.occurred_at}>
            {formatTime(entry.occurred_at, t.dateLocale)}
          </time>
        </>
      )}
      {queued && (
        <>
          {" · "}
          <span className="sk-queued">{t.queued}</span>
        </>
      )}
    </p>
  );
}

/** What a failed tag write says; the same causes as every write. */
export function tagFailureText(how: WriteFailure, t: JournalLabels): string {
  if (how === "conflict") return t.tagsConflict;
  if (how === "invalid") return t.tagsInvalid;
  if (how === "forbidden") return t.forbiddenWrite;
  return t.tagsFailed;
}

/** What a refused edit says; a failed save is the editor's own row with its retry, so it says nothing here. */
export function editRefusalText(
  how: WriteFailure | undefined,
  t: JournalLabels,
): string | undefined {
  if (how === "conflict") return t.entryEditConflict;
  if (how === "invalid") return t.entryInvalid;
  if (how === "forbidden") return t.forbiddenWrite;
  return undefined;
}

/**
 * The pen ("Change the entry", key E) and the plus ("Add text") as icon buttons, for the detail's head beside ⋯. A
 * button is drawn only when the transport can write that change.
 */
export function EntryChangeButtons({
  labels: t,
  canEdit,
  canAppend,
  onEdit,
  onAppend,
}: {
  labels: JournalLabels;
  canEdit: boolean;
  canAppend: boolean;
  onEdit: () => void;
  onAppend: () => void;
}) {
  return (
    <>
      {canEdit && (
        <button
          type="button"
          className="sk-iconbtn"
          aria-label={t.editEntry}
          title={`${t.editEntry} (E)`}
          aria-keyshortcuts="e"
          onClick={onEdit}
        >
          <PenIcon />
        </button>
      )}
      {canAppend && (
        <button
          type="button"
          className="sk-iconbtn"
          aria-label={t.appendText}
          title={t.appendText}
          onClick={onAppend}
        >
          <PlusIcon />
        </button>
      )}
    </>
  );
}
