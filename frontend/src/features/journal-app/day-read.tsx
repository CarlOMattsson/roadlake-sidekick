import type { ReactNode, RefObject } from "react";
import { SplitAside } from "../mcp-apps/ui/split-layout";
import { formatTime } from "./dates";
import { DayHeading } from "./day-heading";
import { DaySummary } from "./day-summary";
import { entryTextOf, useEntrySource } from "./entry-read";
import type { JournalLabels } from "./labels";
import type { JournalDay, JournalEntry, JournalTransport } from "./transport";
import { isQueued, isStandInId } from "./use-queued-records";
import "./journal.css";
import "./day-read.css";

/**
 * What a room puts beside its list in a wide frame when no entry is open (SplitAside). The aside is drawn in the shell,
 * outside the room's own root, so the room's rules reach it only through the root class it carries here.
 */
export function JournalAside({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return (
    <SplitAside>
      <div
        className={
          className ? `sidekick-journal ${className}` : "sidekick-journal"
        }
      >
        {children}
      </div>
    </SplitAside>
  );
}

/**
 * One entry of the day in full: its title with the time on the same baseline, then the owner's own text in the reading
 * type (entry-read.tsx decides which text is hers: Claude's summary is not shown here). The title opens the entry.
 */
function DayReadEntry({
  entry,
  transport,
  labels: t,
  queued,
  onOpen,
}: {
  entry: JournalEntry;
  transport: JournalTransport;
  labels: JournalLabels;
  queued: boolean;
  onOpen?: () => void;
}) {
  const text = entryTextOf(entry, useEntrySource(transport, entry));
  return (
    <article className="journal-read__entry">
      <header className="journal-read__entry-head">
        <h3 className="journal-read__title">
          {onOpen ? (
            <button
              type="button"
              className="journal-read__title-link"
              onClick={onOpen}
            >
              {entry.title}
            </button>
          ) : (
            entry.title
          )}
        </h3>
        {queued && <span className="sk-queued">{t.queued}</span>}
        {entry.occurred_at ? (
          <time className="journal-read__time" dateTime={entry.occurred_at}>
            {formatTime(entry.occurred_at, t.dateLocale)}
          </time>
        ) : null}
      </header>
      {text.waiting && (
        <p className="journal-muted" role="status">
          {t.loading}
        </p>
      )}
      {text.main && <div className="journal-entry-text">{text.main}</div>}
    </article>
  );
}

/**
 * The day as it is read beside the list (desktop spec 3.2): the day's heading in the display size, the day's summary if
 * there is one, then every entry in full length one after the other with 48 between them. A day without entries shows
 * `empty` (its sentence and the ways to write) in their place.
 */
export function DayRead({
  day,
  heading,
  headingRef,
  transport,
  labels: t,
  queuedIds,
  onOpen,
  empty,
}: {
  day: JournalDay;
  /** The day's name ("Fredag 20 november"). */
  heading: string;
  /** The heading the view moves focus to after a move. */
  headingRef: RefObject<HTMLHeadingElement | null>;
  transport: JournalTransport;
  labels: JournalLabels;
  queuedIds: ReadonlySet<string>;
  onOpen: (id: string) => void;
  empty: ReactNode;
}) {
  return (
    <JournalAside className="journal-read">
      <DayHeading
        ref={headingRef}
        className="journal-read__heading"
        long={heading}
        short={heading}
      />
      <DaySummary day={day} fullscreen labels={t} />
      {day.entries.length === 0
        ? empty
        : day.entries.map((entry) => (
            <DayReadEntry
              key={entry.id}
              entry={entry}
              transport={transport}
              labels={t}
              queued={isQueued(queuedIds, entry.id)}
              onOpen={
                isStandInId(entry.id) ? undefined : () => onOpen(entry.id)
              }
            />
          ))}
      {day.next_cursor && <p role="status">{t.moreEntries}</p>}
    </JournalAside>
  );
}
