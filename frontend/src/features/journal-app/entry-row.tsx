import { ChevronRightIcon } from "../mcp-apps/ui/icons";
import { ownerToday } from "../mcp-apps/app-timezone";
import { TagChips } from "../mcp-apps/ui/tags";
import type { TagOption } from "../mcp-apps/ui/tag-vocabulary";
import { formatShortDateWithYear, formatTime } from "./dates";
import { linkName, summaryRest } from "./entry-card";
import type { JournalLabels } from "./labels";
import type { JournalEntry } from "./transport";
import { useWideFrame } from "./use-wide-frame";
import "./journal.css";

/** What one row shows of an entry. The link fields are optional: a missing count is not shown. */
export type EntryRowData = Pick<
  JournalEntry,
  "id" | "source_id" | "title" | "summary" | "occurred_at"
> &
  Partial<
    Pick<
      JournalEntry,
      | "contact_ids"
      | "task_ids"
      | "archived"
      | "links"
      | "tags"
      | "journal_date"
    >
  >;

export type EntryRowProps = {
  entry: EntryRowData;
  labels: JournalLabels;
  /** Opens the entry. Without it the row is plain content and shows no chevron. */
  onOpen?: () => void;
  /** The tag vocabulary, so a tag reads by its label; without it by its slug. */
  tagVocabulary?: readonly TagOption[];
  /** The row leads with the entry's day instead of its time, for a list that spans days. */
  dated?: boolean;
};

/** How many linked names the meta line names; the rest are counted. */
const ROW_LINK_LIMIT = 2;
/** The tags a row names before it counts the rest: two on a phone, four where the frame is wide. */
const ROW_TAGS_NARROW = 2;
const ROW_TAGS_WIDE = 4;

/**
 * One Journal entry in a day's timeline (designsystem §3, Anteckningsrad): a row with no frame, no surface and no
 * hairlines. The title comes first, then the muted meta "12:30 · Anna Andersson · 1 uppgift" and a two-line
 * excerpt; the entry's tags close the meta line. The chevron sits in the right column on the title's line. The whole row opens the entry;
 * the original text is read in the entry view.
 */
export function EntryRow({
  entry,
  labels: t,
  onOpen,
  tagVocabulary,
  dated = false,
}: EntryRowProps) {
  const wide = useWideFrame();
  const time =
    dated && entry.journal_date ? (
      <time dateTime={entry.journal_date}>
        {formatShortDateWithYear(
          entry.journal_date,
          t.dateLocale,
          ownerToday(),
        )}
      </time>
    ) : entry.occurred_at ? (
      <time dateTime={entry.occurred_at}>
        {formatTime(entry.occurred_at, t.dateLocale)}
      </time>
    ) : undefined;
  const meta = metaLine(entry, t);
  const tags = entry.tags ?? [];
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
      {time || meta || tags.length > 0 ? (
        <span className="journal-entry-meta">
          {time || meta ? (
            <span className="sk-row-meta">
              {time}
              {time && meta ? " · " : null}
              {meta}
            </span>
          ) : null}
          {/* A few tags close the meta line; the text before them gives way first (tags.css). */}
          <TagChips
            tags={tags}
            known={tagVocabulary}
            max={wide ? ROW_TAGS_WIDE : ROW_TAGS_NARROW}
            locale={t.dateLocale}
          />
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
