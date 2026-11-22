import {
  type KeyboardEvent,
  type ReactNode,
  type TouchEvent,
  useEffect,
  useRef,
} from "react";
import { ChevronLeftIcon, ChevronRightIcon } from "../mcp-apps/ui/icons";
import {
  formatCalendarDate,
  formatShortDate,
  shiftDate,
  weekDates,
} from "./dates";
import type { DayStripLabels } from "./day-strip-labels";
import "./journal.css";

/**
 * Every day cell is at least 56 px high in px (weekday or `today`, the number, and an 8 px marker row for the entry dot;
 * 104–160 at 412, it was 3.5rem, 61.6 at 110 %), and grows with its rows at large text. Its width
 * comes from the grid in journal.css.
 */
const dayStyle = { minHeight: "56px" };
/** A horizontal swipe of at least this many px steps one week. Shorter or mostly vertical moves do nothing. */
const swipeMinimum = 48;

export type DayStripProps = {
  /** The selected day, YYYY-MM-DD. The strip shows the seven days of `stripDays(selected)`. */
  selected: string;
  /**
   * No day is chosen: the view lists entries from many days (a tag filter). No cell is filled or read as selected;
   * `selected` still picks the week and holds the strip's tab stop, and a tap on a day opens that day. No dots either:
   * they mark days with any entry, which in a list of tagged entries would read as hits.
   */
  unmarked?: boolean;
  /** Today, YYYY-MM-DD. Passed in so the strip never reads the clock. */
  today: string;
  /** Days (YYYY-MM-DD) with at least one entry. Days outside the shown seven are ignored. */
  daysWithEntries: readonly string[];
  labels: DayStripLabels;
  disabled?: boolean;
  onSelect: (date: string) => void;
  /**
   * The day's heading. Without `head` it stands on the head's first row with the tools; with `head` it stands under
   * the strip, so the first two rows are the same in the day and the week view.
   */
  heading?: ReactNode;
  /**
   * The room head (ui/room-head.tsx: Dag | Vecka with + and ⋯) in fullscreen, in place of the title row; then `actions`
   * and `more` are the head's and not drawn here.
   */
  head?: ReactNode;
  /** The week row's name between ‹ and › ("Vecka 47 · 16–22 nov"). Absent: the range alone. */
  weekLabel?: ReactNode;
  /** A quiet control before + and ⋯ on the first row: the view's `today` button, shown when the week lacks today. */
  actions?: ReactNode;
  /** The room's ⋯ on the title row (x 383 as in every room head). */
  more?: ReactNode;
  /** What ⋯ opens, under the title row and above the week. */
  panel?: ReactNode;
  /** What + opens: under the week, where the day's content starts, so opening it never moves the week. */
  below?: ReactNode;
};

/**
 * The shown week in words, between ‹ and ›: "2–8 nov" in one month, "29 okt–4 nov" across two (the
 * arrows step a week, and the line names it). Empty for an empty week.
 */
export function weekRange(days: readonly string[], locale: string): string {
  const first = days[0];
  const last = days.at(-1);
  if (!first || !last) return "";
  const end = formatShortDate(last, locale);
  const start =
    first.slice(0, 7) === last.slice(0, 7)
      ? String(Number(first.slice(8, 10)))
      : formatShortDate(first, locale);
  return `${start}–${end}`;
}

/**
 * The seven days (YYYY-MM-DD, Monday first) the strip shows for `selected`: its calendar week, Monday to Sunday, the
 * same week the week view shows, so ‹ › step the same weeks in both views and the strip never slides. Days after
 * today are drawn but cannot be chosen. Empty for a malformed date.
 */
export function stripDays(selected: string): string[] {
  return weekDates(selected);
}

/** The short weekday name, "mån" in Swedish and "Mon" in English. */
export function weekdayShort(date: string, locale: string): string {
  return new Date(`${date}T00:00:00Z`).toLocaleDateString(locale, {
    weekday: "short",
    timeZone: "UTC",
  });
}

/** The weekday in full in lower case, "torsdag". */
function weekdayLong(date: string, locale: string): string {
  return new Date(`${date}T00:00:00Z`).toLocaleDateString(locale, {
    weekday: "long",
    timeZone: "UTC",
  });
}

/** The month in full in lower case, "oktober". */
function monthLong(date: string, locale: string): string {
  return new Date(`${date}T00:00:00Z`).toLocaleDateString(locale, {
    month: "long",
    timeZone: "UTC",
  });
}

