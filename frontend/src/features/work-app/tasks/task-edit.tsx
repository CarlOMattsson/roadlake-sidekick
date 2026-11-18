import { useEffect, useId, useRef, useState } from "react";
import { ErrorNotice } from "../../mcp-apps/ui/states";
import { priorityLabel, type WorkLabels } from "../shared/labels";
import {
  isCompleteDate,
  keepEdits,
  titleProblem,
  type TitleProblem,
} from "../shared/fields";
import { DESCRIPTION_MAX_LENGTH } from "../hierarchy/project-edit";
import {
  parseDueDay,
  ownerClockTime,
  ownerDayPlus,
  ownerDaysToNextMonday,
  ownerDueAt,
  ownerEndOfDay,
} from "../../mcp-apps/ui/due";
import {
  type WorkContact,
  type WorkTask,
  type WorkTaskChanges,
  type WorkTransport,
} from "../transport/transport";
import { useUnsavedGuard } from "../../mcp-apps/unsaved-guard";
import { followUpAtOf, waitingSinceOf } from "../shared/waiting";
import { EditWaiting, type WaitingDraft } from "./task-edit-waiting";

/** The priorities the form offers; a Task with urgent keeps that value, shown as an extra option. */
type PriorityChoice = NonNullable<WorkTaskChanges["priority"]>;
/** The priorities a Task can be given here; the editor and the priority chip offer these. */
export const PRIORITY_CHOICES = [
  "low",
  "normal",
  "high",
] as const satisfies readonly PriorityChoice[];
export function isPriorityChoice(value: string): value is PriorityChoice {
  return (PRIORITY_CHOICES as readonly string[]).includes(value);
}

/**
 * Editable Task fields as the form shows them; due is an owner-zone YYYY-MM-DD or "", time the owner-zone HH:MM the
 * Task is due at or "" for a bare date. Priority is the raw
 * value ("normal" when the Task has none). The status is not here: the status choice in the Task
 * view writes it. The waiting fields are owner-zone days and the waiting Contact's id, "" for none.
 */
export type TaskDraft = {
  title: string;
  description: string;
  priority: string;
  due: string;
  time: string;
} & WaitingDraft;
/**
 * `base` is the Task as the user last saw it (opening the editor, or the latest reload). A field
 * counts as changed only while it differs from base, so an edit reverted by hand is not sent.
 * `dueIncomplete`, `timeIncomplete` and `waitingIncomplete` are set while the date or time input holds a partial entry the
 * browser cannot read.
 */
export type DraftState = {
  values: TaskDraft;
  base: TaskDraft;
  dueIncomplete: boolean;
  timeIncomplete?: boolean;
  waitingIncomplete?: boolean;
};
export type FieldProblem =
  | TitleProblem
  | "descriptionTooLong"
  | "dueIncomplete"
  | "timeIncomplete"
  | "waitingIncomplete";
type DraftField = keyof TaskDraft;
/** The date shortcuts above the due date field: today, tomorrow, the next Monday, or no date. */
type DueShortcut = "today" | "tomorrow" | "nextWeek" | "none";

