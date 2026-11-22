import { useContext, useEffect, useMemo, useRef } from "react";
import { ownerToday } from "../mcp-apps/app-timezone";
import { ChevronLeftIcon, ChevronRightIcon } from "../mcp-apps/ui/icons";
import type { HostSettingsEntry } from "../mcp-apps/room-types";
import { ErrorNotice } from "../mcp-apps/ui/states";
import { RoomSurfaceContext } from "../mcp-apps/ui/room-context";
import { useRoomShortcuts } from "../mcp-apps/ui/shortcut-registry";
import { useTagVocabulary } from "../mcp-apps/ui/tag-vocabulary";
import { shellLabelsForDateLocale } from "../mcp-apps/sidekick-shell-labels";
import {
  formatShortDate,
  isoWeekNumber,
  shiftDate,
  weekDates,
  weekStart,
} from "./dates";
import { DayHeading } from "./day-heading";
import { DayMoreButton, DayMorePanel, useDayMore } from "./day-more";
import { weekRange } from "./day-strip";
import type { FrameProps } from "./frame-props";
import type { JournalLabels } from "./labels";
import type { JournalFrame } from "./transport";
import { useQueuedRecords } from "./use-queued-records";
import { useStuck } from "./use-stuck";
import { useWeekDays } from "./use-week-days";
import { JournalViewSwitch } from "./view-switch";
import { RoomHead } from "../mcp-apps/ui/room-head";
import { TagFilter } from "../mcp-apps/ui/tags";
import { useSplitList } from "../mcp-apps/ui/split-layout";
import { JournalAside } from "./day-read";
import { dayStripLabelsEn, dayStripLabelsSv } from "./day-strip-labels";
import { MonthRail } from "./month-rail";
import { WeekDay, WeekGap } from "./week-day";
import { weekGapText, weekSegments } from "./week-gaps";
import "./week.css";

/**
 * The days a week view shows its heading for, in words: "16–22 nov" in one month, "29 okt–4 nov" across two. The year
 * follows when the week is not in the year of `today`, and both years when the week spans two ("29 dec 2025–4 jan 2026").
 */
export function weekHeadingRange(
  days: readonly string[],
  locale: string,
  today: string,
): string {
  const first = days[0];
  const last = days.at(-1);
  if (!first || !last) return "";
  const firstYear = first.slice(0, 4);
  const lastYear = last.slice(0, 4);
  if (firstYear !== lastYear)
    return `${formatShortDate(first, locale)} ${firstYear}–${formatShortDate(last, locale)} ${lastYear}`;
  const range = weekRange(days, locale);
  return lastYear === today.slice(0, 4) ? range : `${range} ${lastYear}`;
}

/** The week view's title: "Vecka 47 · 16–22 nov". */
export function weekTitle(
  start: string,
  labels: JournalLabels,
  today: string,
): string {
  return labels.weekTitle(
    isoWeekNumber(start),
    weekHeadingRange(weekDates(start), labels.dateLocale, today),
  );
}

type WeekFrameProps = FrameProps & {
  frame: Extract<JournalFrame, { kind: "day" }>;
  /** The Monday of the shown week. */
  start: string;
  onStart: (monday: string) => void;
  /** To the day view, on `date` when a day is meant (the first of a run of empty days); without it, on the day it showed. */
  onShowDay: (date?: string) => void;
  /** Writes a new entry. Present: the room head draws + (the same one as the day view's); absent: no +. */
  onAdd?: () => void;
  onOpen: (frame: JournalFrame) => void;
  refreshKey?: number;
  control?: HostSettingsEntry;
  /** In a wide frame the tag filter stands under the calendar; choosing a tag opens the tagged list (the day view's). Absent: no filter. */
  onFilterTags?: (tags: string[]) => void;
};

/**
 * A calendar week, Monday to Sunday, as one scrollable list: per day its heading, its summary, its entries and its folded
 * «Gjort» (week-day.tsx). Days after today are not listed. The arrows (and `[` `]`, ← and →) step a calendar week, `t`
 * goes to this week. The week's name and ‹ › stay under the shell's rows while the list scrolls; ‹ › come first, so ›
 * stands at the same place whatever the name says. Runs of days with nothing written are one quiet line each, with the way to write for the first of them. Each day is read with the day view's own call, so what the week shows is what the day shows.
 */
