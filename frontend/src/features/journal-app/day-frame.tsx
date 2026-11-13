import { useEffect, useRef, useState } from "react";
import { formatDayHeading, formatLongDate, shiftDate } from "./dates";
import { DayEmpty } from "./day-empty";
import { useDayRefresh, useEntryDates } from "./day-frame-hooks";
import { DayHeading } from "./day-heading";
import { DayMoreButton, DayMorePanel, useDayMore } from "./day-more";
import { DayStrip, stripDays } from "./day-strip";
import { dayStripLabelsEn, dayStripLabelsSv } from "./day-strip-labels";
import { DayAddButton, DayAddPanel, useDayWrite } from "./day-write";
import { DoneSection } from "./done-section";
import { EntryTextForm } from "./entry-write";
import { EntryRow } from "./entry-row";
import { DaySummary, hasDaySummary } from "./day-summary";
import { DayTags, useDayTags } from "./day-tags";
import { isForbidden } from "./transport";
import type { JournalDay, JournalFrame } from "./transport";
import { useShortcuts } from "../mcp-apps/ui/shortcuts";
import { useMounted } from "../mcp-apps/ui/use-mounted";
import type { HostSettingsEntry } from "../mcp-apps/room-types";
import { ownerToday } from "../mcp-apps/app-timezone";
import { ErrorNotice } from "../mcp-apps/ui/states";
import type { FrameProps } from "./frame-props";

type DayFrameProps = FrameProps & {
  frame: Extract<JournalFrame, { kind: "day" }>;
  onChange: (next: JournalFrame) => void;
  onOpen: (frame: JournalFrame) => void;
  fullscreen: boolean;
  allEntries: boolean;
  refreshKey?: number;
  onTellClaude?: (text?: string) => void;
  /**
   * The last entry of the day view's ⋯: Control, or the host's own settings (the phone's "Inställningar"). Absent: no
   * such entry.
   */
  control?: HostSettingsEntry;
};

/** Inline, a day shows this many entries; "Show all" in the card opens the rest. */
const inlineEntryLimit = 3;

