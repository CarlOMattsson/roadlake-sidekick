import { useEffect, useId, useRef, useState } from "react";
import { priorityLabel, type WorkLabels } from "./labels";
import {
  isCompleteDate,
  keepEdits,
  titleProblem,
  type TitleProblem,
} from "./fields";
import { DESCRIPTION_MAX_LENGTH } from "./project-edit";
import {
  parseDueDay,
  ownerDayPlus,
  ownerDaysToNextMonday,
  ownerEndOfDay,
} from "../mcp-apps/ui/due";
import { type WorkTask, type WorkTaskChanges } from "./transport";
import { useUnsavedGuard } from "../mcp-apps/unsaved-guard";

/** The priorities the form offers; a Task with urgent keeps that value, shown as an extra option. */
type PriorityChoice = NonNullable<WorkTaskChanges["priority"]>;
const PRIORITY_CHOICES = [
  "low",
  "normal",
  "high",
] as const satisfies readonly PriorityChoice[];
function isPriorityChoice(value: string): value is PriorityChoice {
  return (PRIORITY_CHOICES as readonly string[]).includes(value);
}

/**
 * Editable Task fields as the form shows them; due is an owner-zone YYYY-MM-DD or "". Priority is the raw
 * value ("normal" when the Task has none). The status is not here: the status choice in the Task
 * view writes it.
 */
export type TaskDraft = {
  title: string;
  description: string;
  priority: string;
  due: string;
};
/**
 * `base` is the Task as the user last saw it (opening the editor, or the latest reload). A field
 * counts as changed only while it differs from base, so an edit reverted by hand is not sent.
 * `dueIncomplete` is set while the date input holds a partial entry the browser cannot read.
 */
export type DraftState = {
  values: TaskDraft;
  base: TaskDraft;
  dueIncomplete: boolean;
};
export type FieldProblem =
  | TitleProblem
  | "descriptionTooLong"
  | "dueIncomplete";
type DraftField = keyof TaskDraft;
/** The date shortcuts above the due date field: today, tomorrow, the next Monday, or no date. */
type DueShortcut = "today" | "tomorrow" | "nextWeek" | "none";

export function draftFromTask(task: WorkTask): TaskDraft {
  return {
    title: task.title,
    description: task.description ?? "",
    priority: task.priority ?? "normal",
    due: dateInputValue(task.due_at),
  };
}

/** The owner calendar day of a due instant as YYYY-MM-DD for a date input; "" when there is no due date. */
export function dateInputValue(iso: string | null): string {
  const day = parseDueDay(iso);
  if (day === null) return "";
  return new Date(day * 86_400_000).toISOString().slice(0, 10);
}

/**
 * The date input value a shortcut sets, counted from `now`. The next Monday is the same day the
 * agenda's "Next week" moves an overdue Task to (the Monday after this week's Monday).
 */
function dueShortcutValue(shortcut: DueShortcut, now: Date): string {
  if (shortcut === "none") return "";
  const days =
    shortcut === "today"
      ? 0
      : shortcut === "tomorrow"
        ? 1
        : ownerDaysToNextMonday(now);
  return ownerDayPlus(now, days);
}

/**
 * due_at is an instant (date-time), not a calendar date. The chosen day is stored as 23:59 on that day in
 * the owner's zone, the one the app shows dates in, whatever the browser's zone is; `dateInputValue`
 * reads the same owner day back, so an untouched field never changes the due. "" clears the date and yields null.
 */
export function dueAtFromDateInput(value: string): string | null {
  if (!value) return null;
  return ownerEndOfDay(value);
}

/** The first field problem that blocks Save, or none. */
export function fieldProblem(state: DraftState): FieldProblem | undefined {
  const title = titleProblem(state.values.title);
  if (title) return title;
  if (Array.from(state.values.description).length > DESCRIPTION_MAX_LENGTH)
    return "descriptionTooLong";
  if (
    state.dueIncomplete ||
    (state.values.due !== "" && !isCompleteDate(state.values.due))
  )
    return "dueIncomplete";
  return undefined;
}

/**
 * Only the fields that differ from what the user last saw. A field the user did not change is
 * never sent, so a reload cannot overwrite someone else's change. An incomplete date is not a
 * change; Save is blocked for it instead. An emptied description is sent as null, which clears it.
 */
export function changedFields(state: DraftState): WorkTaskChanges {
  const { values, base } = state;
  const changes: WorkTaskChanges = {};
  if (values.title.trim() !== base.title.trim())
    changes.title = values.title.trim();
  if (values.description.trim() !== base.description.trim())
    changes.description = values.description.trim() || null;
  if (values.priority !== base.priority && isPriorityChoice(values.priority))
    changes.priority = values.priority;
  if (!state.dueIncomplete && values.due !== base.due)
    changes.due_at = dueAtFromDateInput(values.due);
  return changes;
}

/**
 * After a reload the base becomes the latest Task. A field the user changed keeps the user's
 * value so it can be saved again; an untouched field follows the latest Task.
 */
function follow(current: DraftState, task: WorkTask): DraftState {
  const fresh = draftFromTask(task);
  return {
    values: keepEdits(current, fresh),
    base: fresh,
    dueIncomplete: current.dueIncomplete,
  };
}

