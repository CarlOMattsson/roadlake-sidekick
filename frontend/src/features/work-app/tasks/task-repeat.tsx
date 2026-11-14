import type { RecurrenceRecord } from "../../../lib/mcp/tool-results.generated";
import { ChipChoices } from "./chip-choices";
import type { TaskPlaceLabels } from "./task-place-labels";
import type { WorkTask, WorkTaskChanges } from "../transport/transport";

type Rule = NonNullable<WorkTask["recurrence"]>;
type Simple = RecurrenceRecord["frequency"];

/** The picker's value for a rule it has no word for; choosing it changes nothing. */
const CURRENT = "current";

/** A rule the picker names: every day, week, month or year, with no weekdays, day of month or end date. */
function simpleFrequency(rule: Rule | null | undefined): Simple | null {
  if (!rule) return null;
  const plain =
    rule.interval <= 1 &&
    (rule.weekdays ?? []).length === 0 &&
    rule.day_of_month == null &&
    rule.until == null;
  return plain ? rule.frequency : null;
}

/** The update_task change a picker value stands for: no rule is null, a frequency is a rule with only that. */
export function repeatChanges(value: string): WorkTaskChanges {
  return value === "none"
    ? { recurrence: null }
    : { recurrence: { frequency: value as Simple } };
}

/**
 * The Task's own repeat rule as a chip on the place row: (the repeat text). The rule belongs to the Task, not
 * to a Process. A tap unfolds the rules as chips under the row (ChipChoices): not repeating, every day, week, month or
 * year. One tap on another chip is one update_task through `onChoose` and folds the chips away. A rule the chips have no word for (every 2nd week, chosen
 * weekdays, an end date) stands as its own ticked chip, "… (current)", so opening the choices never loses it. Where
 * the host cannot write (the phone), a rule shows as a plain read-only chip and a Task without one shows nothing.
 * Escape folds the chips and returns focus to the chip; opening them puts focus on the ticked one.
 */
export function TaskRepeat({
  rule,
  title,
  words,
  writable,
  busy,
  onChoose,
}: {
  rule: WorkTask["recurrence"];
  title: string;
  words: TaskPlaceLabels;
  writable: boolean;
  busy: boolean;
  onChoose: (changes: WorkTaskChanges) => void;
}) {
  const current = rule ?? null;
  const simple = simpleFrequency(current);
  const text = current ? words.repeats(current) : words.repeatsNot;

  if (!writable)
    return current ? (
      <span className="sk-chip work-prop-chip work-prop-static">{text}</span>
    ) : null;

  const value = current ? (simple ?? CURRENT) : "none";
  const options: { value: string; label: string }[] = [
    { value: "none", label: words.repeatOptions.none },
    { value: "daily", label: words.repeatOptions.daily },
    { value: "weekly", label: words.repeatOptions.weekly },
    { value: "monthly", label: words.repeatOptions.monthly },
    { value: "yearly", label: words.repeatOptions.yearly },
    ...(value === CURRENT && current
      ? [{ value: CURRENT, label: words.repeatCurrent(words.repeats(current)) }]
      : []),
  ];
  return (
    <ChipChoices
      name={`${words.changeRepeat}: ${text}`}
      text={text}
      groupLabel={words.repeatPickerFor(title)}
      options={options}
      value={value}
      busy={busy}
      onChoose={(next) => onChoose(repeatChanges(next))}
    />
  );
}
