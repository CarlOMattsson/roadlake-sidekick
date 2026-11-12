import { ChevronRightIcon } from "../mcp-apps/ui/icons";
import { formatTime } from "./dates";
import { linkName, summaryRest } from "./entry-card";
import type { JournalLabels } from "./labels";
import type { JournalEntry } from "./transport";
import "./journal.css";

/** What one row shows of an entry. The link fields are optional: a missing count is not shown. */
export type EntryRowData = Pick<
  JournalEntry,
  "id" | "source_id" | "title" | "summary" | "occurred_at"
> &
  Partial<
    Pick<JournalEntry, "contact_ids" | "task_ids" | "archived" | "links">
  >;

export type EntryRowProps = {
  entry: EntryRowData;
  labels: JournalLabels;
  /** Opens the entry. Without it the row is plain content and shows no chevron. */
  onOpen?: () => void;
};

/** How many linked names the meta line names; the rest are counted ("och 1 till"). */
const ROW_LINK_LIMIT = 2;

/**
 * One Journal entry in a day's timeline (designsystem §3, Anteckningsrad): a row with no frame, no surface and no
 * hairlines. The title comes first, then the muted meta "12:30 · Anna Andersson · 1 uppgift" and a two-line
 * excerpt. The chevron sits in the right column on the title's line. The whole row opens the entry;
 * the original text is read in the entry view.
 */
export function EntryRow({ entry, labels: t, onOpen }: EntryRowProps) {
  const time = entry.occurred_at ? (
    <time dateTime={entry.occurred_at}>
      {formatTime(entry.occurred_at, t.dateLocale)}
    </time>
  ) : undefined;
  const meta = metaLine(entry, t);
  const summary = summaryRest(entry.title, entry.summary);
  // Title first, then the meta line and the excerpt (designsystem §3, one row system). The chevron follows the
  // title in the markup, so the grid puts it in the right column on the title's line.
  const body = (
    <>
      <span className="sk-row-primary">{entry.title}</span>
      {onOpen ? (
        <span className="journal-entry-chevron">
          <ChevronRightIcon />
        </span>
      ) : null}
      {time || meta ? (
        <span className="journal-entry-meta">
          {time}
          {time && meta ? " · " : null}
          {meta}
        </span>
      ) : null}
      {summary ? (
        <span className="journal-entry-excerpt">{summary}</span>
      ) : null}
    </>
  );
  return (
    <li
      className="journal-entry-row"
      data-navigates={onOpen ? "true" : undefined}
    >
      {onOpen ? (
        <button type="button" className="journal-entry-card" onClick={onOpen}>
          {body}
        </button>
      ) : (
        <div className="journal-entry-card">{body}</div>
      )}
    </li>
  );
}

/**
 * The metadata after the time: the archived marker first, then the linked names ("Anna Andersson", from `links`) or,
 * from an older result without names, the contact count; then the Task count. Nonzero parts only; undefined when
 * there is nothing to show.
 */
function metaLine(entry: EntryRowData, t: JournalLabels): string | undefined {
  const parts: string[] = [];
  if (entry.archived) parts.push(t.archived);
  if (entry.links) {
    const names = entry.links
      .slice(0, ROW_LINK_LIMIT)
      .map((link) => linkName(link, t));
    const rest = entry.links.length - names.length;
    if (names.length > 0)
      parts.push(
        rest > 0
          ? `${names.join(", ")} ${t.and} ${t.andMoreCount(rest)}`
          : names.join(", "),
      );
  } else {
    const contacts = entry.contact_ids?.length ?? 0;
    if (contacts > 0) parts.push(t.cardContacts(contacts));
  }
  const tasks = entry.task_ids?.length ?? 0;
  if (tasks > 0) parts.push(t.cardTasks(tasks));
  return parts.length > 0 ? parts.join(" · ") : undefined;
}
