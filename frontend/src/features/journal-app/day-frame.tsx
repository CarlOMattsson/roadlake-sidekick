import { useContext, useEffect, useRef, useState } from "react";
import { formatDayHeading, formatLongDate, shiftDate } from "./dates";
import { DayEmpty } from "./day-empty";
import { rereadDay, useDayRefresh, useEntryDates } from "./day-frame-hooks";
import { DayHeading } from "./day-heading";
import { useDayPhotos } from "./day-photos";
import { DayMoreButton, DayMorePanel, useDayMore } from "./day-more";
import { DayRead, JournalAside } from "./day-read";
import { DayStrip, stripDays } from "./day-strip";
import { dayStripLabelsEn, dayStripLabelsSv } from "./day-strip-labels";
import {
  DayAddButton,
  DayAddPanel,
  dayAddTool,
  useDayWrite,
} from "./day-write";
import { DoneSection } from "./done-section";
import { JournalViewSwitch } from "./view-switch";
import { weekTitle } from "./week-frame";
import { EntryTextForm } from "./entry-write";
import { EntryRow } from "./entry-row";
import { DaySummary, hasDaySummary } from "./day-summary";
import { DayTags, useDayTags } from "./day-tags";
import { MonthRail } from "./month-rail";
import { RailEntries } from "./rail-entries";
import { isForbidden } from "./transport";
import { isQueued, isStandInId, useQueuedRecords } from "./use-queued-records";
import type { JournalDay, JournalFrame } from "./transport";
import { useRoomShortcuts } from "../mcp-apps/ui/shortcut-registry";
import { RoomSurfaceContext } from "../mcp-apps/ui/room-context";
import { useSplitList } from "../mcp-apps/ui/split-layout";
import { shellLabelsForDateLocale } from "../mcp-apps/sidekick-shell-labels";
import { RoomHead } from "../mcp-apps/ui/room-head";
import { useMounted } from "../mcp-apps/ui/use-mounted";
import type { HostSettingsEntry } from "../mcp-apps/room-types";
import { ownerToday } from "../mcp-apps/app-timezone";
import { ErrorNotice } from "../mcp-apps/ui/states";
import { ReceiptBar, useReceipt } from "../mcp-apps/ui/receipt";
import { receiptText } from "./receipt-text";
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
   * The last entry of the day view's ⋯: Control, or the host's own settings (the phone's settings). Absent: no
   * such entry.
   */
  control?: HostSettingsEntry;
  /** Present in fullscreen: switches to the calendar week view of the shown day. Absent: no switch. */
  onShowWeek?: () => void;
  /** The day opens with the form for a new entry open (the week view's +). */
  startComposing?: boolean;
  /** Called once the form was opened that way, so the view does not open it again on a later mount. */
  onComposeStarted?: () => void;
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
  onShowWeek,
  startComposing,
  onComposeStarted,
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
  const queuedIds = useQueuedRecords(transport);
  // In a wide frame the list pane is a rail (the month calendar and the day's rows) and the day is read beside it, in
  // the shell's aside; `aside` is false while an entry is open there, as the aside is then the entry's.
  const split = useSplitList();
  const { asideSlot } = useContext(RoomSurfaceContext);
  const rail = split && fullscreen;
  const aside = rail && Boolean(asideSlot);
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
  // A day opened for a new entry has told the view so once; a later mount does not open the form again.
  const composeStarted = useRef(onComposeStarted);
  useEffect(() => {
    if (startComposing) composeStarted.current?.();
  }, [startComposing]);

  // A saved note is confirmed in the receipt bar, which goes by itself and is cleared on another day: it never stays
  // in the day's content to come back later (dagbok-ui fynd 1).
  const receipt = useReceipt(page.journal_date);
  const { show: showReceipt } = receipt;
  // A message to Claude goes into the conversation, and the host shows no answer here: the receipt says where it comes.
  const tellClaude = onTellClaude
    ? (text?: string) => {
        onTellClaude(text);
        showReceipt({ message: t.tellClaudeSent });
      }
    : undefined;
  // What an empty day says to Claude: today's own message, or the day it is about.
  const dayMessage =
    page.journal_date === today
      ? t.tellClaudeMessage
      : t.tellClaudeDayMessage(formatLongDate(page.journal_date, t.dateLocale));
  // A day with notes asks for more behind + in its title row, where the other rooms create:
  // the content starts with the day itself. A day without notes (also one with only a summary) keeps its whole button under its sentence.
  const tellMore =
    tellClaude && !failedDate && page.entries.length > 0
      ? () =>
          tellClaude(
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
    onTellClaude: tellClaude,
    tellMore,
    dayMessage,
    startComposing,
  });
  // The day's photos: the block under the summary, and the viewer that takes the day's place while a photo is open.
  const photos = useDayPhotos({
    transport,
    labels: t,
    journalDate: page.journal_date,
    ids: page.day_attachments?.ids ?? [],
    fullscreen,
    onAdded: () => {
      showReceipt({ message: receiptText(t.photosAdded) });
      rereadDay(frame, transport, mounted, onChange);
    },
  });
  const { canWrite, composing, created, addOpen } = write;
  const { clearCreated } = write;
  useEffect(() => {
    if (!created || composing) return;
    showReceipt({ message: receiptText(t.entryCreated) });
    clearCreated();
  }, [created, composing, showReceipt, clearCreated, t.entryCreated]);

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
        // A step with ← → or [ ] from a row of the old day leaves the focus on nothing once that row is gone: the
        // new day's heading takes it, so the keys and Tab go on from the day shown. Focus anywhere else stays.
        requestAnimationFrame(() => {
          const now = document.activeElement;
          if (!now || now === document.body) heading.current?.focus();
        });
      })
      .catch((error: unknown) => {
        if (!mounted.current) return;
        setCause(error);
        setPhase(isForbidden(error) ? "forbidden" : "error");
      });
  }

  const shownDays = stripDays(shownDate);
  const rangeFrom = shownDays[0];
  const rangeTo = shownDays[shownDays.length - 1];
  // The day the view has read is newer than the range read, so it decides its own dot. The rail's calendar reads its
  // own month, so the strip's week is not read there.
  const daysWithEntries = useEntryDates(
    transport,
    rail ? undefined : rangeFrom,
    rail ? undefined : rangeTo,
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

  // Design language 4.6: `[` `]` and ← → step to the previous and next day, `t` to today. A day after today is never
  // offered, so a step stops there. Fullscreen only: an inline card has no shortcuts.
  const keys = shellLabelsForDateLocale(t.dateLocale).shortcuts;
  const stepDay = (delta: number) => {
    const next = shiftDate(shownDate, delta);
    if (next <= today) go(next);
  };
  useRoomShortcuts(
    {
      "[": () => stepDay(-1),
      "]": () => stepDay(1),
      ArrowLeft: () => stepDay(-1),
      ArrowRight: () => stepDay(1),
      t: () => go(today),
    },
    {
      id: "journal-day",
      title: t.title,
      labels: {
        "[": keys.previousDay,
        "]": keys.nextDay,
        ArrowLeft: keys.previousDay,
        ArrowRight: keys.nextDay,
        t: keys.today,
      },
    },
    { enabled: fullscreen },
  );

  // The `today` button shows only while the strip shows a week without today: in today's week the strip's own `today`
  // cell is the way back, so the button is gone rather than greyed. It stands before the tools, so its coming and going
  // moves nothing else. The `t` shortcut still works. The calendar has no such cell: it is there while the shown day is not today.
  const todayButton = !(rail
    ? shownDate === today
    : shownDays.includes(today)) ? (
    <button
      type="button"
      className="sk-btn sk-btn--quiet sk-btn--compact journal-day-today"
      disabled={phase === "loading"}
      onClick={() => go(today)}
    >
      {dayStripLabels.today}
    </button>
  ) : undefined;

  // Fullscreen: the room head (Dag | Vecka, `today`, + and ⋯ at their fixed places), in the shell's row when wide.
  const head = onShowWeek ? (
    <RoomHead
      scope="sidekick-journal"
      keysTitle={t.title}
      tabs={
        <JournalViewSwitch
          value="day"
          labels={t}
          disabled={phase === "loading"}
          onChange={onShowWeek}
        />
      }
      views={[
        { key: "d", label: t.viewDay, onChoose: () => undefined },
        { key: "w", label: t.viewWeek, onChoose: onShowWeek },
      ]}
      extra={todayButton}
      add={dayAddTool(write, t, phase === "loading")}
      addRef={addButton}
      more={
        more.hasMore ? (
          <DayMoreButton more={more} buttonRef={moreButton} />
        ) : undefined
      }
    />
  ) : undefined;
  const morePanel = more.hasMore ? (
    <DayMorePanel more={more} buttonRef={moreButton} />
  ) : undefined;

  const notices = (
    <>
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
    </>
  );
  const textForm =
    composing && canWrite ? (
      <EntryTextForm
        labels={t}
        kind="new"
        note={t.newEntryDay(formatLongDate(page.journal_date, t.dateLocale))}
        signatureBase={page.journal_date}
        submit={write.writeEntry}
        onCancel={() => write.setComposing(false)}
      />
    ) : null;
  const empty = (
    <DayEmpty
      labels={t}
      isToday={page.journal_date === today}
      composing={composing}
      addOpen={addOpen}
      canWrite={canWrite}
      dayMessage={dayMessage}
      onTellClaude={tellClaude}
      onWriteYourself={write.startComposing}
    />
  );
  const tags = !failedDate && (
    <DayTags
      state={dayTags}
      frame={frame}
      transport={transport}
      labels={t}
      refreshKey={refreshKey}
      onChange={onChange}
      onOpen={onOpen}
      wrap={rail}
    />
  );
  const openEntry = (id: string) => onOpen({ kind: "entry", id });
  const photoBlock = !failedDate && !dayTags.filtered ? photos.block : null;

  // A photo opened from the day is a layer: it takes the place of the day, and closing it returns to the day.
  if (photos.viewer) return <article>{photos.viewer}</article>;

  if (rail) {
    const long = formatDayHeading(shownDate, t.dateLocale, today);
    return (
      <article>
        {head}
        {morePanel}
        <MonthRail
          transport={transport}
          refreshKey={refreshKey}
          selected={shownDate}
          unmarked={dayTags.filtered}
          today={today}
          known={{
            date: page.journal_date,
            hasEntries: page.entries.length > 0,
          }}
          labels={dayStripLabels}
          disabled={phase === "loading"}
          onSelect={go}
        />
        <DayAddPanel write={write} buttonRef={addButton} labels={t} />
        {notices}
        {/* The form takes the reading pane; with an entry open there is no such pane, and it stands under the calendar. */}
        {!aside && textForm}
        {!failedDate && !dayTags.filtered && (
          <RailEntries
            entries={page.entries}
            labels={t}
            queuedIds={queuedIds}
            onOpen={openEntry}
          />
        )}
        {/* In the rail the tags are a list that wraps (desktop spec 3.2), not the phone's sideways scroller. */}
        <div className="journal-rail-tags">{tags}</div>
        {!failedDate && !dayTags.filtered && done}
        {photoBlock}
        {!failedDate &&
          !dayTags.filtered &&
          (composing && canWrite ? (
            <JournalAside className="journal-read">{textForm}</JournalAside>
          ) : (
            <DayRead
              day={page}
              heading={long}
              headingRef={heading}
              transport={transport}
              labels={t}
              queuedIds={queuedIds}
              onOpen={openEntry}
              empty={empty}
            />
          ))}
        <ReceiptBar receipt={receipt} />
      </article>
    );
  }

  // Writing is a view of its own (dagbok-ui fynd 4): the strip and the week's arrows are put away, and what is left is
  // the room head and the form. Cancel and Save bring them back.
  if (fullscreen && textForm) {
    return (
      <article>
        {head}
        {morePanel}
        {textForm}
        <ReceiptBar receipt={receipt} />
      </article>
    );
  }

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
        head={head}
        // The same name as the week view's: "Vecka 47 · 16–22 nov", for the Monday-to-Sunday week the strip shows.
        weekLabel={shownDays[0] ? weekTitle(shownDays[0], t, today) : undefined}
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
        panel={morePanel}
        below={<DayAddPanel write={write} buttonRef={addButton} labels={t} />}
        // The `today` button shows only while the strip shows a week without today: in today's week the strip's own
        // `today` cell is the way back, so the button is gone rather than greyed. It stands before + and ⋯ at the end
        // of the first row, so its coming and going moves nothing else. The `t` shortcut still works.
        actions={todayButton}
      />
      {notices}
      {textForm}
      {/* Under the strip: the tag filter, and with a tag chosen the tagged list in place of the day's content. */}
      {tags}
      {!failedDate && !dayTags.filtered && (
        <>
          <DaySummary day={page} fullscreen={fullscreen} labels={t} />
          {/* «Gjort» under the day's summary, or first on a day with notes and no summary. */}
          {(summaryShown || page.entries.length > 0) && done}
          {photoBlock}
          {page.entries.length > 0 ? <h3>{t.entries}</h3> : null}
          {page.entries.length === 0 && (
            <>
              {empty}
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
                  queued={isQueued(queuedIds, entry.id)}
                  // A note still in the outbox has no entry on the server to open yet.
                  onOpen={
                    isStandInId(entry.id)
                      ? undefined
                      : () => openEntry(entry.id)
                  }
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
      <ReceiptBar receipt={receipt} />
    </article>
  );
}
