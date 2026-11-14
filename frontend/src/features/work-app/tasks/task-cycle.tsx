import { useEffect, useRef } from "react";
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
 * The Ångra of a `markDone` receipt: focus starts on its button (the write had moved it to the title), and the
 * time is held by the pointer only. A hold by focus would never let the time run out, since focus starts there. When
 * the time is up with focus on the button, focus goes to the Task's title.
 */
function useReceiptUndo(onExpire: () => void) {
  const button = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    button.current?.focus();
  }, []);
  const { held, handlers } = useUndoHold(true, () => {
    const undo = button.current;
    if (undo && document.activeElement === undo)
      undo.closest("article")?.querySelector("h2")?.focus();
    onExpire();
  });
  const pointer = {
    onPointerEnter: handlers.onPointerEnter,
    onPointerLeave: handlers.onPointerLeave,
  };
  return { button, held, pointer };
}

/**
 * The Task view's answer to `markDone` on a recurring Task, right under the button, in the family's receipt shape
 * (line plus Ångra): `recurringDone`. The server recorded the cycle and opened the Task again for its next
 * date, so the button still says `markDone` and Ångra writes the earlier due date back. It is a polite live
 * region; its time to undo stops while the pointer is over it (not for focus, which starts on Ångra), and `onExpire` ends it.
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
  const { button, held, pointer } = useReceiptUndo(onExpire);
  return (
    <div
      className="work-task-cycle"
      data-held={held ? "" : undefined}
      {...pointer}
    >
      <p role="status">{text}</p>
      {onUndo && (
        <button
          ref={button}
          type="button"
          className="sk-btn--secondary sk-btn--compact sk-undo-time"
          disabled={disabled}
          onClick={onUndo}
        >
          {t.agendaUndo}
        </button>
      )}
    </div>
  );
}

/**
 * Ångra in the place of `reopenTask` while a Task has just been marked done: the status chip already says `completed`, so the
 * one way back is this button (with its time line) and no line of its own is added. Focus starts on it, and the time
 * stands still while the pointer is over it. Screen readers get `completed` from a hidden live region.
 */
export function TaskDoneUndo({
  labels: t,
  disabled,
  onUndo,
  onExpire,
}: {
  labels: WorkLabels;
  disabled: boolean;
  onUndo: () => void;
  onExpire: () => void;
}) {
  const { button, held, pointer } = useReceiptUndo(onExpire);
  return (
    <>
      <button
        ref={button}
        type="button"
        className="sk-btn--secondary sk-btn--compact sk-undo-time work-task-done"
        data-held={held ? "" : undefined}
        disabled={disabled}
        onClick={onUndo}
        {...pointer}
      >
        {t.agendaUndo}
      </button>
      <span role="status" className="work-visually-hidden">
        {t.taskStatus.completed}
      </span>
    </>
  );
}

/** What the last `markDone` left to undo: a recurring Task's cycle, or the status any other Task had before. */
export type DoneReceipt =
  | ({ kind: "cycle" } & RecurringCycle)
  | { kind: "finished"; was: TaskStatusValue };

/**
 * What Ångra of the last `markDone` writes back, or nothing where the host cannot answer that write: a recurring
 * Task's earlier due date (and last completion), or the status any other Task had.
 */
export function receiptUndo(
  receipt: DoneReceipt,
  offers: ReturnType<typeof useTaskOffers>["offers"],
): WorkTaskChanges | undefined {
  if (receipt.kind === "cycle")
    return offers("update_task", { changes: { due_at: null } })
      ? {
          due_at: receipt.from,
          ...(receipt.lastCompleted !== undefined
            ? { last_completed_at: receipt.lastCompleted }
            : {}),
        }
      : undefined;
  return offers("update_task", {
    changes: { status: receipt.was },
    from_status: "completed",
  })
    ? { status: receipt.was }
    : undefined;
}

/**
 * The Task's `markDone` slot, last in the control row: the screen's one primary, compact ink; on a done Task
 * `reopenTask` as a secondary, which sets it back to `todo`. Right after `markDone` on any other Task Ångra stands
 * there instead (see TaskDoneUndo) until the time to undo is up. Both choices go through `onChoose`.
 */
export function TaskDoneControl({
  task,
  receipt,
  offers,
  labels: t,
  disabled,
  onChoose,
  onUndo,
  onExpire,
}: {
  task: WorkTask;
  receipt: DoneReceipt | undefined;
  offers: ReturnType<typeof useTaskOffers>["offers"];
  labels: WorkLabels;
  disabled: boolean;
  onChoose: (status: TaskStatusValue) => void;
  onUndo: (changes: WorkTaskChanges) => void;
  onExpire: () => void;
}) {
  const finished = task.status === "completed";
  const undo =
    receipt?.kind === "finished" && finished
      ? receiptUndo(receipt, offers)
      : undefined;
  if (undo)
    return (
      <TaskDoneUndo
        labels={t}
        disabled={disabled}
        onUndo={() => onUndo(undo)}
        onExpire={onExpire}
      />
    );
  return (
    <button
      type="button"
      className={
        finished
          ? "sk-btn--secondary sk-btn--compact work-task-done"
          : "sk-btn--primary sk-btn--compact work-task-done"
      }
      disabled={disabled}
      onClick={() => onChoose(finished ? "todo" : "completed")}
    >
      {finished ? t.reopenTask : t.markDone}
    </button>
  );
}

/**
 * The receipt line of a recurring Task's last `markDone` (`recurringDone`) with the Ångra that writes the
 * earlier due date back through `save`. Without a host that answers that write the line only says what happened.
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
  receipt: Extract<DoneReceipt, { kind: "cycle" }>;
  task: WorkTask;
  labels: WorkLabels;
  disabled: boolean;
  offers: ReturnType<typeof useTaskOffers>["offers"];
  save: (changes: WorkTaskChanges) => void;
  onExpire: () => void;
}) {
  const undo = receiptUndo(receipt, offers);
  return (
    <TaskCycleLine
      text={recurringDoneText(t, task.due_at, new Date())}
      labels={t}
      disabled={disabled}
      onUndo={undo && (() => save(undo))}
      onExpire={onExpire}
    />
  );
}
