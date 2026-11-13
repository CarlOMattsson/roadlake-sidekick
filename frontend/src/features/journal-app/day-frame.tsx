import { useEffect, useId, useRef, useState } from "react";
import { formatDayHeading, formatLongDate, shiftDate } from "./dates";
import { DayStrip, stripDays } from "./day-strip";
import { dayStripLabelsEn, dayStripLabelsSv } from "./day-strip-labels";
import { DoneSection } from "./done-section";
import { EntryTextForm } from "./entry-write";
import { EntryRow } from "./entry-row";
import { DaySummary, hasDaySummary } from "./day-summary";
import { DayTags, useDayTags } from "./day-tags";
import { isForbidden } from "./transport";
import type { JournalDay, JournalFrame } from "./transport";
import { useShortcuts } from "../mcp-apps/ui/shortcuts";
import { KeyScope } from "../mcp-apps/ui/key-scope";
import { MenuUpdateReminder, useMoreMark } from "../mcp-apps/update-reminder";
import {
  MenuLicenseRow,
  useLicenseInMenu,
  useLicenseMenu,
} from "../mcp-apps/license-mark";
import type { HostSettingsEntry } from "../mcp-apps/room-types";
import { MoreIcon, PlusIcon } from "../mcp-apps/ui/icons";
import { ownerNoon, ownerToday } from "../mcp-apps/app-timezone";
import { EmptyState, ErrorNotice } from "../mcp-apps/ui/states";
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

