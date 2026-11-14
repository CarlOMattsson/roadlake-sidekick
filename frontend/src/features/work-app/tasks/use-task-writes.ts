import { useCallback, useRef, useState } from "react";
import { isRecurringCycle } from "../agenda/parts/agenda-helpers";
import {
  isTaskStatus,
  type TaskStatusValue,
  type WorkTask,
  type WorkTaskChanges,
  type WorkTransport,
} from "../transport/transport";
import type { DetailFrame } from "../view/parts/use-detail-frame";
import type { DoneReceipt } from "./task-cycle";

/** Which write a failure line names. */
export type TaskWriteKind = "trash" | "save" | "done";

/**
 * Every write of the open Task frame: the quick status and date choices, the editor's save, the tag set, the move
 * to the trash and its restore. The Task itself stays with the frame (`task`, `setTask`); this keeps what the
 * writes leave behind: the receipt of the last "done", the trash record's version, and the retry of a failed write.
 * The same action keeps its key, so the server replays a retry.
 */
export function useTaskWrites({
  frame,
  transport,
  id,
  task,
  setTask,
  refreshTags,
  onSaved,
  onTrashStart,
}: {
  frame: DetailFrame;
  transport: WorkTransport;
  id: string;
  task: WorkTask | undefined;
  setTask: (task: WorkTask | undefined) => void;
  refreshTags: () => void;
  onSaved: () => void;
  /** Runs when the Task is about to be moved to the trash (the frame closes its ⋯ panel). */
  onTrashStart: () => void;
}) {
  // What the last `markDone` left to undo: the line under the button and the earlier value its Ångra puts back.
  const [receipt, setReceipt] = useState<DoneReceipt>();
  const endReceipt = useCallback(() => setReceipt(undefined), []);
  // Set once the Task has moved to the trash: the trash record's version, which the restore needs.
  const [trashed, setTrashed] = useState<{ version: number }>();
  // Runs the last failed trash, restore, quick change or tag change again.
  const retryWrite = useRef<(() => void) | undefined>(undefined);
  const [writeWhat, setWriteWhat] = useState<TaskWriteKind>("trash");
  const { heading } = frame;

  /**
   * Writes only the changed fields against the version the view holds; the key follows the action. Every write ends
   * the receipt of an earlier one; `then` sees the reply once it is shown. `receipt`: the reply is shown by the
   * controls themselves (a `completed` receipt with Ångra, or the controls put back by Ångra), so no plain `saved` stands
   * beside it.
   */
  function saveTask(
    changes: WorkTaskChanges,
    then?: (next: WorkTask) => void,
    receipt = false,
  ) {
    if (!task || frame.flight.isRunning()) return;
    if (Object.keys(changes).length === 0) {
      frame.stopEdit();
      return;
    }
    setReceipt(undefined);
    retryWrite.current = () => saveTask(changes, then, receipt);
    setWriteWhat(receipt && changes.status === "completed" ? "done" : "save");
    frame.sendWrite(
      JSON.stringify([task.id, task.version, changes]),
      "save",
      (key) => transport.updateTask(task.id, task.version, changes, key),
      (result) => {
        retryWrite.current = undefined;
        setTask(result.task);
        then?.(result.task);
        frame.setEditing(false);
        onSaved();
        heading.current?.focus();
      },
      receipt,
    );
  }
  /**
   * Writes the Task's whole tag set (update_task changes.tags) in place: the focus stays in the tag field, and `done`
   * runs once it is stored. A failure keeps the typed tag and offers Försök igen.
   */
  function setTags(next: string[], done: () => void) {
    if (!task || frame.flight.isRunning()) return;
    retryWrite.current = () => setTags(next, done);
    setWriteWhat("save");
    setReceipt(undefined);
    frame.sendWrite(
      JSON.stringify(["tags", task.id, task.version, next]),
      "write",
      (key) => transport.updateTask(task.id, task.version, { tags: next }, key),
      (result) => {
        retryWrite.current = undefined;
        setTask(result.task);
        onSaved();
        refreshTags();
        done();
      },
    );
  }
  /** Moves the Task to the trash at the version the view holds; no question first, since Ångra undoes it. */
  function trashTask() {
    if (!task || frame.flight.isRunning()) return;
    onTrashStart();
    retryWrite.current = trashTask;
    setWriteWhat("trash");
    frame.sendWrite(
      JSON.stringify(["trash", task.id, task.version]),
      "write",
      (key) => transport.trashTask(task.id, task.version, key),
      (result) => {
        retryWrite.current = undefined;
        setTrashed({ version: result.version });
        onSaved();
        heading.current?.focus();
      },
    );
  }
  /** Takes the Task out of the trash and reads it again, so the view holds the version the restore left. */
  function restoreTask() {
    if (!trashed || frame.flight.isRunning()) return;
    retryWrite.current = restoreTask;
    setWriteWhat("trash");
    frame.sendWrite(
      JSON.stringify(["restore", id, trashed.version]),
      "write",
      (key) =>
        transport
          .restoreTask(id, trashed.version, key)
          .then(() => transport.getTask(id)),
      (result) => {
        retryWrite.current = undefined;
        setTask(result.task);
        setTrashed(undefined);
        onSaved();
        heading.current?.focus();
      },
    );
  }
  /** The Ångra of a `markDone`: the status and the button go back in place, with no `saved` beside them. */
  function undoDone(changes: WorkTaskChanges) {
    saveTask(changes, undefined, true);
  }
  /** A quick status choice writes through saveTask, the same path as Spara. Off while the editor is open. */
  function chooseStatus(status: TaskStatusValue) {
    if (!task || task.status === status) return;
    // Done on a recurring Task: the reply is the Task open again with its next date (see isRecurringCycle).
    const before = task.due_at ?? null;
    const lastCompleted = task.last_completed_at ?? null;
    const was = task.status;
    saveTask(
      { status },
      (next) => {
        if (status !== "completed") return;
        if (isRecurringCycle(next, before))
          setReceipt({ kind: "cycle", from: before, lastCompleted });
        else if (isTaskStatus(was)) setReceipt({ kind: "finished", was });
      },
      status === "completed",
    );
  }

  return {
    receipt,
    endReceipt,
    trashed,
    writeWhat,
    retryLast: () => retryWrite.current?.(),
    saveTask,
    setTags,
    trashTask,
    restoreTask,
    undoDone,
    chooseStatus,
  };
}
