import { useUndoHold } from "../../mcp-apps/ui/undo-hold";
import {
  recurringDoneText,
  type RecurringCycle,
} from "../agenda/parts/agenda-helpers";
import type { WorkLabels } from "../shared/labels";
import type {
  TaskStatusValue,
  WorkTask,
  WorkTaskChanges,
} from "../transport/transport";
import type { useTaskOffers } from "./use-task-offers";

/**
 * The Task view's answer to "Markera klar", right under the button, in the family's receipt shape (line plus Ångra).
 * On a recurring Task the server recorded the cycle and opened the Task again for its next date, so the button still
 * says "Markera klar" and the line says "Klar · nästa: fre 27 nov"; its Ångra writes the earlier due date back. On any
 * other Task the line says "Klar" and Ångra writes the earlier status back. It is a polite live region; its time to
 * undo stops while the pointer is over it or focus is in it, and `onExpire` ends it.
 */
export function TaskCycleLine({
  text,
  labels: t,
  disabled,
  onUndo,
  onExpire,
}: {
  text: string;
  labels: WorkLabels;
  disabled: boolean;
  /** Absent where the host cannot write the due date back: the line only says what happened. */
  onUndo?: () => void;
  onExpire: () => void;
}) {
  return (
    <div className="work-task-cycle" {...useUndoHold(true, onExpire).handlers}>
      <p role="status">{text}</p>
      {onUndo && (
        <button
          type="button"
          className="sk-btn--secondary sk-btn--compact"
          disabled={disabled}
          onClick={onUndo}
        >
          {t.agendaUndo}
        </button>
      )}
    </div>
  );
}

/** What the last "Markera klar" left to undo: a recurring Task's cycle, or the status any other Task had before. */
export type DoneReceipt =
  | ({ kind: "cycle" } & RecurringCycle)
  | { kind: "finished"; was: TaskStatusValue };

/**
 * The receipt line of the last "Markera klar" under the button: "Klar · nästa: fre 27 nov" for a recurring Task, "Klar"
 * for any other, each with the Ångra that writes the earlier value back through `save`. Without a host that answers that
 * write the line only says what happened.
 */
export function TaskDoneReceipt({
  receipt,
  task,
  labels: t,
  disabled,
  offers,
  save,
  onExpire,
}: {
  receipt: DoneReceipt;
  task: WorkTask;
  labels: WorkLabels;
  disabled: boolean;
  offers: ReturnType<typeof useTaskOffers>["offers"];
  save: (changes: WorkTaskChanges) => void;
  onExpire: () => void;
}) {
  const undo: WorkTaskChanges | undefined =
    receipt.kind === "cycle"
      ? offers("update_task", { changes: { due_at: null } })
        ? {
            due_at: receipt.from,
            ...(receipt.lastCompleted !== undefined
              ? { last_completed_at: receipt.lastCompleted }
              : {}),
          }
        : undefined
      : offers("update_task", {
            changes: { status: receipt.was },
            from_status: "completed",
          })
        ? { status: receipt.was }
        : undefined;
  return (
    <TaskCycleLine
      text={
        receipt.kind === "cycle"
          ? recurringDoneText(t, task.due_at, new Date())
          : t.taskStatus.completed
      }
      labels={t}
      disabled={disabled}
      onUndo={undo && (() => save(undo))}
      onExpire={onExpire}
    />
  );
}
