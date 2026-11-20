import { useEffect, useRef } from "react";
import { ownerToday } from "../mcp-apps/app-timezone";
import { ChevronLeftIcon, ChevronRightIcon } from "../mcp-apps/ui/icons";
import type { HostSettingsEntry } from "../mcp-apps/room-types";
import { ErrorNotice } from "../mcp-apps/ui/states";
import { useShortcuts } from "../mcp-apps/ui/shortcuts";
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
import { useWeekDays } from "./use-week-days";
import { JournalViewSwitch } from "./view-switch";
import { WeekDay } from "./week-day";

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
  /** Back to the day view. */
  onShowDay: () => void;
  onOpen: (frame: JournalFrame) => void;
  refreshKey?: number;
  control?: HostSettingsEntry;
};

/**
 * A calendar week, Monday to Sunday, as one scrollable list: per day its heading, its summary, its entries and its folded
 * «Gjort» (week-day.tsx). Days after today are not listed. The arrows (and `[` and `]`) step a calendar week, `t` goes to
 * this week. Each day is read with the day view's own call, so what the week shows is what the day shows.
 */
export function WeekFrame({
  frame,
  start,
  onStart,
  onShowDay,
  transport,
  labels: t,
  moves,
  onOpen,
  refreshKey,
  control,
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
  const title = weekTitle(start, t, today);
  const atThisWeek = start >= thisWeek;
  useEffect(() => {
    if (moves > 0) heading.current?.focus();
  }, [moves]);

  // A step forward stops at this week: no day after today is offered.
  const step = (delta: number) =>
    onStart(
      delta > 0 && atThisWeek ? thisWeek : weekStart(shiftDate(start, delta)),
    );
  useShortcuts(
    {
      "[": () => step(-7),
      "]": () => step(7),
      t: () => onStart(thisWeek),
    },
    { enabled: true },
  );

  return (
    <article>
      {/* The same two rows as the day view: Dag | Vecka with the tools, then the week row, whose name is the heading. */}
      <div className="sk-day-strip-head" data-tabs="true">
        <div className="sk-day-strip-tabs">
          <JournalViewSwitch value="week" labels={t} onChange={onShowDay} />
        </div>
        <div className="sk-day-strip-tools">
          {!atThisWeek && (
            <button
              type="button"
              className="sk-btn sk-btn--quiet sk-btn--compact journal-day-today"
              onClick={() => onStart(thisWeek)}
            >
              {t.weekThis}
            </button>
          )}
          {more.hasMore && <DayMoreButton more={more} buttonRef={moreButton} />}
        </div>
        <div className="sk-day-strip-weekrow">
          <button
            type="button"
            className="sk-iconbtn sk-day-strip-arrow"
            aria-label={t.weekPrevious}
            onClick={() => step(-7)}
          >
            <ChevronLeftIcon />
          </button>
          <div className="journal-day-range">
            <DayHeading ref={heading} long={title} short={title} />
          </div>
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
      </div>
      {more.hasMore && <DayMorePanel more={more} buttonRef={moreButton} />}
      {read.phase === "loading" && <p role="status">{t.weekLoading}</p>}
      {read.phase === "forbidden" && <p>{t.forbidden}</p>}
      {read.phase === "error" && (
        <ErrorNotice locale={t.dateLocale} cause={read.cause} onRetry={retry} />
      )}
      {read.phase === "ready" &&
        read.days.map((day) => (
          <WeekDay
            key={day.journal_date}
            day={day}
            today={today}
            labels={t}
            queuedIds={queuedIds}
            onOpen={(id) => onOpen({ kind: "entry", id })}
          />
        ))}
    </article>
  );
}
