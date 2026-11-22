import { formatDayHeading, formatLongDate, formatTime } from "./dates";
import { doneCountLine } from "./done-section";
import type { JournalLabels } from "./labels";
import type { JournalDay } from "./transport";
import { summaryRest } from "./entry-card";
import { OpenLink } from "../mcp-apps/ui/open-link";
import { EmptyState } from "../mcp-apps/ui/states";
import "./journal.css";
import "./day-glance.css";

/** Touch target for the one action (44 px, HIG and WCAG 2.5.5). */
const touchStyle = { minHeight: "44px" };
/** The glance lists at most this many entries; the action opens the rest. */
const glanceEntryLimit = 3;
/** While the host answers the fullscreen request a second press does nothing. */
const ignore = () => undefined;

/** The entry whose text the wide card shows: the latest by time among those shown (the later one when times tie). */
function latestEntry(entries: JournalDay["entries"]) {
  let latest: JournalDay["entries"][number] | undefined;
  for (const entry of entries) {
    if (
      latest === undefined ||
      (entry.occurred_at ?? "") >= (latest.occurred_at ?? "")
    ) {
      latest = entry;
    }
  }
  return latest;
}

/**
 * Inline day glance, shown inline: the weekday and date, the day's overview (at most three lines), the number of
 * entries as one muted line, the first entries (each a button that opens that entry, at most three; in a card 37.5rem
 * wide or more the latest also shows the first two lines of its text), a "Review N drafts" button when drafts wait,
 * what was done on the day as one muted count line («Gjort · 1 uppgift · 1 steg», read-only; the fold with its rows is
 * in the day view), and the card's one link (`OpenLink`, "Öppna Dagbok ›", with "· N till" for the entries the rows
 * leave out). A day with nothing written and no summary is the family's empty state (one sentence and what to say to
 * Claude) instead of a count of zero. The link asks the host for fullscreen when it is offered, otherwise it expands
 * the day inline. Zero drafts are not mentioned. The glance reads nothing and writes nothing.
 */
export function DayGlance({
  day,
  today,
  draftCount,
  labels: t,
  onOpen,
  onOpenEntry,
  onReviewDrafts,
  onTellClaude,
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
  /** Sends the empty day's example to Claude; absent where the host offers no messages (the example is then shown as text). */
  onTellClaude?: (text?: string) => void;
  /** True while the host answers the fullscreen request; the button is busy and cannot be pressed. */
  opening?: boolean;
}) {
  const overview = day.summary.content?.overview?.trim() || undefined;
  const shown = day.entries.slice(0, glanceEntryLimit);
  const hidden = day.entries.length - shown.length;
  const excerptEntry = latestEntry(shown);
  const empty = day.entries.length === 0;
  const doneLine = day.done ? doneCountLine(day.done, t) : "";
  const isToday = day.journal_date === today;
  // Nothing written and no summary: the day says so, however much was done.
  const blank = empty && !overview;
  // What the empty day says to Claude: today's own message, or the day it is about.
  const dayMessage = isToday
    ? t.tellClaudeMessage
    : t.tellClaudeDayMessage(formatLongDate(day.journal_date, t.dateLocale));
  return (
    <section className="sidekick-journal" aria-label={t.title}>
      <article className="journal-card sk-card">
        <h1 className="sk-eyebrow">{t.title}</h1>
        <h2 className="sk-card__title">
          {formatDayHeading(day.journal_date, t.dateLocale, today)}
        </h2>
        {/* With entries, no "no summary" line: the entries are the content of the glance. A day with nothing at all is
            the family's empty state, as the day view has it: the sentence and what to say to Claude; no line counts
            zero entries. */}
        {overview ? (
          <p className="journal-summary journal-card-summary">{overview}</p>
        ) : (
          blank && (
            <EmptyState
              title={isToday ? t.noEntriesToday : t.noEntries}
              ask={{
                locale: t.dateLocale,
                example: dayMessage,
                onSend: onTellClaude
                  ? () => onTellClaude(dayMessage)
                  : undefined,
              }}
            />
          )
        )}
        {!empty && (
          <p className="journal-muted">
            {t.glanceEntries(day.entries.length, day.next_cursor !== null)}
          </p>
        )}
        {shown.length > 0 && (
          <ul className="journal-glance-entries">
            {shown.map((entry) => {
              const excerpt =
                entry === excerptEntry
                  ? summaryRest(entry.title, entry.summary)
                  : undefined;
              return (
                <li key={entry.id} data-sk-row>
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
                    <span className="journal-glance-text">
                      <span className="journal-glance-title">
                        {entry.title}
                      </span>
                      {excerpt && (
                        <span className="journal-glance-excerpt">
                          {excerpt}
                        </span>
                      )}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
        {doneLine && (
          <p className="journal-muted journal-glance-done">
            {t.done} · {doneLine}
          </p>
        )}
        {draftCount !== undefined && draftCount > 0 && (
          <div className="journal-actions sk-card__actions">
            <button
              type="button"
              className="sk-btn--secondary"
              onClick={onReviewDrafts}
              style={touchStyle}
            >
              {t.reviewDrafts(draftCount)}
            </button>
          </div>
        )}
        <OpenLink
          label={opening ? t.cardOpening : t.glanceOpen}
          more={
            hidden > 0 && !opening
              ? t.glanceMore(hidden, day.next_cursor !== null)
              : undefined
          }
          onOpen={opening ? ignore : onOpen}
        />
      </article>
    </section>
  );
}
