import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { ChevronLeftIcon, ChevronRightIcon } from "../mcp-apps/ui/icons";
import { formatLongDate, shiftDate, weekStart } from "./dates";
import { useEntryDates } from "./day-frame-hooks";
import { weekdayShort } from "./day-strip";
import type { DayStripLabels } from "./day-strip-labels";
import type { JournalTransport } from "./transport";
import "./month-rail.css";

/** The seven columns and six rows of the grid: a month never needs more. */
const GRID_DAYS = 42;

/** The month ("2026-11") a calendar date is in. */
function monthOf(date: string): string {
  return date.slice(0, 7);
}

/** The month `delta` months from `month` ("2026-11"). */
function shiftMonth(month: string, delta: number): string {
  const [year, number] = month.split("-").map(Number);
  return new Date(Date.UTC(year ?? 1970, (number ?? 1) - 1 + delta, 1))
    .toISOString()
    .slice(0, 7);
}

/** The 42 days of the grid: whole weeks, Monday first, from the week that holds the 1st. */
function monthGrid(month: string): string[] {
  const first = weekStart(`${month}-01`);
  return Array.from({ length: GRID_DAYS }, (_, index) =>
    shiftDate(first, index),
  );
}

/** "November 2026" in the app's language, with its first letter capitalised ("november 2026" in Swedish). */
function monthTitle(month: string, locale: string): string {
  const text = new Date(`${month}-01T00:00:00Z`).toLocaleDateString(locale, {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
  return text.charAt(0).toLocaleUpperCase(locale) + text.slice(1);
}

export type MonthRailProps = {
  transport: JournalTransport;
  /** A changed value reads the month's dots again (a write elsewhere). */
  refreshKey?: number;
  /** The shown day (or, in the week view, the week's Monday): the month opens on it and follows it. */
  selected: string;
  /** No day is chosen (a tag filter lists many days): no cell is filled and no dot is drawn. */
  unmarked?: boolean;
  /** The seven days of the week view: all are filled as the chosen days. */
  week?: readonly string[];
  /** Today, YYYY-MM-DD. Passed in so the calendar never reads the clock. */
  today: string;
  /** The day the view has already read: it is newer than the month's read, so it decides its own dot. */
  known?: { date: string; hasEntries: boolean };
  labels: DayStripLabels;
  disabled?: boolean;
  onSelect: (date: string) => void;
};

/**
 * The month calendar of the Journal's list pane in a wide frame (desktop spec 3.2): ‹ › together on the left at a fixed
 * place with the month's name, the weekdays, and 42 days in whole weeks. A dot marks a day with entries, the chosen day
 * is filled, today is inked, days outside the month are muted and days after today cannot be chosen, as in the day
 * strip. The arrows step a month and the calendar follows the shown day; ↑ and ↓ move the focus a week, and ← and →
 * are the day view's own keys (a day step), which keep the focus on the chosen day. Journal text never reaches it: it
 * receives dates only.
 */
export function MonthRail({
  transport,
  refreshKey,
  selected,
  unmarked = false,
  week,
  today,
  known,
  labels: t,
  disabled = false,
  onSelect,
}: MonthRailProps) {
  const root = useRef<HTMLDivElement>(null);
  // Set by ← or → so that the focus follows the chosen day to its new button once the view has moved.
  const followFocus = useRef(false);
  const [month, setMonth] = useState(monthOf(selected));
  const [seen, setSeen] = useState(selected);
  // A new shown day (a key, the week view, a link) opens the month it is in.
  if (seen !== selected) {
    setSeen(selected);
    setMonth(monthOf(selected));
  }
  const days = monthGrid(month);
  const fromDay = days[0];
  const toDay = days[GRID_DAYS - 1];
  const read = useEntryDates(transport, fromDay, toDay, refreshKey);
  const marked = new Set(unmarked ? [] : read);
  if (known) {
    marked.delete(known.date);
    if (known.hasEntries && !unmarked) marked.add(known.date);
  }
  const weekDays = new Set(unmarked ? [] : (week ?? []));
  // The one tab stop: the chosen day, else today, else the 1st; never a day after today, which cannot be pressed.
  const tabStop = [selected, today, `${month}-01`].find(
    (date) => days.includes(date) && date <= today,
  );
  const latest = month >= monthOf(today);

  useEffect(() => {
    if (!followFocus.current) return;
    followFocus.current = false;
    root.current
      ?.querySelector<HTMLButtonElement>(`button[data-date="${selected}"]`)
      ?.focus();
  }, [selected]);

  function onDayKey(event: KeyboardEvent<HTMLButtonElement>, date: string) {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      followFocus.current = true;
      return;
    }
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
    event.preventDefault();
    const target = shiftDate(date, event.key === "ArrowUp" ? -7 : 7);
    if (target > today) return;
    root.current
      ?.querySelector<HTMLButtonElement>(`button[data-date="${target}"]`)
      ?.focus();
  }

  return (
    <div
      ref={root}
      className="sk-month-rail"
      role="group"
      aria-label={t.calendar}
    >
      <div className="sk-month-head">
        <button
          type="button"
          className="sk-iconbtn sk-month-step"
          aria-label={t.previousMonth}
          onClick={() => setMonth(shiftMonth(month, -1))}
        >
          <ChevronLeftIcon />
        </button>
        <button
          type="button"
          className="sk-iconbtn sk-month-step"
          aria-label={t.nextMonth}
          aria-disabled={latest || undefined}
          onClick={() => {
            if (!latest) setMonth(shiftMonth(month, 1));
          }}
        >
          <ChevronRightIcon />
        </button>
        <p className="sk-month-title" aria-live="polite">
          {monthTitle(month, t.dateLocale)}
        </p>
      </div>
      <div className="sk-month-grid">
        {days.slice(0, 7).map((date) => (
          <span key={date} className="sk-month-weekday" aria-hidden="true">
            {weekdayShort(date, t.dateLocale)}
          </span>
        ))}
        {days.map((date, index) => {
          const active = !unmarked && !week && date === selected;
          const inWeek = weekDays.has(date);
          const hasEntries = marked.has(date);
          const isToday = date === today;
          // The name is the long date ("onsdag 18 november"), which holds the day number the cell shows (WCAG 2.5.3).
          const name = [
            formatLongDate(date, t.dateLocale),
            isToday ? t.todayMarker : undefined,
            active || inWeek ? t.selected : undefined,
            hasEntries ? t.withEntries : undefined,
          ]
            .filter(Boolean)
            .join(", ");
          const column = index % 7;
          return (
            // Keyed by place, so the focus stays where it is when the month changes under it.
            <button
              key={index}
              type="button"
              className="sk-month-day"
              data-date={date}
              data-outside={monthOf(date) !== month ? "true" : undefined}
              data-has-entries={hasEntries ? "true" : undefined}
              data-today={isToday ? "true" : undefined}
              data-week={
                inWeek
                  ? column === 0
                    ? "start"
                    : column === 6
                      ? "end"
                      : "middle"
                  : undefined
              }
              aria-current={active ? "date" : undefined}
              aria-label={name}
              aria-keyshortcuts="ArrowLeft ArrowRight"
              tabIndex={date === tabStop ? 0 : -1}
              disabled={disabled || date > today}
              onClick={() => onSelect(date)}
              onKeyDown={(event) => onDayKey(event, date)}
            >
              <span className="sk-month-number" aria-hidden="true">
                {Number(date.slice(8, 10))}
              </span>
              {hasEntries ? (
                <span className="sk-month-dot" aria-hidden="true" />
              ) : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}
