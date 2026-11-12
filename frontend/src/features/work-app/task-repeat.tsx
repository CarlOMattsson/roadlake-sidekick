import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import type { RecurrenceRecord } from "../../lib/mcp/tool-results.generated";
import { ChevronDownIcon } from "../mcp-apps/ui/icons";
import type { TaskPlaceLabels } from "./task-place-labels";
import type { WorkTask, WorkTaskChanges } from "./transport";

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
 * The Task's own repeat rule as a chip on the place row: "Upprepas varje vecka ⌄". The rule belongs to the Task, not
 * to a Process. A tap unfolds the rules as chips under the row, the current one ticked, as the row menu's Status and
 * Date (uc-4): not repeating, every day, week, month or year. One tap on another chip is one
 * update_task through `onChoose` and folds the chips away. A rule the chips have no word for (every 2nd week, chosen
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
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const chip = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  // Opening the choices puts focus on the ticked one, so Enter keeps it and Tab walks the others.
  useEffect(() => {
    if (open)
      panel.current
        ?.querySelector<HTMLElement>('[aria-pressed="true"]')
        ?.focus({ preventScroll: true });
  }, [open]);
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
  function close() {
    setOpen(false);
    chip.current?.focus();
  }
  function onKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key !== "Escape" || !open) return;
    event.preventDefault();
    event.stopPropagation();
    close();
  }
  function choose(next: string) {
    if (next === CURRENT || next === value) return close();
    setOpen(false);
    onChoose(repeatChanges(next));
  }

  return (
    <>
      <button
        ref={chip}
        type="button"
        className="sk-chip work-prop-chip"
        aria-label={`${words.changeRepeat}: ${text}`}
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        disabled={busy}
        onClick={() => setOpen(!open)}
        onKeyDown={onKeyDown}
      >
        <span>{text}</span>
        <ChevronDownIcon size={16} />
      </button>
      {open && (
        // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions -- Escape bubbling up from the chips inside; the group itself is not a control.
        <div
          ref={panel}
          id={panelId}
          role="group"
          aria-label={words.repeatPickerFor(title)}
          className="work-repeat-choices"
          onKeyDown={onKeyDown}
        >
          {options.map((option) => (
            <button
              key={option.value}
              type="button"
              className="sk-chip"
              aria-pressed={option.value === value}
              disabled={busy}
              onClick={() => choose(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>
      )}
    </>
  );
}
