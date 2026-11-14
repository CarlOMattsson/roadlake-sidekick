import { hierarchyDetailLabelsFor } from "../hierarchy/hierarchy-detail-labels";
import { priorityLabel, type WorkLabels } from "../shared/labels";
import type { WorkTask, WorkTaskChanges } from "../transport/transport";
import { ChipChoices } from "./chip-choices";
import { PRIORITY_CHOICES, isPriorityChoice } from "./task-edit";

/**
 * The Task's priority as a property chip beside its place and repeat rule: the `priority` label with its value, the word `high` in the
 * warning colour the rows' `high` has. A tap unfolds `low`, `normal` and `high` (ChipChoices); a choice is one update_task
 * through `onChoose`. A value the chips have no word for keeps its own ticked chip, so opening them never loses it.
 * Where the host cannot write (the phone), only a high priority shows, as a plain chip.
 */
export function TaskPriority({
  task,
  labels: t,
  writable,
  busy,
  onChoose,
}: {
  task: WorkTask;
  labels: WorkLabels;
  writable: boolean;
  busy: boolean;
  onChoose: (changes: WorkTaskChanges) => void;
}) {
  const value = task.priority ?? "normal";
  const word = priorityLabel(t, value);
  const text = (
    <>
      {t.priority}:{" "}
      <span
        className="work-card-priority"
        data-priority={value === "high" ? "high" : undefined}
      >
        {word}
      </span>
    </>
  );
  if (!writable)
    return value === "high" ? (
      <span className="sk-chip work-prop-chip work-prop-static">
        <span>{text}</span>
      </span>
    ) : null;
  const options = [
    ...PRIORITY_CHOICES.map((choice) => ({
      value: choice,
      label: priorityLabel(t, choice),
    })),
    ...(isPriorityChoice(value) ? [] : [{ value, label: word }]),
  ];
  return (
    <ChipChoices
      name={`${hierarchyDetailLabelsFor(t.dateLocale).changePriority}: ${word}`}
      text={text}
      groupLabel={t.priority}
      options={options}
      value={value}
      busy={busy}
      onChoose={(next) => {
        if (isPriorityChoice(next)) onChoose({ priority: next });
      }}
    />
  );
}
