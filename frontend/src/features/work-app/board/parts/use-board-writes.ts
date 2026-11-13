import { useRef, type Dispatch, type SetStateAction } from "react";
import { keyFor, type PendingKey } from "../../../mcp-apps/idempotency";
import type { AgendaUndo } from "../../agenda/agenda-undo";
import {
  isRecurringCycle,
  recurringDoneText,
} from "../../agenda/parts/agenda-helpers";
import type { WorkLabels } from "../../shared/labels";
import { failureNotice, type BoardAction } from "../board-notice";
import {
  completeColumn as wholeColumn,
  findTaskCard,
  reorderedColumn,
  withColumnPlaced,
  type BoardUndo,
  type ReorderTo,
} from "../board-columns";
import {
  toggleStepWrite,
  undoMoveWrite,
  type BoardWriteDeps,
  type LastWrite,
} from "../board-writes";
import { cardKey } from "../../shared/work-items";
import {
  isTaskStatus,
  writeFailure,
  type TaskStatusValue,
  type WorkBoardFrame,
  type WorkBoardPlacement,
  type WorkBoardPlacementItem,
  type WorkItemRecord,
} from "../../transport/transport";
import type { BoardCore } from "./use-board-core";
import type { Preview } from "./use-board-sections";

type Options = {
  core: BoardCore;
  frame: WorkBoardFrame;
  labels: WorkLabels;
  single: boolean;
  /** The records a section of the single layout draws, by section key. */
  shownOf: (key: string) => WorkItemRecord[];
  undos: Record<string, BoardUndo>;
  setUndos: Dispatch<SetStateAction<Record<string, BoardUndo>>>;
  setPreview: Dispatch<SetStateAction<Preview | undefined>>;
};

/**
 * The board's card writes: a status move, a column order, their Undo and Retry. Each waits in its card's queue;
 * a write whose delivery is unknown is replayed with its own key before the next one of the queue is made.
 */