export function WeekFrame({
  frame,
  start,
  onStart,
  onShowDay,
  onAdd,
  transport,
  labels: t,
  moves,
  onOpen,
  refreshKey,
  control,
  onFilterTags,
}: WeekFrameProps) {
  const heading = useRef<HTMLHeadingElement>(null);
  const moreButton = useRef<HTMLButtonElement>(null);
  const more = useDayMore(t, true, control, moreButton);
  const queuedIds = useQueuedRecords(transport);
  // The owner's today (the zone the day result names, else the declared one), never the device's.
  const today = ownerToday(frame.page.owner_timezone);
  const thisWeek = weekStart(today);
  const dates = weekDates(start).filter((date) => date <= today);
  const { read, retry } = useWeekDays(transport, dates, refreshKey);
  const segments = useMemo(
    () => (read.phase === "ready" ? weekSegments(read.days) : []),
    [read],
  );
  const vocabulary = useTagVocabulary(transport.listTags, "journal_entry");
  // In the shell's row (wide) the room head is inside the bar the week head rests under; in place it is a row of its own.
  const headInBar = Boolean(useContext(RoomSurfaceContext).headSlot);
  const { marker, element: stickyHead, stuck } = useStuck<HTMLDivElement>();
  const title = weekTitle(start, t, today);
  const atThisWeek = start >= thisWeek;
  const rail = useSplitList();
  useEffect(() => {
    if (moves > 0) heading.current?.focus();
  }, [moves]);

  // A step forward stops at this week: no day after today is offered.
  const step = (delta: number) =>
    onStart(
      delta > 0 && atThisWeek ? thisWeek : weekStart(shiftDate(start, delta)),
    );
  const keys = shellLabelsForDateLocale(t.dateLocale).shortcuts;
  useRoomShortcuts(
    {
      "[": () => step(-7),
      "]": () => step(7),
      ArrowLeft: () => step(-7),
      ArrowRight: () => step(7),
      t: () => onStart(thisWeek),
    },
    {
      id: "journal-week",
      title: t.title,
      labels: {
        "[": keys.previousWeek,
        "]": keys.nextWeek,
        ArrowLeft: keys.previousWeek,
        ArrowRight: keys.nextWeek,
        t: keys.thisWeek,
      },
    },
    { enabled: true },
  );

  // The room head (Dag | Vecka with the tools, + where the owner can write).
  const head = (
    <RoomHead
      scope="sidekick-journal"
      keysTitle={t.title}
      tabs={
        <JournalViewSwitch
          value="week"
          labels={t}
          onChange={() => onShowDay()}
        />
      }
      views={[
        { key: "d", label: t.viewDay, onChoose: () => onShowDay() },
        { key: "w", label: t.viewWeek, onChoose: () => undefined },
      ]}
      extra={
        atThisWeek ? undefined : (
          <button
            type="button"
            className="sk-btn sk-btn--quiet sk-btn--compact journal-day-today"
            onClick={() => onStart(thisWeek)}
          >
            {t.weekThis}
          </button>
        )
      }
      add={onAdd ? { label: t.addEntry, onPress: onAdd } : undefined}
      more={
        more.hasMore ? (
          <DayMoreButton more={more} buttonRef={moreButton} />
        ) : undefined
      }
    />
  );
  // The week head: ‹ › and the week's name, which is the heading, resting under the shell's rows while the list scrolls.
  const weekHead = (
    <>
      <span ref={marker} className="sk-week-head__marker" aria-hidden="true" />
      <div
        ref={stickyHead}
        className="sk-week-head"
        data-place={headInBar ? "bar" : "room"}
        data-stuck={stuck || undefined}
      >
        <div className="sk-week-head__arrows">
          <button
            type="button"
            className="sk-iconbtn sk-day-strip-arrow"
            aria-label={t.weekPrevious}
            onClick={() => step(-7)}
          >
            <ChevronLeftIcon />
          </button>
          <button
            type="button"
            className="sk-iconbtn sk-day-strip-arrow"
            aria-label={t.weekNext}
            aria-disabled={atThisWeek || undefined}
            onClick={() => !atThisWeek && step(7)}
          >
            <ChevronRightIcon />
          </button>
        </div>
        <div className="sk-week-head__title">
          <DayHeading ref={heading} long={title} short={title} />
        </div>
      </div>
    </>
  );
  const morePanel = more.hasMore ? (
    <DayMorePanel more={more} buttonRef={moreButton} />
  ) : undefined;
  const days = (
    <>
      {read.phase === "loading" && <p role="status">{t.weekLoading}</p>}
      {read.phase === "forbidden" && <p>{t.forbidden}</p>}
      {read.phase === "error" && (
        <ErrorNotice locale={t.dateLocale} cause={read.cause} onRetry={retry} />
      )}
      {read.phase === "ready" &&
        segments.map((segment) => {
          if (segment.kind === "day")
            return (
              <WeekDay
                key={segment.day.journal_date}
                day={segment.day}
                today={today}
                labels={t}
                queuedIds={queuedIds}
                tagVocabulary={vocabulary.suggestions}
                onOpen={(id) => onOpen({ kind: "entry", id })}
              />
            );
          const wholeWeek = segments.length === 1;
          return (
            <WeekGap
              key={segment.dates[0]}
              text={weekGapText(
                segment.dates,
                t,
                wholeWeek ? isoWeekNumber(start) : undefined,
              )}
              labels={t}
              onWrite={() => onShowDay(segment.dates[0])}
            />
          );
        })}
    </>
  );

  // In a wide frame the list pane holds the calendar (the week filled) and the tag filter, and the week is read beside it.
  if (rail)
    return (
      <article>
        {head}
        {morePanel}
        <MonthRail
          transport={transport}
          refreshKey={refreshKey}
          selected={start}
          week={weekDates(start)}
          today={today}
          labels={
            t.dateLocale.startsWith("sv") ? dayStripLabelsSv : dayStripLabelsEn
          }
          onSelect={(date) => onShowDay(date)}
        />
        {onFilterTags && (
          <div className="journal-rail-tags">
            <TagFilter
              options={vocabulary.options}
              selected={[]}
              onChange={onFilterTags}
              locale={t.dateLocale}
              wrap
            />
          </div>
        )}
        <JournalAside>
          {weekHead}
          {days}
        </JournalAside>
      </article>
    );
  return (
    <article>
      {head}
      {weekHead}
      {morePanel}
      {days}
    </article>
  );
}
