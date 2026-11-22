import { useState } from "react";
import { formatDayHeading } from "./dates";
import { DaySummary, hasDaySummary } from "./day-summary";
import { DoneSection } from "./done-section";
import { EntryRow } from "./entry-row";
import type { TagOption } from "../mcp-apps/ui/tag-vocabulary";
import { ChevronRightIcon } from "../mcp-apps/ui/icons";
import type { JournalLabels } from "./labels";
import type { JournalDay } from "./transport";
import { isQueued, isStandInId } from "./use-queued-records";
import "./week.css";

/** A day of the week list shows this many entries; "Show all" opens the rest, as the day card does. */
const weekEntryLimit = 3;

/**
 * A run of days with nothing written, as one quiet line: what it covers, then the way to write for the first of them
 * ("Inget skrivet mån–ons · Skriv för en dag ›").
 */
export function WeekGap({
  text,
  labels: t,
  onWrite,
}: {
  text: string;
  labels: JournalLabels;
  onWrite: () => void;
}) {
  return (
    <p className="sk-week-gap">
      <span>{text}</span>
      <span aria-hidden="true">·</span>
      <button
        type="button"
        className="sk-btn sk-btn--quiet sk-btn--compact"
        onClick={onWrite}
      >
        {t.weekGapWrite}
        <ChevronRightIcon />
      </button>
    </p>
  );
}

/**
 * One day in the week list: its heading, the day's summary when it has one, its entries as the day's rows, the same
 * rows as the day view (each opens the entry), and «Gjort» folded as in the day view. A day with only something done
 * says so in one muted line. «Gjort» keeps its own fold per day. Days with nothing at all are not drawn here: the
 * list folds them into a `WeekGap`.
 */
export function WeekDay({
  day,
  today,
  labels: t,
  queuedIds,
  tagVocabulary,
  onOpen,
}: {
  day: JournalDay;
  today: string;
  labels: JournalLabels;
  queuedIds: ReadonlySet<string>;
  tagVocabulary?: readonly TagOption[];
  onOpen: (id: string) => void;
}) {
  const [doneOpen, setDoneOpen] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const shown = showAll ? day.entries : day.entries.slice(0, weekEntryLimit);
  const written = day.entries.length > 0 || hasDaySummary(day.summary);
  return (
    <section
      className="sk-week-day"
      aria-labelledby={`week-day-${day.journal_date}`}
    >
      <h3 id={`week-day-${day.journal_date}`} className="sk-week-day__title">
        {formatDayHeading(day.journal_date, t.dateLocale, today)}
      </h3>
      <DaySummary day={day} fullscreen labels={t} />
      {!written && <p className="sk-week-day__empty">{t.weekDayEmpty}</p>}
      {shown.length > 0 && (
        <ul className="journal-timeline">
          {shown.map((entry) => (
            <EntryRow
              key={entry.id}
              entry={entry}
              labels={t}
              tagVocabulary={tagVocabulary}
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