export function useBoardWrites({
  core,
  frame,
  labels: t,
  single,
  shownOf,
  undos,
  setUndos,
  setPreview,
}: Options) {
  const {
    transport,
    latest,
    writes,
    focusWanted,
    notify,
    commit,
    reread,
    reload,
    loadMore,
    queueWrite,
    wrote,
  } = core;
  const pendingMove = useRef(new Map<string, PendingKey>());
  const pendingReorder = useRef(new Map<string, PendingKey>());
  const lastWrite = useRef<LastWrite>(undefined);
  // A write by queue key whose delivery is unknown (no answer): the server may have applied it. The next write of the
  // queue replays it with its own key first and shows its answer, so the next one is worked out from what the server holds.
  const unsure = useRef(new Map<string, () => Promise<void>>());

  /** The Task with this id on the board, if it is one. */
  function taskCard(id: string, from = frame.page): WorkItemRecord | undefined {
    return findTaskCard(id, from);
  }
  /** Ends the Undo of one card: its time is up, or it was used. */
  function forget(key: string) {
    setUndos((all) => {
      const rest = { ...all };
      delete rest[key];
      return rest;
    });
  }
  /** Replays the queue's unsure write, if any, and shows its answer; false when it fails again (the notice says so). */
  async function replayUnsure(key: string): Promise<boolean> {
    const replay = unsure.current.get(key);
    if (!replay) return true;
    try {
      await replay();
      unsure.current.delete(key);
      return true;
    } catch (error) {
      if (writeFailure(error) !== "failed") unsure.current.delete(key);
      const failed = failureNotice(error, "move");
      notify(failed);
      if (failed.kind === "conflict") await reread(failed);
      return false;
    }
  }
  /** What the extracted card writes (board-writes) share with this view. */
  const writeDeps: BoardWriteDeps = {
    transport,
    latest,
    pendingMove,
    unsure,
    writes,
    focusWanted,
    lastWrite,
    notify,
    commit,
    forget,
    queueWrite,
    replayUnsure,
    reread,
    taskCard,
    wrote,
  };
  /**
   * One Task moves to another status. The write carries the card's version (the board's, patched by an earlier
   * write of the card; read with get_task when the card has none) and a key that a retry of the same move reuses.
   * It waits in the card's queue behind an earlier write of the same card. A conflict reads the board again and
   * keeps the banner.
   * `shown` is a drag or arrow-key move: the card is drawn in its target column while the write is
   * pending, and goes back to its own column if the write is refused.
   */
  function move(card: WorkItemRecord, to: TaskStatusValue, shown = false) {
    const key = cardKey(card);
    // In the single layout the card keeps its place in its section while its Undo lasts (a card that stays somewhere
    // already keeps that place).
    const at = single ? (undos[key]?.at ?? card.status) : undefined;
    const index = Math.max(
      0,
      (at === undefined ? [] : shownOf(at)).findIndex(
        (item) => item.id === card.id,
      ),
    );
    if (shown) setPreview({ taskId: card.id, column: to });
    queueWrite(key, async () => {
      let base = taskCard(card.id, latest.current.page) ?? card;
      let replay: (() => Promise<void>) | undefined;
      try {
        if (!(await replayUnsure(key))) return;
        base = taskCard(card.id, latest.current.page) ?? card;
        // Already there (an earlier tap of this card got it there): nothing to write.
        if (base.status === to) return;
        const version =
          typeof base.version === "number"
            ? base.version
            : (await transport.getTask(card.id)).task.version;
        const signature = JSON.stringify([card.id, version, to]);
        const pendingKey = keyFor(pendingMove.current.get(key), signature);
        pendingMove.current.set(key, pendingKey);
        const from = base.status;
        // The whole end of a move, so a replay that succeeds later ends the same way: shown, focused, with its Undo.
        replay = async () => {
          const { task } = await transport.updateTask(
            card.id,
            version,
            { status: to },
            pendingKey.key,
          );
          pendingMove.current.delete(key);
          wrote(task);
          focusWanted.current = { kind: "card", id: card.id };
          // Done on a recurring Task: the server reopened it for its next date. Its Ångra puts the due date back.
          const before = base.due_at ?? null;
          const cycle = to === "completed" && isRecurringCycle(task, before);
          if (isTaskStatus(from))
            setUndos((all) => ({
              ...all,
              [key]: {
                key,
                taskId: card.id,
                from,
                to: task.status,
                version: task.version,
                at,
                index,
                ...(cycle
                  ? {
                      completed: true,
                      lastCompleted: { from: base.last_completed_at ?? null },
                      due: {
                        from: before,
                        label: recurringDoneText(t, task.due_at, new Date()),
                      },
                    }
                  : {}),
              },
            }));
        };
        await replay();
      } catch (error) {
        if (replay && writeFailure(error) === "failed")
          unsure.current.set(key, replay);
        const failed = failureNotice(error, "move");
        lastWrite.current = { kind: "move", card, to };
        notify(failed);
        if (failed.kind === "conflict") await reread(failed);
        return;
      } finally {
        // A later tap of this card has its own preview, which stays.
        setPreview((now) =>
          now?.taskId === card.id && now.column === to ? undefined : now,
        );
      }
    });
  }
  /** Undo of a status move (see board-writes). */
  function undoMove(entry: AgendaUndo) {
    undoMoveWrite(writeDeps, entry);
  }
  /** The column's Tasks in their order with versions, or undefined when the column is not whole on the board. */
  function completeColumn(
    status: TaskStatusValue,
    source: WorkBoardFrame = frame,
  ) {
    return wholeColumn(source, status);
  }
  /**
   * A drop inside one column. The order is written only for a complete column; an incomplete one
   * keeps its order and nothing is sent. The order is worked out when the write runs, against the column as the
   * writes before it left it, and the answer (the new versions and order) is on the board before the next write runs.
   * A refused order reads the board again, so the Tasks go back to the server's order, and shows the same notice
   * as a refused move. The key is the one a retry of the same order reuses.
   */
  function reorder(status: TaskStatusValue, taskId: string, to: ReorderTo) {
    if (!completeColumn(status)) return;
    const key = `reorder:${status}`;
    queueWrite(key, async () => {
      if (!(await replayUnsure(key))) return;
      const items = reorderedColumn(status, taskId, to, latest.current);
      if (!items) return;
      const signature = JSON.stringify([
        status,
        items.map((item) => [item.taskId, item.version]),
      ]);
      const pendingKey = keyFor(pendingReorder.current.get(key), signature);
      pendingReorder.current.set(key, pendingKey);
      const replay = async () => {
        const answer = await transport.reorderBoardColumn(
          status,
          items,
          pendingKey.key,
        );
        pendingReorder.current.delete(key);
        placedColumn(status, answer?.items ?? [], items);
      };
      try {
        await replay();
      } catch (error) {
        if (writeFailure(error) === "failed") unsure.current.set(key, replay);
        const failed = failureNotice(error, "move");
        lastWrite.current = { kind: "reorder", status, taskId, to };
        notify(failed);
        if (failed.kind === "conflict") await reread(failed);
      }
    });
  }
  /** A column order was written: the column shows the answer's order and versions at once (else the order it sent). */
  function placedColumn(
    status: TaskStatusValue,
    answer: WorkBoardPlacement[],
    sent: WorkBoardPlacementItem[],
  ) {
    writes.current += 1;
    commit({
      ...latest.current,
      page: withColumnPlaced(latest.current.page, status, answer, sent),
    });
  }
  /** The glyph of a card in the single layout: done, or open again when it is done. */
  function toggleDone(card: WorkItemRecord) {
    move(card, card.status === "completed" ? "todo" : "completed");
  }
  /** The check of a Step in the single layout (see board-writes). */
  function toggleStep(card: WorkItemRecord) {
    toggleStepWrite(writeDeps, card);
  }
  /** Flytta upp / Flytta ned: the Task takes the neighbouring place in its whole column. */
  function stepWithin(card: WorkItemRecord, direction: -1 | 1) {
    if (!isTaskStatus(card.status)) return;
    const items = completeColumn(card.status);
    const at = items?.findIndex((item) => item.taskId === card.id) ?? -1;
    if (!items || at === -1) return;
    const to = at + direction;
    if (to < 0 || to >= items.length) return;
    // The write is made the same way as a drop, a step from where the card stands when it runs; the card's
    // title takes focus when it is done.
    focusWanted.current = { kind: "more", id: card.id };
    reorder(card.status, card.id, { by: direction });
  }
  function retry(action: BoardAction) {
    const last = lastWrite.current;
    const lastKey =
      last?.kind === "move" || last?.kind === "step"
        ? cardKey(last.card)
        : last?.kind === "undo"
          ? last.entry.key
          : last
            ? `reorder:${last.status}`
            : undefined;
    // A write whose delivery is unknown is only replayed, never made twice.
    if (action === "move" && lastKey && unsure.current.has(lastKey))
      queueWrite(lastKey, async () => void (await replayUnsure(lastKey)));
    else if (action === "move" && last?.kind === "move")
      move(last.card, last.to);
    else if (action === "move" && last?.kind === "undo") undoMove(last.entry);
    else if (action === "move" && last?.kind === "step") toggleStep(last.card);
    else if (action === "move" && last?.kind === "reorder")
      reorder(last.status, last.taskId, last.to);
    else if (action === "more") loadMore();
    else reload();
  }
  return {
    taskCard,
    forget,
    move,
    undoMove,
    completeColumn,
    reorder,
    toggleDone,
    toggleStep,
    stepWithin,
    retry,
  };
}
