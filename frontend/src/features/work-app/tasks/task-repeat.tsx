import { ownerDayNumber, parseDueDay, workDate } from "../../mcp-apps/ui/due";
import { ChipChoices, PropLabel } from "./chip-choices";
import { dayText, nextOccurrenceDay, weekdayOf } from "./repeat-next";
import type { TaskPlaceLabels } from "./task-place-labels";
import type { WorkTask, WorkTaskChanges } from "../transport/transport";

type Rule = NonNullable<WorkTask["recurrence"]>;
type Choice =
  "daily" | "weekly" | "biweekly" | "monthly" | "lastWeekday" | "yearly";

/** The picker's value for a rule it has no word for; choosing it changes nothing. */
const CURRENT = "current";

/**
 * The picker's name for a rule, or null when it has none: every day, week (on the chosen weekdays, if any), second week,
 * month, last weekday of the month or year, with no day of month or end date.
 */
function choiceOf(rule: Rule | null | undefined): Choice | null {
  if (!rule || rule.day_of_month != null || rule.until != null) return null;
  if (rule.frequency === "weekly") {
    if (rule.interval === 1) return "weekly";
    return rule.interval === 2 ? "biweekly" : null;
  }
  if ((rule.weekdays ?? []).length > 0 || rule.interval > 1) return null;
  if (rule.frequency === "monthly")
    return rule.last_weekday ? "lastWeekday" : "monthly";
  return rule.frequency;
}

/**
 * The update_task change a picker value stands for: no rule is null, a name is the rule it names. Changing between the
 * weekly rules keeps the weekdays the Task already repeats on.
 */
export function repeatChanges(
  value: string,
  current?: Rule | null,
): WorkTaskChanges {
  const weekdays =
    current?.frequency === "weekly" ? (current.weekdays ?? []) : [];
  const kept = weekdays.length > 0 ? { weekdays } : {};
  switch (value) {
    case "none":
      return { recurrence: null };
    case "weekly":
      return { recurrence: { frequency: "weekly", ...kept } };
    case "biweekly":
      return { recurrence: { frequency: "weekly", interval: 2, ...kept } };
    case "lastWeekday":
      return { recurrence: { frequency: "monthly", last_weekday: true } };
    default:
      return {
        recurrence: { frequency: value as "daily" | "monthly" | "yearly" },
      };
  }
}

/** The rule with one weekday more or fewer; the rest of the rule stays as it is. */
function toggledWeekday(rule: Rule, day: number): WorkTaskChanges {
  const had = rule.weekdays ?? [];
  const weekdays = had.includes(day)
    ? had.filter((d) => d !== day)
    : [...had, day].sort((x, y) => x - y);
  return {
    recurrence: {
      frequency: "weekly",
      interval: rule.interval,
      weekdays,
      ...(rule.until ? { until: rule.until } : {}),
    },
  };
}

/**
 * The Task's own repeat rule as a chip on the place row: (the repeat text). The rule belongs to the Task, not
 * to a Process. A tap unfolds the rules as chips under the row (ChipChoices): not repeating, every day, week, other
 * week, month, last weekday of the month or year. One tap on another chip is one update_task through `onChoose` and
 * folds the chips away. A weekly rule also shows the seven weekdays as toggle chips under the row; each tap is one
 * update_task with the weekdays changed, and none ticked repeats a week after each completion. A rule the chips have
 * no word for (every 3rd week, a day of the month, an end date) stands as its own ticked chip, "… (current)", so
 * opening the choices never loses it. Where the host cannot write (the phone), a rule shows as a plain read-only chip
 * and a Task without one shows nothing. Escape folds the chips and returns focus to the chip; opening them puts focus
 * on the ticked one.
 */
