import { useRef } from "react";
import { keyFor } from "../../../mcp-apps/idempotency";
import { ownerEndOfDay, workDate } from "../../../mcp-apps/ui/due";
import type { AgendaUndo } from "../agenda-undo";
import { failureNotice } from "../../board/board";
import { isCompleteDate } from "../../shared/fields";
import type { WorkLabels } from "../../shared/labels";
import {
  isTaskStatus,
  writeFailure,
  type TaskStatusValue,
  type WorkItemRecord,
  type WorkTask,
  type WorkTaskChanges,
  type WorkTransport,
} from "../../transport/transport";
import { cardKey } from "../../shared/work-items";
import { sameDue } from "./agenda-helpers";
import type { AgendaSession } from "./use-agenda-session";
import type { RowState } from "./use-row-state";

/**
 * The writes of one row: a status change, a due-date move and their Undo. Each goes in its row's queue, against the
 * version the row holds when the write runs, with one key per attempt; a refused write shows the board's notice and a
 * network failure offers "Try again" with the same key.
 */
export function useRowWrites({
  transport,
  labels: t,
  now,
  session,
  rows,
  mounted,
  keepFocus,
  closeMenu,
}: {
  transport: WorkTransport;
  labels: WorkLabels;
  now: Date;
  session: AgendaSession;
  rows: RowState;
  mounted: { readonly current: boolean };
  keepFocus: (key: string) => void;
  /** Closes the quick choices of the row menu. */
  closeMenu: () => void;
}) {
  const { reading, pending, armRetry, setNotice, enqueueRow } = session;
  // A change by row whose delivery is unknown (no answer): the server may have applied it. The row's next write
  // replays it with its own key first and shows its answer, so the next change is judged against what the server holds.
  const unsure = useRef(new Map<string, { replay: () => Promise<void> }>());

  /**
   * One change against the version the row holds when the write runs (read with get_task when it has none). The write
   * goes in its row's queue: a tap while the row's earlier write runs waits behind it and uses the version that write
   * left. The change leaves an Undo line on its row, whichever control made it. A refused write shows the board's
   * notice; a network failure offers "Try again" with the same key. `dueLabel` is set for a due-date move: its Undo
   * line names the move, and Undo writes the old due date back. `triage` marks the row as changed by a triage button
   * once the change is done. `changes` may be a function of the row as it is when the write runs.
   */
  function send(
    record: WorkItemRecord,
    changes: WorkTaskChanges | ((item: WorkItemRecord) => WorkTaskChanges),
    dueLabel?: string,
    triage = false,
  ) {
    // A bulk write or a read in progress owns the whole list: a key press meanwhile is not queued.
    if (reading.current) return;
    const key = cardKey(record);
    keepFocus(key);
    const due = dueLabel !== undefined;
    setNotice(undefined);
    enqueueRow(key, async () => {
      if (!(await settleUnsure(key))) return;
      const item = rows.latest(record);
      const wanted = typeof changes === "function" ? changes(item) : changes;
      let replay: (() => Promise<void>) | undefined;
      try {
        const version =
          item.version ?? (await transport.getTask(item.id)).task.version;
        const signature = JSON.stringify([item.id, version, wanted]);
        const attempt = keyFor(pending.current.get(key), signature);
        pending.current.set(key, attempt);
        const done = (task: WorkTask) => {
          pending.current.delete(key);
          unsure.current.delete(key);
          if (!mounted.current) return;
          // Read before the override takes the row out of `left`: Undo puts it back there.
          const hadLeft = rows.hasLeftNow(key);
          rows.applyOverride(key, task, due);
          if (triage) rows.markTriaged(key, true);
          // A change that went through closes its quick choices; its Undo takes the meta line.
          closeMenu();
          if (due || isTaskStatus(item.status)) {
            const entry: AgendaUndo = {
              key,
              taskId: item.id,
              from: item.status,
              to: task.status,
              version: task.version,
              completed: wanted.status === "completed",
              ...(hadLeft ? { hadLeft: true } : {}),
              ...(due
                ? { due: { from: item.due_at ?? null, label: dueLabel } }
                : {}),
              // Done on a recurring Task: the server records the completion; Undo puts the earlier record back.
              ...(wanted.status === "completed" && item.recurrence != null
                ? { lastCompleted: { from: item.last_completed_at ?? null } }
                : {}),
            };
            rows.setUndo(key, entry);
          }
        };
        replay = async () =>
          done(
            (await transport.updateTask(item.id, version, wanted, attempt.key))
              .task,
          );
        await replay();
      } catch (error) {
        if (writeFailure(error) !== "failed") pending.current.delete(key);
        else if (replay) unsure.current.set(key, { replay });
        if (!mounted.current) return;
        // "Try again" repeats the write that failed last: the unsure one is only replayed, never made twice.
        armRetry(() =>
          unsure.current.has(key)
            ? enqueueRow(key, async () => void (await settleUnsure(key)))
            : send(record, changes, dueLabel, triage),
        );
        setNotice(failureNotice(error, "move"));
      }
    });
  }
  /** Replays the row's unsure change, if any, and shows its answer; false when it fails again (the notice says so). */
  async function settleUnsure(key: string): Promise<boolean> {
    const earlier = unsure.current.get(key);
    if (!earlier) return true;
    try {
      await earlier.replay();
      // The change the notice told about went through after all.
      if (mounted.current) setNotice(undefined);
      return true;
    } catch (error) {
      if (writeFailure(error) !== "failed") {
        unsure.current.delete(key);
        pending.current.delete(key);
      }
      armRetry(() =>
        enqueueRow(key, async () => void (await settleUnsure(key))),
      );
      if (mounted.current) setNotice(failureNotice(error, "move"));
      return false;
    }
  }

  /** One status change: see `send`. */
  function write(record: WorkItemRecord, to: TaskStatusValue) {
    send(record, { status: to });
  }

  /** A triage move of an overdue Task's due date. Its Undo names the new date: "Flyttad till imorgon · Ångra". */
  function moveDue(record: WorkItemRecord, dueAt: string) {
    send(
      record,
      { due_at: dueAt },
      workDate(dueAt, now, t.dateLocale, { inline: true }),
      true,
    );
  }

  /** The ⋯ menu's "Choose …" date: the same move as the triage buttons, to 23:59 on the chosen day. */
  function moveDueTo(record: WorkItemRecord, day: string) {
    if (!isCompleteDate(day)) return;
    const dueAt = ownerEndOfDay(day);
    // The chosen day becomes the menu's chosen chip, and the date chip that took the pick may be redrawn: focus goes
    // back to a control that stays (the hidden menu button when it opened the menu, else the row's own), also when the
    // write itself is held back.
    keepFocus(cardKey(record));
    moveDue(record, dueAt);
  }

  function toggleDone(record: WorkItemRecord) {
    // The target is decided when the write runs: two taps are done, then open again.
    send(record, (item) => ({
      status: item.status === "completed" ? "todo" : "completed",
    }));
  }

  /**
   * Undo: the previous status or due date, written against the version the change left. It gets its
   * own key, so it never replays the change it reverts.
   */
  function undoWrite(entry: AgendaUndo) {
    const changes: WorkTaskChanges | undefined = entry.due
      ? {
          due_at: entry.due.from,
          ...(entry.lastCompleted
            ? { last_completed_at: entry.lastCompleted.from }
            : {}),
        }
      : isTaskStatus(entry.from)
        ? { status: entry.from }
        : undefined;
    if (!changes || reading.current) return;
    const due = entry.due !== undefined;
    const undoKey = `undo:${entry.key}`;
    keepFocus(entry.key);
    rows.forget(entry.key);
    // Undo closes the quick choices of its row, if they are still open.
    closeMenu();
    setNotice(undefined);
    enqueueRow(entry.key, async () => {
      // An earlier change of the row that got no answer is settled first, so Undo is judged against what the server holds.
      if (!(await settleUnsure(entry.key))) return;
      // After a write queued before it, the row's version is the one that write left.
      const version = rows.versionOf(entry.key) ?? entry.version;
      const signature = JSON.stringify([entry.taskId, version, changes]);
      const attempt = keyFor(pending.current.get(undoKey), signature);
      pending.current.set(undoKey, attempt);
      let answered = false;
      // Kept as the row's unsure change when no answer comes: the next write of the row replays Undo with its key first.
      const replay = async () => {
        const { task } = await transport.updateTask(
          entry.taskId,
          version,
          changes,
          attempt.key,
        );
        answered = true;
        pending.current.delete(undoKey);
        unsure.current.delete(entry.key);
        // The reply must show the value Undo asked for. Any other reply is a failure with
        // "Try again", not a silently restored row; the retry gets a new key.
        const restored = entry.due
          ? sameDue(task.due_at, entry.due.from)
          : task.status === entry.from;
        if (!restored) {
          throw new Error("undo not applied");
        }
        if (!mounted.current) return;
        rows.applyOverride(entry.key, task, due);
        // A row that had left its group for Klar idag, opened again and now done again, goes back there, not to its group.
        if (entry.hadLeft && task.status === "completed")
          rows.markLeft(entry.key);
        // The row is back as it was, so its triage buttons are on again, and no Undo of an older write is left.
        rows.markTriaged(entry.key, false);
        rows.forget(entry.key);
      };
      try {
        await replay();
      } catch (error) {
        if (writeFailure(error) !== "failed") pending.current.delete(undoKey);
        else if (!answered) unsure.current.set(entry.key, { replay });
        if (!mounted.current) return;
        // "Try again" repeats the Undo that failed last: an unsure one is only replayed, never made twice.
        armRetry(() =>
          unsure.current.has(entry.key)
            ? enqueueRow(
                entry.key,
                async () => void (await settleUnsure(entry.key)),
              )
            : undoWrite(entry),
        );
        setNotice(failureNotice(error, "move"));
      }
    });
  }

  return { send, write, toggleDone, moveDue, moveDueTo, undoWrite };
}

/** The writes of one row: see `useRowWrites`. */
export type RowWrites = ReturnType<typeof useRowWrites>;