/** A new entry on another day than today sits on that day (noon, owner zone); on today the server decides. */
function occurredAtFor(
  date: string,
  today: string,
  zone?: string,
): string | undefined {
  if (date === today) return undefined;
  return ownerNoon(date, zone);
}

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
  const [moreOpen, setMoreOpen] = useState(false);
  const moreMark = useMoreMark(t.moreActions);
  const licenseInMenu = useLicenseInMenu();
  // ⋯ holds "Kontroll", and the update reminder and the license row when Control is off and the card is full size.
  const hasMore =
    Boolean(control) || (fullscreen && (moreMark.inMenu || licenseInMenu));
  // Writing by hand (see docs/decisions/log.md D-076: the journal is written by hand, no AI): the + menu, the open form, and the line after a saved entry.
  const [addOpen, setAddOpen] = useState(false);
  const [composing, setComposing] = useState(false);
  const [created, setCreated] = useState(false);
  const addButton = useRef<HTMLButtonElement>(null);
  const addPanel = useId();
  // «Gjort» is folded until the owner opens it; it stays open while she steps between days.
  const [doneOpen, setDoneOpen] = useState(false);
  const moreButton = useRef<HTMLButtonElement>(null);
  // The license coin asks (Control off): this ⋯ opens on its row.
  useLicenseMenu(moreButton, () => setMoreOpen(true));
  const morePanel = useId();
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
  const mounted = useRef(true);
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
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    if (moves > 0) heading.current?.focus();
  }, [moves]);
  // The latest values for the refresh below, so it reads the day as it is when the request arrives.
  const latest = useRef({ frame, phase, transport, onChange });
  useEffect(() => {
    latest.current = { frame, phase, transport, onChange };
  });
  // A changed refreshKey reads the shown day again, in place: no day change, no loading state, and the
  // expanded day and the scroll position stay. A read that lands after the owner moved on is dropped.
  const refreshAtMount = useRef(refreshKey);
  useEffect(() => {
    if (refreshKey === refreshAtMount.current) return;
    refreshAtMount.current = refreshKey;
    const shown = latest.current;
    // A day the owner is moving to is read by its own step; that read replaces the frame.
    if (shown.phase === "loading") return;
    shown.transport.getDay(shown.frame.page.journal_date).then(
      (next: JournalDay) => {
        if (!mounted.current || latest.current.frame !== shown.frame) return;
        shown.onChange({ ...shown.frame, page: next });
      },
      () => undefined,
    );
  }, [refreshKey]);

  function go(date: string) {
    // One day read at a time, as the disabled step buttons allowed before.
    if (phase === "loading") return;
    setPhase("loading");
    setCreated(false);
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

  // The dots in the strip: one list_journal_entries read (dates only) per shown seven days, again on a refresh.
  // Kept per range, so stepping back to seven days already read shows their dots at once while they are read again.
  const shownDays = stripDays(shownDate, today);
  const rangeFrom = shownDays[0];
  const rangeTo = shownDays[shownDays.length - 1];
  const [entryDates, setEntryDates] = useState<Record<string, string[]>>({});
  useEffect(() => {
    const list = latest.current.transport.listEntryDates;
    if (!list || !rangeFrom || !rangeTo) return;
    const range = `${rangeFrom}/${rangeTo}`;
    let current = true;
    list(rangeFrom, rangeTo).then(
      (dates) => {
        if (current && mounted.current)
          setEntryDates((known) => ({ ...known, [range]: dates }));
      },
      // A failed read leaves the dots as they were: the day the view has read still gets its own.
      () => undefined,
    );
    return () => {
      current = false;
    };
  }, [rangeFrom, rangeTo, refreshKey]);
  // The day the view has read is newer than the range read, so it decides its own dot.
  const daysWithEntries = (entryDates[`${rangeFrom}/${rangeTo}`] ?? []).filter(
    (date) => date !== page.journal_date,
  );
  if (page.entries.length > 0) daysWithEntries.push(page.journal_date);

  // The summary section shows with a summary or a note about one; an empty summary is not shown.
  const summaryShown = hasDaySummary(page.summary);
  // What was done on the day (completed tasks and steps, and purchases, as the journal read returns them); an older server sends no `done`, and the section is then absent.
  const done = page.done ? (
    <DoneSection
      done={page.done}
      labels={t}
      open={doneOpen}
      onToggle={() => setDoneOpen((open) => !open)}
    />
  ) : null;
  // A day with notes asks for more behind + in its title row, where the other rooms create:
  // the content starts with the day itself. A day without notes (also one with only a summary) keeps its whole button under its sentence.
  // What an empty day says to Claude: today's own message, or the day it is about.
  const dayMessage =
    page.journal_date === today
      ? t.tellClaudeMessage
      : t.tellClaudeDayMessage(formatLongDate(page.journal_date, t.dateLocale));
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

  // The day's + (see docs/decisions/log.md D-076: the journal is written by hand, no AI): with a transport that can write, it also holds writing by hand. Together with Claude it
  // opens a two-item menu; alone it opens the form. Without a writing transport it is the old "Tell Claude more".
  const canWrite = transport.writeEntry !== undefined && !failedDate;
  const tellClaudeAction = onTellClaude
    ? () => (tellMore ? tellMore() : onTellClaude(dayMessage))
    : undefined;
  const addAction = canWrite
    ? () => {
        if (tellClaudeAction) setAddOpen((open) => !open);
        else {
          setCreated(false);
          setComposing(true);
        }
      }
    : tellMore;
  function writeEntry(
    values: { title: string; text: string },
    idempotencyKey: string,
  ): Promise<void> {
    const write = transport.writeEntry;
    if (!write) return Promise.reject(new Error("no writeEntry"));
    const journalDate = page.journal_date;
    const occurredAt = occurredAtFor(journalDate, today, page.owner_timezone);
    return write(
      {
        journal_date: journalDate,
        title: values.title,
        source_text: values.text,
        ...(occurredAt ? { occurred_at: occurredAt } : {}),
      },
      idempotencyKey,
    ).then(({ entry }) => {
      setComposing(false);
      setCreated(true);
      // The day is read again so the entry sits where the server puts it; if that read fails the entry is added here.
      return transport.getDay(journalDate).then(
        (next) => {
          if (mounted.current) onChange({ ...frame, page: next });
        },
        () => {
          if (mounted.current)
            onChange({
              ...frame,
              page: { ...page, entries: [...page.entries, entry] },
            });
        },
      );
    });
  }

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
      <DayStrip
        selected={shownDate}
        today={today}
        daysWithEntries={daysWithEntries}
        labels={dayStripLabels}
        disabled={phase === "loading"}
        onSelect={go}
        heading={
          <h2 ref={heading} tabIndex={-1}>
            {formatDayHeading(shownDate, t.dateLocale, today)}
          </h2>
        }
        more={
          addAction || hasMore ? (
            <>
              {/* The day's one primary: the round ink + of the list views, 4 before ⋯. */}
              {addAction && (
                <button
                  ref={addButton}
                  type="button"
                  className="sk-iconbtn sk-iconbtn--primary journal-day-add"
                  aria-label={canWrite ? t.addEntry : t.tellClaude}
                  title={canWrite ? t.addEntry : t.tellClaude}
                  aria-expanded={
                    canWrite && tellClaudeAction ? addOpen : undefined
                  }
                  aria-controls={
                    canWrite && tellClaudeAction && addOpen
                      ? addPanel
                      : undefined
                  }
                  aria-disabled={phase === "loading" || undefined}
                  onClick={() => {
                    if (phase !== "loading") addAction();
                  }}
                >
                  <PlusIcon />
                </button>
              )}
              {hasMore && (
                <button
                  ref={moreButton}
                  type="button"
                  className="sk-iconbtn journal-day-more"
                  aria-label={moreMark.label}
                  aria-expanded={moreOpen}
                  aria-controls={morePanel}
                  onClick={() => setMoreOpen(!moreOpen)}
                >
                  <MoreIcon />
                  {moreMark.dot}
                </button>
              )}
            </>
          ) : undefined
        }
        panel={
          <>
            {hasMore && (
              // The room's ⋯ menu as Work's (a card under the head, 44 rows): Control, or the update reminder
              // in its place when Control is off.
              <KeyScope
                id={morePanel}
                className="journal-more-panel"
                hidden={!moreOpen}
                onEscape={() => {
                  setMoreOpen(false);
                  moreButton.current?.focus();
                }}
              >
                {control && (
                  <button
                    type="button"
                    className="journal-more-item"
                    onClick={() => {
                      setMoreOpen(false);
                      control.onOpen();
                    }}
                  >
                    {control.label}
                  </button>
                )}
                <MenuUpdateReminder />
                <MenuLicenseRow />
              </KeyScope>
            )}
          </>
        }
        below={
          // Mounted only while open: a closed panel between the week and the content would part the strip from the
          // summary and heading that follow it (journal.css).
          canWrite && tellClaudeAction && addOpen ? (
            <KeyScope
              id={addPanel}
              className="journal-add-panel"
              onEscape={() => {
                setAddOpen(false);
                addButton.current?.focus();
              }}
            >
              {/* Two real buttons, one way each: Claude asks, or the user writes. */}
              <button
                type="button"
                className="sk-btn--primary journal-add-choice"
                onClick={() => {
                  setAddOpen(false);
                  tellClaudeAction();
                }}
              >
                {t.tellClaude}
              </button>
              <button
                type="button"
                className="sk-btn--secondary journal-add-choice"
                onClick={() => {
                  setAddOpen(false);
                  setCreated(false);
                  setComposing(true);
                }}
              >
                {t.writeYourself}
              </button>
              <p className="journal-add-hint">{t.tellClaudeHint}</p>
            </KeyScope>
          ) : undefined
        }
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
          submit={writeEntry}
          onCancel={() => setComposing(false)}
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
          {/* An empty day has no section heading over nothing: one sentence, then the primary way to write. */}
          {page.entries.length > 0 ? <h3>{t.entries}</h3> : null}
          {page.entries.length === 0 && (
            <>
              {/* The family's empty state: the sentence, then what to say to Claude, and writing by hand as the
                  secondary. One way to write at a time: while + has its choices open, or the form is open,
                  the empty day says only its sentence. */}
              {composing || addOpen ? (
                composing ? null : (
                  <p className="journal-empty">
                    {page.journal_date === today
                      ? t.noEntriesToday
                      : t.noEntries}
                  </p>
                )
              ) : (
                <div className="journal-empty-state">
                  <EmptyState
                    title={
                      page.journal_date === today
                        ? t.noEntriesToday
                        : t.noEntries
                    }
                    ask={
                      failedDate
                        ? undefined
                        : {
                            locale: t.dateLocale,
                            example: dayMessage,
                            onSend: onTellClaude
                              ? () => onTellClaude(dayMessage)
                              : undefined,
                          }
                    }
                  >
                    {canWrite ? (
                      <button
                        type="button"
                        className="sk-btn--secondary journal-write-self"
                        onClick={() => {
                          setCreated(false);
                          setComposing(true);
                        }}
                      >
                        {t.writeYourself}
                      </button>
                    ) : null}
                  </EmptyState>
                </div>
              )}
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
            <p>
              <button
                type="button"
                className="sk-btn--quiet"
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