/** The day of the month without a leading zero: "26", "1". */
function dayOfMonth(date: string): string {
  return String(Number(date.slice(8, 10)));
}

/**
 * A seven-day strip for the journal day view (`stripDays`). Each day shows its short weekday and day number; today
 * says `today` in place of its weekday, the selected day is filled, and a 6 px dot under the number marks each day
 * with entries (journal.css). The strip chooses the day; ‹ › on the title row and a horizontal swipe on the strip step a
 * week (O and F read day steps beside a strip of days as two ways to do one thing), and the arrow keys
 * step a day. A day after today is never offered: a step forward stops at today. Journal text never reaches the component: it only receives dates,
 * so nothing here can send text to the model.
 */
export function DayStrip({
  selected,
  unmarked = false,
  today,
  daysWithEntries,
  labels: t,
  disabled = false,
  onSelect,
  heading,
  head,
  weekLabel,
  actions,
  more,
  panel,
  below,
}: DayStripProps) {
  const strip = useRef<HTMLDivElement>(null);
  const weekList = useRef<HTMLOListElement>(null);
  // Set by an arrow key so focus follows the day to its new button after the parent re-renders.
  const followFocus = useRef(false);
  // Where the current touch started, for a swipe that steps one week.
  const touchStart = useRef<{ x: number; y: number } | null>(null);
  const days = stripDays(selected);
  const marked = new Set(unmarked ? [] : daysWithEntries);
  // Today when it is in the shown week, otherwise the selected day. Below ~250 px, and at large text in a phone frame,
  // the week scrolls (journal.css); then this day is centred in it. Keyed on this value, so a tap in the same week does not move it.
  const scrollTarget = days.includes(today) ? today : selected;
  // › is off in the week that holds today. Both arrows always show.
  const atToday = days.includes(today) || selected >= today;

  useEffect(() => {
    if (!followFocus.current) return;
    followFocus.current = false;
    const buttons =
      strip.current?.querySelectorAll<HTMLButtonElement>("button[data-date]");
    for (const button of buttons ?? []) {
      if (button.dataset.date === selected) button.focus();
    }
  }, [selected]);

  useEffect(() => {
    const list = weekList.current;
    const button = list?.querySelector<HTMLElement>(
      `button[data-date="${scrollTarget}"]`,
    );
    if (list && button)
      list.scrollLeft =
        button.offsetLeft - (list.clientWidth - button.offsetWidth) / 2;
  }, [scrollTarget]);

  function step(from: string, delta: number, keepFocus: boolean) {
    // A day after today is not selectable, so a step past today stops on today (ISO dates compare as text).
    const ahead = shiftDate(from, delta);
    const target = ahead > today ? today : ahead;
    if (target === from) return;
    followFocus.current = keepFocus;
    onSelect(target);
  }

  function onDayKey(event: KeyboardEvent<HTMLButtonElement>, date: string) {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    if (disabled) return;
    step(date, event.key === "ArrowLeft" ? -1 : 1, true);
  }

  function onSwipeStart(event: TouchEvent<HTMLDivElement>) {
    const touch = event.touches[0];
    touchStart.current = touch ? { x: touch.clientX, y: touch.clientY } : null;
  }

  // Swiping left shows the next week, swiping right the previous one. A mostly vertical move is a page scroll.
  function onSwipeEnd(event: TouchEvent<HTMLDivElement>) {
    const start = touchStart.current;
    touchStart.current = null;
    const touch = event.changedTouches[0];
    if (!start || !touch || disabled) return;
    // A week that scrolls inside itself (large text, a narrow frame) takes a sideways swipe as its own scroll.
    const list = weekList.current;
    if (list && list.scrollWidth > list.clientWidth + 1) return;
    const dx = touch.clientX - start.x;
    const dy = touch.clientY - start.y;
    if (Math.abs(dx) < swipeMinimum || Math.abs(dx) < Math.abs(dy) * 2) return;
    // A swipe forward in the week that holds today does what › does there: nothing.
    if (dx < 0 && atToday) return;
    step(selected, dx < 0 ? 7 : -7, false);
  }

  // The week row under the title row: "‹ 29 okt–4 nov ›", the
  // arrows (48 × 48, glyph 24) right beside the week they step, at the start of the row with ‹'s glyph on the content
  // edge, the same form at every width and text size. On today › is aria-disabled in the tertiary tone (journal.css)
  // and stays drawn; step() ignores a press past today. `today`, when the week lacks today, follows ›.
  const arrows = (
    <div className="sk-day-strip-weekrow">
      <button
        type="button"
        className="sk-iconbtn sk-day-strip-arrow"
        aria-label={t.previousWeek}
        disabled={disabled}
        onClick={() => step(selected, -7, false)}
      >
        <ChevronLeftIcon />
      </button>
      {days.length > 0 && (
        <p className="journal-day-range">
          {weekLabel ?? weekRange(days, t.dateLocale)}
        </p>
      )}
      <button
        type="button"
        className="sk-iconbtn sk-day-strip-arrow"
        aria-label={t.nextWeek}
        aria-disabled={atToday || undefined}
        disabled={disabled}
        onClick={() => !atToday && step(selected, 7, false)}
      >
        <ChevronRightIcon />
      </button>
    </div>
  );

  return (
    <>
      {/* The first row: the room head (or, without it, the title "Tisdag 3 november" with `today`, + and ⋯ at its
          end); under it the week row. */}
      {head}
      <div className="sk-day-strip-head" data-tabs={head ? "true" : undefined}>
        {head ? null : (
          <>
            <div className="sk-day-strip-title">{heading}</div>
            <div className="sk-day-strip-tools">
              {actions}
              {more}
            </div>
          </>
        )}
        {arrows}
      </div>
      {panel}
      <div
        ref={strip}
        className="sk-day-strip"
        data-unmarked={unmarked ? "true" : undefined}
        role="group"
        aria-label={t.group}
        onTouchStart={onSwipeStart}
        onTouchEnd={onSwipeEnd}
        onTouchCancel={() => {
          touchStart.current = null;
        }}
      >
        {days.length > 0 && (
          <ol ref={weekList} className="sk-day-strip-week">
            {days.map((date) => {
              const anchor = date === selected;
              const active = anchor && !unmarked;
              const hasEntries = marked.has(date);
              const isToday = date === today;
              // The name starts with the two words the cell shows (its weekday, or `today`, and the day number) so
              // it contains the visible label (WCAG 2.5.3), then the month, the weekday in full when the cell says
              // `today`, `selected` for the selected day and `withEntries` for a marked day.
              const name = [
                `${isToday ? t.todayMarker : weekdayShort(date, t.dateLocale)} ${dayOfMonth(date)} ${monthLong(date, t.dateLocale)}`,
                isToday ? weekdayLong(date, t.dateLocale) : undefined,
                active ? t.selected : undefined,
                hasEntries ? t.withEntries : undefined,
              ]
                .filter(Boolean)
                .join(", ");
              return (
                <li key={date}>
                  <button
                    type="button"
                    className="sk-day-strip-day"
                    data-date={date}
                    data-has-entries={hasEntries ? "true" : undefined}
                    data-today={isToday ? "true" : undefined}
                    aria-current={active ? "date" : undefined}
                    aria-label={name}
                    aria-keyshortcuts="ArrowLeft ArrowRight"
                    tabIndex={anchor ? 0 : -1}
                    disabled={disabled || date > today}
                    style={dayStyle}
                    onClick={() => onSelect(date)}
                    onKeyDown={(event) => onDayKey(event, date)}
                  >
                    {/* Today says `today` where the weekday is, so every cell keeps the same three rows. */}
                    <span
                      className={
                        isToday
                          ? "sk-day-strip-weekday sk-day-strip-today"
                          : "sk-day-strip-weekday"
                      }
                      aria-hidden="true"
                    >
                      {isToday
                        ? t.todayMarker
                        : weekdayShort(date, t.dateLocale)}
                    </span>{" "}
                    <span className="sk-day-strip-number" aria-hidden="true">
                      {dayOfMonth(date)}
                    </span>
                    {/* The marker row is always there, so the numbers line up; the dot is centred under the number. */}
                    <span className="sk-day-strip-marker" aria-hidden="true">
                      {hasEntries ? (
                        <span className="sk-day-strip-dot" />
                      ) : null}
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>
        )}
        {/* The date is in the view heading; this region only announces a change to screen readers. */}
        <span className="sk-day-strip-live" aria-live="polite">
          {unmarked ? "" : formatCalendarDate(selected, t.dateLocale)}
        </span>
      </div>
      {head && heading ? (
        <div className="sk-day-strip-title sk-day-strip-title--below">
          {heading}
        </div>
      ) : null}
      {below}
    </>
  );
}
