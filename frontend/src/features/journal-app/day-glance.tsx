import { formatDayHeading, formatTime } from "./dates";
import { doneCountLine } from "./done-section";
import type { JournalLabels } from "./labels";
import type { JournalDay } from "./transport";
import { CardFoot } from "../mcp-apps/ui/card";
import { ChevronRightIcon } from "../mcp-apps/ui/icons";
import "./journal.css";

/** Touch target for the one action (44 px, HIG and WCAG 2.5.5). */
const touchStyle = { minHeight: "44px" };
/** The glance lists at most this many entries; the action opens the rest. */
const glanceEntryLimit = 3;

/**
 * Inline day glance, shown inline: the weekday and date, the day's overview (at most three lines), the
 * first entries (each a button that opens that entry, at most three), the number of entries, a "Review N
 * drafts" button when drafts wait, what was done on the day as one muted count line («Gjort · 1 uppgift · 1 steg»,
 * read-only; the fold with its rows is in the day view), and one action. A day with nothing written and no summary
 * says so in one sentence instead of a count of zero. The action asks the host for fullscreen when it is offered,
 * otherwise it expands the day inline; with more than three entries it reads "Show all". Zero drafts are not
 * mentioned. The glance reads nothing and writes nothing.
 */
export function DayGlance({
  day,
  today,
  draftCount,
  labels: t,
  onOpen,
  onOpenEntry,
  onReviewDrafts,
  opening = false,
}: {
  day: JournalDay;
  /** Today, YYYY-MM-DD, so the heading can leave out the year of the current year. Passed in, never read here. */
  today: string;
  /**
   * Drafts awaiting review on this day. Absent while the read runs or when it failed, so the
   * glance never claims a count it does not know.
   */
  draftCount?: number;
  labels: JournalLabels;
  onOpen: () => void;
  /** Opens one entry of the day from its row. */
  onOpenEntry: (id: string) => void;
  /** Opens the day's drafts awaiting review in the app. */
  onReviewDrafts: () => void;
  /** True while the host answers the fullscreen request; the button is busy and cannot be pressed. */
  opening?: boolean;
}) {
  const overview = day.summary.content?.overview?.trim() || undefined;
  const shown = day.entries.slice(0, glanceEntryLimit);
  const more = day.entries.length > glanceEntryLimit;
  const empty = day.entries.length === 0;
  const doneLine = day.done ? doneCountLine(day.done, t) : "";
  return (
    <section className="sidekick-journal" aria-label={t.title}>
      <article className="journal-card sk-card">
        <h1 className="sk-eyebrow">{t.title}</h1>
        <h2 className="sk-card__title">
          {formatDayHeading(day.journal_date, t.dateLocale, today)}
        </h2>
        {/* With entries, no "no summary" line: the entries are the content of the glance. An empty day says it in one
            sentence, so no second line counts zero entries. */}
        {overview ? (
          <p className="journal-summary journal-card-summary">{overview}</p>
        ) : (
          empty && (
            <p className="journal-muted">
              {day.journal_date === today ? t.noEntriesToday : t.noEntries}
            </p>
          )
        )}
        {shown.length > 0 && (
          <ul className="journal-glance-entries">
            {shown.map((entry) => (
              <li key={entry.id}>
                <button
                  type="button"
                  className="sk-btn--quiet journal-glance-row"
                  onClick={() => onOpenEntry(entry.id)}
                  style={touchStyle}
                >
                  {entry.occurred_at && (
                    <time
                      className="journal-glance-time"
                      dateTime={entry.occurred_at}
                    >
                      {formatTime(entry.occurred_at, t.dateLocale)}
                    </time>
                  )}
                  <span className="journal-glance-title">{entry.title}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {!empty && (
          <p className="journal-muted">
            {t.glanceEntries(day.entries.length, day.next_cursor !== null)}
          </p>
        )}
        {doneLine && (
          <p className="journal-muted journal-glance-done">
            {t.done} · {doneLine}
          </p>
        )}
        <CardFoot>
          <div className="journal-actions sk-card__actions">
            <button
              type="button"
              className="sk-btn--open"
              onClick={onOpen}
              disabled={opening}
              aria-busy={opening || undefined}
            >
              {opening
                ? t.cardOpening
                : more
                  ? t.showAllEntries(day.entries.length)
                  : t.cardOpen}
              <ChevronRightIcon />
            </button>
            {draftCount !== undefined && draftCount > 0 && (
              <button
                type="button"
                className="sk-btn--secondary"
                onClick={onReviewDrafts}
                style={touchStyle}
              >
                {t.reviewDrafts(draftCount)}
              </button>
            )}
          </div>
        </CardFoot>
      </article>
    </section>
  );
}