export function DayFrame({
  frame,
  onChange,
  transport,
  labels: t,
  moves,
  onOpen,
  fullscreen,
  allEntries,
  refreshKey,
  onTellClaude,
  control,
}: DayFrameProps) {
  const moreButton = useRef<HTMLButtonElement>(null);
  const addButton = useRef<HTMLButtonElement>(null);
  const more = useDayMore(t, fullscreen, control, moreButton);
  // «Gjort» is folded until the owner opens it; it stays open while she steps between days.
  const [doneOpen, setDoneOpen] = useState(false);
  const [phase, setPhase] = useState<
    "idle" | "loading" | "forbidden" | "error"
  >("idle");
  // What the failed read threw: the notice names the connection only when it may be that.
  const [cause, setCause] = useState<unknown>();
  const [target, setTarget] = useState<string>();
  // The day whose entries the owner expanded inline. Only that day stays expanded when moving on.
  const [expandedDate, setExpandedDate] = useState<string>();
  const heading = useRef<HTMLHeadingElement>(null);
  const { page } = frame;
  // The tags the day is filtered on; the choice is kept in the frame, so Back returns to the tagged list.
  const dayTags = useDayTags(transport, frame.tags, refreshKey);
  const mounted = useMounted();
  // The owner's today (the zone the day result names, else the declared one), never the device's.
  const today = ownerToday(page.owner_timezone);
  // A failed or forbidden read shows only the notice under the day the owner tried to open. The
  // previous day's entries are not shown under the new heading, and the strip follows that day.
  const failedDate =
    phase === "error" || phase === "forbidden" ? target : undefined;
  const shownDate = failedDate ?? page.journal_date;
  const dayStripLabels = t.dateLocale.startsWith("sv")
    ? dayStripLabelsSv
    : dayStripLabelsEn;
  const expanded =
    fullscreen || allEntries || expandedDate === page.journal_date;
  const shownEntries = expanded
    ? page.entries
    : page.entries.slice(0, inlineEntryLimit);
  useEffect(() => {
    if (moves > 0) heading.current?.focus();
  }, [moves]);
  useDayRefresh(refreshKey, mounted, {
    frame,
    loading: phase === "loading",
    transport,
    onChange,
  });

  // What an empty day says to Claude: today's own message, or the day it is about.
  const dayMessage =
    page.journal_date === today
      ? t.tellClaudeMessage
      : t.tellClaudeDayMessage(formatLongDate(page.journal_date, t.dateLocale));
  // A day with notes asks for more behind + in its title row, where the other rooms create:
  // the content starts with the day itself. A day without notes (also one with only a summary) keeps its whole button under its sentence.
  const tellMore =
    onTellClaude && !failedDate && page.entries.length > 0
      ? () =>
          onTellClaude(
            t.tellClaudeMoreMessage(
              page.journal_date === today
                ? undefined
                : formatLongDate(page.journal_date, t.dateLocale),
            ),
          )
      : undefined;
  const write = useDayWrite({
    frame,
    transport,
    onChange,
    mounted,
    today,
    failedDate,
    filtered: dayTags.filtered,
    onTellClaude,
    tellMore,
    dayMessage,
  });
  const { canWrite, composing, created, addOpen } = write;

  function go(date: string) {
    // One day read at a time, as the disabled step buttons allowed before.
    if (phase === "loading") return;
    setPhase("loading");
    write.clearCreated();
    setTarget(date);
    transport
      .getDay(date)
      .then((next: JournalDay) => {
        if (!mounted.current) return;
        setPhase("idle");
        onChange({ kind: "day", page: next });
      })
      .catch((error: unknown) => {
        if (!mounted.current) return;
        setCause(error);
        setPhase(isForbidden(error) ? "forbidden" : "error");
      });
  }

  const shownDays = stripDays(shownDate, today);
  const rangeFrom = shownDays[0];
  const rangeTo = shownDays[shownDays.length - 1];
  // The day the view has read is newer than the range read, so it decides its own dot.
  const daysWithEntries = useEntryDates(
    transport,
    rangeFrom,
    rangeTo,
    refreshKey,
  ).filter((date) => date !== page.journal_date);
  if (page.entries.length > 0) daysWithEntries.push(page.journal_date);

  // The summary section shows with a summary or a note about one; an empty summary is not shown.
  const summaryShown = hasDaySummary(page.summary);
  // What was done on the day (completed tasks and steps, and purchases, as the journal read returns them); an older server sends no `done`, and the section is then absent.
  // Keyed by the day: a kind shown in full is back to its first rows on the next day; the fold itself stays as it was.
  const done = page.done ? (
    <DoneSection
      key={page.journal_date}
      done={page.done}
      labels={t}
      open={doneOpen}
      onToggle={() => setDoneOpen((open) => !open)}
    />
  ) : null;

  // Design language 4.6: `[` and `]` step to the previous and next day, `t` to today.
  // Fullscreen only: an inline card has no shortcuts.
  useShortcuts(
    {
      "[": () => go(shiftDate(shownDate, -1)),
      "]": () => go(shiftDate(shownDate, 1)),
      t: () => go(today),
    },
    { enabled: fullscreen },
  );

  return (
    <article>
      {/* With a tag chosen the list spans many days: the heading names the list, and no day in the strip is chosen
          (a tap on one opens that day and leaves the filter). */}
      <DayStrip
        selected={shownDate}
        unmarked={dayTags.filtered}
        today={today}
        daysWithEntries={daysWithEntries}
        labels={dayStripLabels}
        disabled={phase === "loading"}
        onSelect={go}
        heading={
          <DayHeading
            ref={heading}
            long={
              dayTags.filtered
                ? t.taggedEntries
                : formatDayHeading(shownDate, t.dateLocale, today)
            }
            short={
              dayTags.filtered
                ? t.taggedEntries
                : formatDayHeading(shownDate, t.dateLocale, today, "short")
            }
          />
        }
        more={
          write.addAction || more.hasMore ? (
            <>
              {write.addAction && (
                <DayAddButton
                  write={write}
                  buttonRef={addButton}
                  labels={t}
                  loading={phase === "loading"}
                />
              )}
              {more.hasMore && (
                <DayMoreButton more={more} buttonRef={moreButton} />
              )}
            </>
          ) : undefined
        }
        panel={
          more.hasMore && <DayMorePanel more={more} buttonRef={moreButton} />
        }
        below={<DayAddPanel write={write} buttonRef={addButton} labels={t} />}
        // "Idag" shows only while the strip shows a week without today: in today's week the strip's own
        // "Idag" cell is the way back, so the button is gone rather than greyed. The `t` shortcut still works.
        actions={
          shownDays.includes(today) ? undefined : (
            <button
              type="button"
              className="sk-btn--secondary sk-btn--compact journal-day-today"
              disabled={phase === "loading"}
              onClick={() => go(today)}
            >
              {dayStripLabels.today}
            </button>
          )
        }
      />
      {phase === "loading" && <p role="status">{t.loading}</p>}
      {phase === "forbidden" && <p>{t.forbidden}</p>}
      {phase === "error" && (
        <ErrorNotice
          locale={t.dateLocale}
          cause={cause}
          onRetry={() => {
            if (target) go(target);
          }}
        />
      )}
      {created && !composing && <p role="status">{t.entryCreated}</p>}
      {composing && canWrite && (
        <EntryTextForm
          labels={t}
          kind="new"
          note={t.newEntryDay(formatLongDate(page.journal_date, t.dateLocale))}
          signatureBase={page.journal_date}
          submit={write.writeEntry}
          onCancel={() => write.setComposing(false)}
        />
      )}
      {/* Under the strip: the tag filter, and with a tag chosen the tagged list in place of the day's content. */}
      {!failedDate && (
        <DayTags
          state={dayTags}
          frame={frame}
          transport={transport}
          labels={t}
          refreshKey={refreshKey}
          onChange={onChange}
          onOpen={onOpen}
        />
      )}
      {!failedDate && !dayTags.filtered && (
        <>
          <DaySummary day={page} fullscreen={fullscreen} labels={t} />
          {/* «Gjort» under the day's summary, or first on a day with notes and no summary. */}
          {(summaryShown || page.entries.length > 0) && done}
          {page.entries.length > 0 ? <h3>{t.entries}</h3> : null}
          {page.entries.length === 0 && (
            <>
              <DayEmpty
                labels={t}
                isToday={page.journal_date === today}
                composing={composing}
                addOpen={addOpen}
                canWrite={canWrite}
                dayMessage={dayMessage}
                onTellClaude={onTellClaude}
                onWriteYourself={write.startComposing}
              />
              {/* An empty day without a summary: its sentence and its ways to write first, then what was done. */}
              {!summaryShown && done}
            </>
          )}
          {shownEntries.length > 0 && (
            <ul className="journal-timeline">
              {shownEntries.map((entry) => (
                <EntryRow
                  key={entry.id}
                  entry={entry}
                  labels={t}
                  tagVocabulary={dayTags.vocabulary.suggestions}
                  onOpen={() => onOpen({ kind: "entry", id: entry.id })}
                />
              ))}
            </ul>
          )}
          {!expanded && page.entries.length > inlineEntryLimit && (
            <p className="journal-list-more">
              <button
                type="button"
                className="sk-more"
                onClick={() => setExpandedDate(page.journal_date)}
              >
                {t.showAllEntries(page.entries.length)}
              </button>
            </p>
          )}
          {page.next_cursor && <p role="status">{t.moreEntries}</p>}
        </>
      )}
    </article>
  );
}
