import type { MutableRefObject } from "react";
import { keyFor, type PendingKey } from "../../mcp-apps/idempotency";
import type { AgendaUndo } from "../agenda/agenda-undo";
import { failureNotice, type BoardNotice } from "./board-notice";
import { withStepMoved, type ReorderTo } from "./board-columns";
import { cardKey } from "../shared/work-items";
import { sameDue } from "../agenda/parts/agenda-helpers";
import {
  isTaskStatus,
  writeFailure,
  type TaskStatusValue,
  type WorkBoardFrame,
  type WorkItemRecord,
  type WorkTask,
  type WorkTransport,
} from "../transport/transport";

/**
 * Where focus goes once the board shows the result of a write: a card's glyph (after a move, also in the single
 * layout, where the card stays in place with its Undo), or its title (after Flytta upp or Flytta ned).
 */
export type FocusWanted = { kind: "card" | "more"; id: string };

/**
 * The last write a Retry runs again: a status move, its Undo, or a column order (worked out again when it runs).
 */
export type LastWrite =
  | { kind: "move"; card: WorkItemRecord; to: TaskStatusValue }
  | { kind: "undo"; entry: AgendaUndo }
  | { kind: "step"; card: WorkItemRecord }
  | {
      kind: "reorder";
      status: TaskStatusValue;
      taskId: string;
      to: ReorderTo;
    };

/** What the board's card writes share: its refs, its notice and its queue. BoardView builds one per render. */
export type BoardWriteDeps = {
  transport: WorkTransport;
  latest: MutableRefObject<WorkBoardFrame>;
  pendingMove: MutableRefObject<Map<string, PendingKey>>;
  unsure: MutableRefObject<Map<string, () => Promise<void>>>;
  writes: MutableRefObject<number>;
  focusWanted: MutableRefObject<FocusWanted | undefined>;
  lastWrite: MutableRefObject<LastWrite | undefined>;
  notify: (next: BoardNotice | undefined) => void;
  commit: (next: WorkBoardFrame) => void;
  forget: (key: string) => void;
  queueWrite: (key: string, work: () => Promise<void>) => void;
  replayUnsure: (key: string) => Promise<boolean>;
  reread: (done?: BoardNotice) => Promise<void>;
  taskCard: (
    id: string,
    from?: WorkBoardFrame["page"],
  ) => WorkItemRecord | undefined;
  wrote: (task: WorkTask) => void;
};

/**
 * Undo of a status move: the previous status, written against the version the move left. It gets
 * its own key, so it never replays the move it reverts. A reply that does not show the restored
 * status is a failure with "Try again", as in the agenda. A recurring Task's recorded cycle (`entry.due`) is
 * undone by writing its earlier due date back; the server keeps the completion on record.
 */
export function undoMoveWrite(deps: BoardWriteDeps, entry: AgendaUndo) {
  const {
    forget,
    focusWanted,
    notify,
    queueWrite,
    replayUnsure,
    latest,
    taskCard,
    pendingMove,
    transport,
    wrote,
    unsure,
    lastWrite,
    reread,
  } = deps;
  if (!isTaskStatus(entry.from)) return;
  const from = entry.from;
  const undoKey = `undo:${entry.key}`;
  forget(entry.key);
  focusWanted.current = { kind: "card", id: entry.taskId };
  notify(undefined);
  queueWrite(entry.key, async () => {
    if (!(await replayUnsure(entry.key))) return;
    // A later move of the card has offered an Undo of its own meanwhile; this one is used, so none is left.
    forget(entry.key);
    let answered = false;
    let replay: (() => Promise<void>) | undefined;
    // The version is the card's when the Undo runs, not when it was offered: a later write of the card has raised it.
    const base = taskCard(entry.taskId, latest.current.page);
    const due = entry.due;
    if (!due && base?.status === from) return;
    const changes = due
      ? {
          due_at: due.from,
          ...(entry.lastCompleted
            ? { last_completed_at: entry.lastCompleted.from }
            : {}),
        }
      : { status: from };
    const version =
      typeof base?.version === "number" ? base.version : entry.version;
    try {
      const signature = JSON.stringify([entry.taskId, version, changes]);
      const pendingKey = keyFor(pendingMove.current.get(undoKey), signature);
      pendingMove.current.set(undoKey, pendingKey);
      // Replayed with its key when its delivery is unknown, like a move.
      replay = async () => {
        const { task } = await transport.updateTask(
          entry.taskId,
          version,
          changes,
          pendingKey.key,
        );
        answered = true;
        pendingMove.current.delete(undoKey);
        const restored = due
          ? sameDue(task.due_at, due.from)
          : task.status === from;
        if (!restored) throw new Error("undo not applied");
        wrote(task);
      };
      await replay();
    } catch (error) {
      if (writeFailure(error) !== "failed") pendingMove.current.delete(undoKey);
      else if (replay && !answered) unsure.current.set(entry.key, replay);
      const failed = failureNotice(error, "move");
      lastWrite.current = { kind: "undo", entry };
      focusWanted.current = undefined;
      notify(failed);
      if (failed.kind === "conflict") await reread(failed);
    }
  });
}
/**
 * The check of a Step in the single layout: done, or open again when it is done. The Step is written with
 * its own tools (complete_task_step, update_task_step) against the version the board shows, and moves to its new
 * section at once; the board is read again after it, as after every write. A Step has no Undo line: its check is
 * the way back.
 */
export function toggleStepWrite(deps: BoardWriteDeps, card: WorkItemRecord) {
  const {
    notify,
    queueWrite,
    latest,
    pendingMove,
    transport,
    writes,
    commit,
    focusWanted,
    lastWrite,
    reread,
  } = deps;
  const key = cardKey(card);
  // The target is decided at the tap, as a move's is (`move`): a tap queued behind a write keeps its own wish.
  const wantDone = card.status !== "completed";
  notify(undefined);
  queueWrite(key, async () => {
    const base =
      Object.values(latest.current.page.columns)
        .flat()
        .find((item) => cardKey(item) === key) ?? card;
    if (typeof base.version !== "number") return;
    // Already in the wanted state (an earlier tap of this Step got it there): nothing to write.
    if ((base.status === "completed") === wantDone) return;
    const pendingKey = keyFor(
      pendingMove.current.get(key),
      JSON.stringify([card.id, base.version, wantDone]),
    );
    pendingMove.current.set(key, pendingKey);
    try {
      const { step } = wantDone
        ? await transport.completeTaskStep(
            card.id,
            base.version,
            pendingKey.key,
          )
        : await transport.updateTaskStep(
            card.id,
            base.version,
            { status: "todo" },
            pendingKey.key,
          );
      pendingMove.current.delete(key);
      writes.current += 1;
      commit({
        ...latest.current,
        page: withStepMoved(latest.current.page, key, base, step),
      });
      focusWanted.current = { kind: "card", id: card.id };
    } catch (error) {
      if (writeFailure(error) !== "failed") pendingMove.current.delete(key);
      const failed = failureNotice(error, "move");
      lastWrite.current = { kind: "step", card };
      notify(failed);
      if (failed.kind === "conflict") await reread(failed);
    }
  });
}