export function TaskRepeat({
  rule,
  title,
  words,
  writable,
  busy,
  dueAt,
  onChoose,
}: {
  rule: WorkTask["recurrence"];
  title: string;
  words: TaskPlaceLabels;
  writable: boolean;
  busy: boolean;
  /** The Task's due date, which a monthly rule counts its months from. */
  dueAt?: string | null;
  onChoose: (changes: WorkTaskChanges) => void;
}) {
  const current = rule ?? null;
  const choice = choiceOf(current);
  // The row's value: the rule in short ("Varje måndag"), its name ("Upprepas") stands before it.
  const shown = current
    ? capitalFirst(words.repeatsShort(current))
    : words.repeatNever;

  if (!writable)
    return current ? (
      <span className="sk-chip work-prop-chip work-prop-static">
        <PropLabel text={words.props.repeat} />
        <span>{shown}</span>
      </span>
    ) : null;

  const value = current ? (choice ?? CURRENT) : "none";
  const options: { value: string; label: string }[] = [
    { value: "none", label: words.repeatOptions.none },
    { value: "daily", label: words.repeatOptions.daily },
    { value: "weekly", label: words.repeatOptions.weekly },
    { value: "biweekly", label: words.repeatOptions.biweekly },
    { value: "monthly", label: words.repeatOptions.monthly },
    { value: "lastWeekday", label: words.repeatOptions.lastWeekday },
    { value: "yearly", label: words.repeatOptions.yearly },
    ...(value === CURRENT && current
      ? [{ value: CURRENT, label: words.repeatCurrent(words.repeats(current)) }]
      : []),
  ];
  return (
    <>
      <ChipChoices
        // The name holds the row's visible text ("Upprepas varje vecka", axe label-content-name-mismatch).
        name={`${words.changeRepeat}: ${words.props.repeat} ${current ? words.repeatsShort(current) : words.repeatNever.toLowerCase()}`}
        label={words.props.repeat}
        text={shown}
        groupLabel={words.repeatPickerFor(title)}
        options={options}
        value={value}
        busy={busy}
        onChoose={(next) => onChoose(repeatChanges(next, current))}
      />
      {current && (
        <div
          role="group"
          aria-label={words.repeatDetailsFor(title)}
          className="work-repeat-details"
        >
          {current.frequency === "weekly" && (
            <WeekdayChoices
              rule={current}
              title={title}
              words={words}
              busy={busy}
              onChoose={onChoose}
            />
          )}
          <NextLine rule={current} dueAt={dueAt} words={words} />
        </div>
      )}
    </>
  );
}

/**
 * The seven weekday buttons of a weekly rule under their question, on one row of seven equal columns. Two letters stand
 * on the button when the row is narrow (a phone at 320 px); the full name is always its accessible name. With none
 * chosen, a hint says what the server does: it repeats a whole number of weeks after the Task is completed.
 */
function WeekdayChoices({
  rule,
  title,
  words,
  busy,
  onChoose,
}: {
  rule: Rule;
  title: string;
  words: TaskPlaceLabels;
  busy: boolean;
  onChoose: (changes: WorkTaskChanges) => void;
}) {
  const chosen = rule.weekdays ?? [];
  return (
    <div className="work-weekday-block">
      <p className="work-repeat-question">{words.weekdaysQuestion}</p>
      <div
        role="group"
        aria-label={words.repeatWeekdaysFor(title)}
        className="work-weekday-choices"
      >
        {words.weekdayNames.short.map((name, day) => (
          <button
            key={name}
            type="button"
            className="sk-chip"
            aria-label={words.weekdayNames.full[day]}
            aria-pressed={chosen.includes(day)}
            disabled={busy}
            onClick={() => onChoose(toggledWeekday(rule, day))}
          >
            <span className="work-day-long">{name}</span>
            <span className="work-day-short" aria-hidden="true">
              {name.slice(0, 2)}
            </span>
          </button>
        ))}
      </div>
      {chosen.length === 0 && (
        <p className="work-repeat-hint">{words.noWeekdayHint(rule.interval)}</p>
      )}
    </div>
  );
}

/** "Nästa gång: tis 24 nov": when the rule falls next if the Task is completed today; nothing when the rule has ended. */
function NextLine({
  rule,
  dueAt,
  words,
}: {
  rule: Rule;
  dueAt: string | null | undefined;
  words: TaskPlaceLabels;
}) {
  const now = new Date();
  const next = nextOccurrenceDay(rule, ownerDayNumber(now), parseDueDay(dueAt));
  if (next === null) return null;
  const date = workDate(dayText(next), now, words.dateLocale, {
    inline: true,
    relative: false,
    weekday: false,
  });
  const weekday = words.weekdayNames.short[weekdayOf(next)];
  return (
    <p className="work-repeat-next">{words.repeatNext(`${weekday} ${date}`)}</p>
  );
}

/** The text with its first letter in capitals: the short rule starts a row's value. */
function capitalFirst(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}
