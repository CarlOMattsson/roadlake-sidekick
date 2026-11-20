import { useMemo, type Ref } from "react";
import type { ReceiptState } from "../../mcp-apps/ui/receipt";
import {
  recurringDoneText,
  type RecurringCycle,
} from "../agenda/parts/agenda-helpers";
import { statusUndo } from "../board/board-writes";
import type { DoneHandoff } from "../shared/done-handoff";
import { taskStatusLabel, type WorkLabels } from "../shared/labels";
import {
  rowReceipt,
  useUndoReceipts,
  type UndoReceipt,
} from "../shared/use-undo-receipts";
import {
  isTaskStatus,
  type TaskStatusValue,
  type WorkTask,
  type WorkTaskChanges,
} from "../transport/transport";
import type { useTaskOffers } from "./use-task-offers";
import type { TaskDone } from "./use-task-writes";

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
 * What a Task marked done hands the board its view goes back to: the Task, and the Ångra the board offers where the
 * host can write the change back (the same check as the receipt here, see receiptUndo).
 */
export function doneHandoff(
  { task, was, receipt }: TaskDone,
  offers: ReturnType<typeof useTaskOffers>["offers"],
  t: WorkLabels,
): DoneHandoff {
  if (!receipt || !isTaskStatus(was) || !receiptUndo(receipt, offers))
    return { task };
  const before =
    receipt.kind === "cycle"
      ? { due: receipt.from, lastCompleted: receipt.lastCompleted ?? null }
      : { due: null, lastCompleted: null };
  return { task, undo: statusUndo(t, was, task, before, true) };
}

/**
 * The receipt bar's words for the last `markDone` (designsystem §0.6): "Klar: {title}", or for a recurring Task, which the
 * server opened again for its next date, `recurringDone` ("Klar · nästa: 22 nov"). Ångra writes the earlier status, or the
 * earlier due date, through `write`; where the host cannot answer that write the bar only says what happened.
 */
export function doneBarReceipt(
  receipt: DoneReceipt,
  task: WorkTask,
  offers: ReturnType<typeof useTaskOffers>["offers"],
  t: WorkLabels,
  write: (changes: WorkTaskChanges) => void,
): UndoReceipt {
  const message =
    receipt.kind === "cycle"
      ? recurringDoneText(t, task.due_at, new Date())
      : rowReceipt(taskStatusLabel(t, "completed"), task.title);
  const changes = receiptUndo(receipt, offers);
  return {
    message,
    ...(changes
      ? { undo: { label: t.agendaUndo, onUndo: () => write(changes) } }
      : {}),
  };
}

/**
 * Puts the last `markDone` in the view's receipt bar (doneBarReceipt) while it can be undone: the control stays as it is,
 * showing its new state, and the receipt ends with the bar's time (`onEnd`) or when a new write ends it (`done` goes).
 */
export function useDoneReceipt({
  done,
  task,
  offers,
  labels: t,
  bar,
  write,
  onEnd,
}: {
  done: DoneReceipt | undefined;
  task: WorkTask | undefined;
  offers: ReturnType<typeof useTaskOffers>["offers"];
  labels: WorkLabels;
  bar: ReceiptState;
  /** Writes what Ångra puts back. */
  write: (changes: WorkTaskChanges) => void;
  onEnd: () => void;
}): void {
  const undos = useMemo(
    (): Record<string, DoneReceipt> => (done ? { done } : {}),
    [done],
  );
  useUndoReceipts({
    undos,
    receipt: bar,
    describe: (_key, entry) =>
      task ? doneBarReceipt(entry, task, offers, t, write) : undefined,
    onEnd,
  });
}

/**
 * The Task's `markDone` slot, last in the control row: the screen's one primary, compact ink; on a done Task
 * `reopenTask` as a secondary, which sets it back to `todo`. It shows its new state at once after `markDone` and moves
 * nothing; the change is confirmed, with Ångra, in the receipt bar (see doneBarReceipt). `buttonRef` lets the frame keep
 * focus on it after the write.
 */
export function TaskDoneControl({
  task,
  labels: t,
  disabled,
  onChoose,
  buttonRef,
}: {
  task: WorkTask;
  labels: WorkLabels;
  disabled: boolean;
  onChoose: (status: TaskStatusValue) => void;
  buttonRef?: Ref<HTMLButtonElement>;
}) {
  const finished = task.status === "completed";
  return (
    <button
      ref={buttonRef}
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