export function TaskEditor({
  task,
  busy,
  saveFailed,
  onSave,
  onCancel,
  labels: t,
}: {
  task: WorkTask;
  busy: boolean;
  saveFailed: boolean;
  onSave: (changes: WorkTaskChanges) => void;
  onCancel: () => void;
  labels: WorkLabels;
}) {
  const [state, setState] = useState<DraftState>(() => {
    const initial = draftFromTask(task);
    return { values: initial, base: initial, dueIncomplete: false };
  });
  const [seenTask, setSeenTask] = useState(task);
  const [problem, setProblem] = useState<FieldProblem>();
  useUnsavedGuard(
    state.dueIncomplete || Object.keys(changedFields(state)).length > 0,
  );
  const titleInput = useRef<HTMLInputElement>(null);
  const descriptionInput = useRef<HTMLTextAreaElement>(null);
  const dueInput = useRef<HTMLInputElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  const priorityId = useId();
  const dueId = useId();
  const titleErrorId = useId();
  const descriptionErrorId = useId();
  const dueErrorId = useId();
  // Adjusts state during render when a reload delivers a new Task (same pattern as WorkView).
  if (task !== seenTask) {
    setSeenTask(task);
    setState((current) => follow(current, task));
  }
  useEffect(() => {
    titleInput.current?.focus();
  }, []);
  const priorities: string[] = (PRIORITY_CHOICES as readonly string[]).includes(
    state.values.priority,
  )
    ? [...PRIORITY_CHOICES]
    : [...PRIORITY_CHOICES, state.values.priority];
  const titleBad = problem === "required" || problem === "tooLong";
  const descriptionBad = problem === "descriptionTooLong";

  function setField(field: DraftField, value: string) {
    setProblem(undefined);
    setState((current) => ({
      ...current,
      values: { ...current.values, [field]: value },
    }));
  }
  /** A shortcut sets the date like the date input does, and it is a complete date, not a partial entry. */
  function setDue(value: string) {
    setProblem(undefined);
    setState((current) => ({
      ...current,
      values: { ...current.values, due: value },
      dueIncomplete: false,
    }));
  }
  // Save runs from the button's click, not the form's submit event: the App iframe is sandboxed
  // without allow-forms, where the browser never dispatches submit. Enter still clicks the button.
  function submit() {
    if (busy) return;
    const found = fieldProblem(state);
    setProblem(found);
    if (found === "dueIncomplete") {
      dueInput.current?.focus();
      return;
    }
    if (found === "descriptionTooLong") {
      descriptionInput.current?.focus();
      return;
    }
    if (found) {
      titleInput.current?.focus();
      return;
    }
    onSave(changedFields(state));
  }

  return (
    <form className="work-edit" aria-label={t.edit} noValidate>
      <label htmlFor={titleId}>{t.titleLabel}</label>
      <input
        id={titleId}
        ref={titleInput}
        type="text"
        value={state.values.title}
        disabled={busy}
        aria-invalid={titleBad ? true : undefined}
        aria-describedby={titleBad ? titleErrorId : undefined}
        onChange={(event) => setField("title", event.target.value)}
      />
      {titleBad && (
        <p id={titleErrorId}>
          {problem === "required" ? t.titleRequired : t.titleTooLong}
        </p>
      )}
      <label htmlFor={descriptionId}>{t.description}</label>
      <textarea
        id={descriptionId}
        ref={descriptionInput}
        rows={4}
        value={state.values.description}
        disabled={busy}
        aria-invalid={descriptionBad ? true : undefined}
        aria-describedby={descriptionBad ? descriptionErrorId : undefined}
        onChange={(event) => setField("description", event.target.value)}
      />
      {descriptionBad && <p id={descriptionErrorId}>{t.descriptionTooLong}</p>}
      <label htmlFor={priorityId}>{t.priority}</label>
      <select
        id={priorityId}
        value={state.values.priority}
        disabled={busy}
        onChange={(event) => setField("priority", event.target.value)}
      >
        {priorities.map((value) => (
          <option key={value} value={value}>
            {priorityLabel(t, value)}
          </option>
        ))}
      </select>
      <label htmlFor={dueId}>{t.due}</label>
      <div className="work-due-chips" role="group" aria-label={t.dueShortcuts}>
        <button
          type="button"
          disabled={busy}
          onClick={() => setDue(dueShortcutValue("today", new Date()))}
        >
          {t.dueToday}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => setDue(dueShortcutValue("tomorrow", new Date()))}
        >
          {t.dueTomorrow}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => setDue(dueShortcutValue("nextWeek", new Date()))}
        >
          {t.dueNextWeek}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => setDue(dueShortcutValue("none", new Date()))}
        >
          {t.dueNone}
        </button>
      </div>
      <div className="work-due-row">
        <input
          id={dueId}
          ref={dueInput}
          type="date"
          value={state.values.due}
          disabled={busy}
          aria-invalid={problem === "dueIncomplete" ? true : undefined}
          aria-describedby={
            problem === "dueIncomplete" ? dueErrorId : undefined
          }
          onChange={(event) => {
            // A partial entry reads as "" with badInput set; it is neither a change nor a clear.
            const incomplete = event.target.validity.badInput;
            const value = event.target.value;
            setProblem(undefined);
            setState((current) => ({
              ...current,
              values: { ...current.values, due: value },
              dueIncomplete: incomplete,
            }));
          }}
        />
        {state.values.due && (
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              setProblem(undefined);
              setState((current) => ({
                ...current,
                values: { ...current.values, due: "" },
                dueIncomplete: false,
              }));
            }}
          >
            {t.clearDue}
          </button>
        )}
      </div>
      {problem === "dueIncomplete" && <p id={dueErrorId}>{t.dueIncomplete}</p>}
      {saveFailed && (
        <p role="alert">
          {t.saveFailed}{" "}
          <button type="button" disabled={busy} onClick={() => submit()}>
            {t.retry}
          </button>
        </p>
      )}
      <div className="work-actions">
        <button
          type="submit"
          disabled={busy}
          onClick={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          {t.save}
        </button>
        <button type="button" disabled={busy} onClick={onCancel}>
          {t.cancel}
        </button>
      </div>
    </form>
  );
}
