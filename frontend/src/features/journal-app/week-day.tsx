import { useState } from "react";
import { formatDayHeading } from "./dates";
import { DaySummary, hasDaySummary } from "./day-summary";
import { DoneSection } from "./done-section";
import { EntryRow } from "./entry-row";
import type { JournalLabels } from "./labels";
import type { JournalDay } from "./transport";
import { isQueued, isStandInId } from "./use-queued-records";

/** A day of the week list shows this many entries; "Show all" opens the rest, as the day card does. */
const weekEntryLimit = 3;

/**
 * One day in the week list: its heading, the day's summary when it has one, its entries as the day's rows
 * (each opens the entry), and «Gjort» folded as in the day view. A day with neither summary nor entries says so in one
 * muted line. «Gjort» keeps its own fold per day.
 */
export function WeekDay({
  day,
  today,
  labels: t,
  queuedIds,
  onOpen,
}: {
  day: JournalDay;
  today: string;
  labels: JournalLabels;
  queuedIds: ReadonlySet<string>;
  onOpen: (id: string) => void;
}) {
  const [doneOpen, setDoneOpen] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const shown = showAll ? day.entries : day.entries.slice(0, weekEntryLimit);
  const written = day.entries.length > 0 || hasDaySummary(day.summary);
  return (
    <section
      className="journal-week-day"
      aria-labelledby={`week-day-${day.journal_date}`}
    >
      <h3 id={`week-day-${day.journal_date}`}>
        {formatDayHeading(day.journal_date, t.dateLocale, today)}
      </h3>
      <DaySummary day={day} fullscreen labels={t} />
      {!written && <p className="journal-empty">{t.weekDayEmpty}</p>}
      {shown.length > 0 && (
        <ul className="journal-timeline">
          {shown.map((entry) => (
            <EntryRow
              key={entry.id}
              entry={entry}
              labels={t}
              queued={isQueued(queuedIds, entry.id)}
              // A note still in the outbox has no entry on the server to open yet.
              onOpen={
                isStandInId(entry.id) ? undefined : () => onOpen(entry.id)
              }
            />
          ))}
        </ul>
      )}
      {!showAll && day.entries.length > weekEntryLimit && (
        <p className="journal-list-more">
          <button
            type="button"
            className="sk-more"
            onClick={() => setShowAll(true)}
          >
            {t.showAllEntries(day.entries.length)}
          </button>
        </p>
      )}
      {day.done && (
        <DoneSection
          done={day.done}
          labels={t}
          level="h4"
          open={doneOpen}
          onToggle={() => setDoneOpen((open) => !open)}
        />
      )}
    </section>
  );
}