export function draftFromTask(task: WorkTask): TaskDraft {
  return {
    title: task.title,
    description: task.description ?? "",
    priority: task.priority ?? "normal",
    due: dateInputValue(task.due_at),
    time: ownerClockTime(task.due_at) ?? "",
    waitingSince: dateInputValue(task.waiting_since ?? null),
    followUp: dateInputValue(task.follow_up_at ?? null),
    waitingContact: task.waiting_on_contact_id ?? "",
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

/**
 * The due instant of a draft: the day with its time (23:59 for a bare date, as `dueAtFromDateInput`), or null when there
 * is no date. The time is kept when only the day changes, so a Task that reminds at 17:30 still does.
 */
function dueAtFromDraft(values: TaskDraft): string | null {
  return values.due ? ownerDueAt(values.due, values.time) : null;
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
  if (state.timeIncomplete) return "timeIncomplete";
  if (state.waitingIncomplete) return "waitingIncomplete";
  return undefined;
}

/**
 * The waiting fields that differ from base. A Contact and a follow-up day only exist while the Task waits, so an emptied
 * "waiting since" ends the wait, emptying all three; the editor never leaves a day or a Contact without a wait.
 */
function waitingChanges(
  { values, base }: Pick<DraftState, "values" | "base">,
  now: Date,
): WorkTaskChanges {
  if (values.waitingSince === "")
    return base.waitingSince === ""
      ? {}
      : {
          waiting_since: null,
          follow_up_at: null,
          waiting_on_contact_id: null,
        };
  const changes: WorkTaskChanges = {};
  if (values.waitingSince !== base.waitingSince)
    changes.waiting_since = waitingSinceOf(values.waitingSince, now);
  if (values.followUp !== base.followUp)
    changes.follow_up_at = values.followUp
      ? followUpAtOf(values.followUp)
      : null;
  if (values.waitingContact !== base.waitingContact)
    changes.waiting_on_contact_id = values.waitingContact || null;
  return changes;
}

/**
 * Only the fields that differ from what the user last saw. A field the user did not change is
 * never sent, so a reload cannot overwrite someone else's change. An incomplete date is not a
 * change; Save is blocked for it instead. An emptied description is sent as null, which clears it.
 */
export function changedFields(
  state: DraftState,
  now: Date = new Date(),
): WorkTaskChanges {
  const { values, base } = state;
  const changes: WorkTaskChanges = {};
  if (values.title.trim() !== base.title.trim())
    changes.title = values.title.trim();
  if (values.description.trim() !== base.description.trim())
    changes.description = values.description.trim() || null;
  if (values.priority !== base.priority && isPriorityChoice(values.priority))
    changes.priority = values.priority;
  if (
    !state.dueIncomplete &&
    !state.timeIncomplete &&
    (values.due !== base.due ||
      (values.due !== "" && values.time !== base.time))
  )
    changes.due_at = dueAtFromDraft(values);
  if (!state.waitingIncomplete)
    Object.assign(changes, waitingChanges(state, now));
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
    timeIncomplete: current.timeIncomplete,
    waitingIncomplete: current.waitingIncomplete,
  };
}

export function TaskEditor({
  task,
  busy,
  saveFailed,
  onSave,
  onCancel,
  labels: t,
  transport,
  waitingName = null,
}: {
  task: WorkTask;
  busy: boolean;
  saveFailed: boolean;
  onSave: (changes: WorkTaskChanges) => void;
  onCancel: () => void;
  labels: WorkLabels;
  /** Searches the Contacts for the waiting-on field; without it the field shows its Contact and cannot change it. */
  transport?: WorkTransport;
  /** The name of the Contact the Task waits on, when the caller has it. */
  waitingName?: string | null;
}) {
  const [state, setState] = useState<DraftState>(() => {
    const initial = draftFromTask(task);
    return { values: initial, base: initial, dueIncomplete: false };
  });
  const [seenTask, setSeenTask] = useState(task);
  const [problem, setProblem] = useState<FieldProblem>();
  // The name of the waiting Contact: the caller's, or the one chosen here.
  const [chosen, setChosen] = useState<WorkContact>();
  useUnsavedGuard(
    state.dueIncomplete ||
      Boolean(state.timeIncomplete) ||
      Boolean(state.waitingIncomplete) ||
      Object.keys(changedFields(state)).length > 0,
  );
  const titleInput = useRef<HTMLInputElement>(null);
  const descriptionInput = useRef<HTMLTextAreaElement>(null);
  const dueInput = useRef<HTMLInputElement>(null);
  const timeInput = useRef<HTMLInputElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  const priorityId = useId();
  const dueId = useId();
  const timeId = useId();
  const titleErrorId = useId();
  const descriptionErrorId = useId();
  const dueErrorId = useId();
  const timeErrorId = useId();
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
  /** Sets the waiting fields; a Contact or a follow-up day starts the wait today when it has not begun. */
  function setWaiting(
    next: Partial<WaitingDraft>,
    incomplete = false,
    startsWait = false,
  ) {
    setProblem(undefined);
    setState((current) => {
      const values = { ...current.values, ...next };
      if (startsWait && values.waitingSince === "")
        values.waitingSince = ownerDayPlus(new Date(), 0);
      return { ...current, values, waitingIncomplete: incomplete };
    });
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
    if (found === "timeIncomplete") {
      timeInput.current?.focus();
      return;
    }
    if (found === "waitingIncomplete") return;
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
      {state.values.due && (
        <>
          <label htmlFor={timeId}>{t.dueTime}</label>
          <div className="work-due-row">
            <input
              id={timeId}
              ref={timeInput}
              type="time"
              value={state.values.time}
              disabled={busy}
              aria-invalid={problem === "timeIncomplete" ? true : undefined}
              aria-describedby={
                problem === "timeIncomplete" ? timeErrorId : undefined
              }
              onChange={(event) => {
                // A partial entry reads as "" with badInput set; it is neither a time nor a removed time.
                const incomplete = event.target.validity.badInput;
                const value = event.target.value;
                setProblem(undefined);
                setState((current) => ({
                  ...current,
                  values: { ...current.values, time: value },
                  timeIncomplete: incomplete,
                }));
              }}
            />
            {state.values.time && (
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  setProblem(undefined);
                  setState((current) => ({
                    ...current,
                    values: { ...current.values, time: "" },
                    timeIncomplete: false,
                  }));
                }}
              >
                {t.removeDueTime}
              </button>
            )}
          </div>
          {state.values.time && <p>{t.remindsAtTime}</p>}
          {problem === "timeIncomplete" && (
            <p id={timeErrorId}>{t.dueTimeIncomplete}</p>
          )}
        </>
      )}
      <EditWaiting
        values={state.values}
        contactName={
          chosen?.id === state.values.waitingContact
            ? chosen.display_name
            : state.values.waitingContact === task.waiting_on_contact_id
              ? waitingName
              : null
        }
        transport={transport}
        disabled={busy}
        invalid={problem === "waitingIncomplete"}
        labels={t}
        onSince={(day, incomplete) =>
          setWaiting({ waitingSince: day }, incomplete)
        }
        onFollowUp={(day, incomplete) =>
          setWaiting({ followUp: day }, incomplete, day !== "")
        }
        onContact={(contact) => {
          setChosen(contact ?? undefined);
          setWaiting(
            { waitingContact: contact?.id ?? "" },
            false,
            contact !== null,
          );
        }}
        onStop={() =>
          setWaiting({ waitingSince: "", followUp: "", waitingContact: "" })
        }
      />
      {saveFailed && (
        <ErrorNotice
          placement="row"
          locale={t.dateLocale}
          message={t.saveFailed}
          retrying={busy}
          onRetry={() => submit()}
        />
      )}
      <div className="sk-form-actions">
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
        <button
          type="button"
          className="sk-btn--quiet"
          disabled={busy}
          onClick={onCancel}
        >
          {t.cancel}
        </button>
      </div>
    </form>
  );
}
