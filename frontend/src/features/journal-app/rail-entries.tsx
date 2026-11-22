import { useRecordRow } from "../mcp-apps/ui/split-layout";
import { formatTime } from "./dates";
import type { JournalLabels } from "./labels";
import type { JournalEntry } from "./transport";
import { isQueued, isStandInId } from "./use-queued-records";
import "./day-read.css";

/** One entry as a compact row: its title and, at the right, its time. The entry open beside the list is drawn chosen. */
function RailRow({
  entry,
  labels: t,
  queued,
  onOpen,
}: {
  entry: JournalEntry;
  labels: JournalLabels;
  queued: boolean;
  onOpen?: () => void;
}) {
  const recordRow = useRecordRow(
    onOpen ? { room: "journal", view: "entry", id: entry.id } : undefined,
  );
  const inside = (
    <>
      <span className="journal-rail-title">{entry.title}</span>
      {queued && <span className="sk-queued">{t.queued}</span>}
      {entry.occurred_at ? (
        <time className="journal-rail-time" dateTime={entry.occurred_at}>
          {formatTime(entry.occurred_at, t.dateLocale)}
        </time>
      ) : null}
    </>
  );
  return (
    <li
      className="journal-rail-row"
      data-sk-row={onOpen ? "" : undefined}
      {...recordRow}
    >
      {onOpen ? (
        <button type="button" className="journal-rail-card" onClick={onOpen}>
          {inside}
        </button>
      ) : (
        <div className="journal-rail-card">{inside}</div>
      )}
    </li>
  );
}

/**
 * The day's entries under the calendar in the list pane (desktop spec 3.2): a section named "Anteckningar" with one
 * compact row per entry. A row opens the entry beside the list; the day itself is read in the pane beside it.
 */
export function RailEntries({
  entries,
  labels: t,
  queuedIds,
  onOpen,
}: {
  entries: readonly JournalEntry[];
  labels: JournalLabels;
  queuedIds: ReadonlySet<string>;
  onOpen: (id: string) => void;
}) {
  if (entries.length === 0) return null;
  return (
    <>
      <h3>{t.entries}</h3>
      <ul className="journal-rail-list">
        {entries.map((entry) => (
          <RailRow
            key={entry.id}
            entry={entry}
            labels={t}
            queued={isQueued(queuedIds, entry.id)}
            onOpen={isStandInId(entry.id) ? undefined : () => onOpen(entry.id)}
          />
        ))}
      </ul>
    </>
  );
}
