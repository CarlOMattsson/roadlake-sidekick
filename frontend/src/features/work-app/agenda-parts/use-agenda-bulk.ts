import { useRef, useState } from "react";
import { keyFor, type PendingKey } from "../../mcp-apps/idempotency";
import { failureNotice } from "../board";
import {
  writeFailure,
  type WorkFilters,
  type WorkItemRecord,
  type WorkTaskChanges,
  type WorkTransport,
} from "../transport";
import { cardKey } from "../work-items";
import { remindAt } from "../waiting";
import type { AgendaSession } from "./use-agenda-session";
import type { RowState } from "./use-row-state";

/** How many Tasks one reschedule_tasks call takes at most. */
const RESCHEDULE_CHUNK = 20;

/**
 * The two writes that are not one status change: "Påminn" in the waiting view and "Flytta alla försenade till imorgon"
 * in the Overdue group.
 */
export function useAgendaBulk({
  transport,
  filters,
  now,
  session,
  rows,
  mounted,
}: {
  transport: WorkTransport;
  filters: WorkFilters;
  now: Date;
  session: AgendaSession;
  rows: RowState;
  mounted: { readonly current: boolean };
}) {
  const { reading, pending, retryWrite, setNotice, enqueueRow, run } = session;
  // Waiting view: the Tasks whose reminder this view set, by row key.
  const [reminded, setReminded] = useState<Record<string, boolean>>({});
  const remindedRef = useRef(new Set<string>());
  // The key of "Flytta alla försenade": the same group, unchanged, sends the same key again.
  const bulkPending = useRef<PendingKey | undefined>(undefined);

  /**
   * "Påminn" in the waiting view: sets the Task's follow-up time to 09:00 tomorrow with update_task, so
   * it comes back to the owner as a follow-up then. The key is kept for a retry of the same write.
   */
  function remind(record: WorkItemRecord) {
    if (reading.current) return;
    const key = cardKey(record);
    const changes: WorkTaskChanges = { follow_up_at: remindAt(now) };
    setNotice(undefined);
    enqueueRow(key, async () => {
      // A second tap queued behind a reminder that went through has nothing left to set.
      if (remindedRef.current.has(key)) return;
      try {
        const item = rows.latest(record);
        const version =
          item.version ?? (await transport.getTask(record.id)).task.version;
        const signature = JSON.stringify([record.id, version, changes]);
        const attempt = keyFor(pending.current.get(key), signature);
        pending.current.set(key, attempt);
        await transport.updateTask(record.id, version, changes, attempt.key);
        pending.current.delete(key);
        remindedRef.current.add(key);
        if (mounted.current) setReminded((all) => ({ ...all, [key]: true }));
      } catch (error) {
        if (writeFailure(error) !== "failed") pending.current.delete(key);
        if (!mounted.current) return;
        retryWrite.current = () => remind(record);
        setNotice(failureNotice(error, "move"));
      }
    });
  }

  /**
   * "Flytta alla försenade till imorgon": every open Task of the overdue group moves to 23:59 tomorrow
   * with reschedule_tasks, which takes 20 at most, so the group goes in chunks. Then the agenda is read
   * again, so the rows show the new dates. A refused or stale write shows the notice.
   */
  function moveAllOverdue(records: WorkItemRecord[]) {
    if (reading.current) return;
    const openRows = () =>
      records
        .map(rows.latest)
        .filter(
          (item) =>
            item.kind === "task" &&
            item.status !== "completed" &&
            !rows.isTriagedNow(cardKey(item)),
        );
    if (openRows().length === 0) return;
    run("move", async () => {
      try {
        // The rows' own writes have settled (run waits for them), so this is each row as it now stands.
        const open = openRows();
        if (open.length === 0) return;
        const targets = await Promise.all(
          open.map(async (item) => ({
            id: item.id,
            version:
              item.version ?? (await transport.getTask(item.id)).task.version,
          })),
        );
        const signature = JSON.stringify(
          targets.map((row) => [row.id, row.version]),
        );
        const attempt = keyFor(bulkPending.current, signature);
        bulkPending.current = attempt;
        for (let start = 0; start < targets.length; start += RESCHEDULE_CHUNK) {
          await transport.rescheduleTasks(
            targets.slice(start, start + RESCHEDULE_CHUNK).map((row) => ({
              taskId: row.id,
              version: row.version,
              when: "tomorrow" as const,
            })),
            `${attempt.key}-${start}`,
          );
        }
        bulkPending.current = undefined;
        session.showRead(await transport.getWorkAgenda(filters));
      } catch (error) {
        if (mounted.current) setNotice(failureNotice(error, "move"));
      }
    });
  }

  return { reminded, remind, moveAllOverdue };
}
