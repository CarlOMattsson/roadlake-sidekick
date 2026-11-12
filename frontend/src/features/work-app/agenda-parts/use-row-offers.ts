import { useToolSupport } from "../../mcp-apps/tool-support";
import {
  TASK_STATUSES,
  type TaskStatusValue,
  type WorkItemRecord,
  type WorkTransport,
} from "../transport";

/**
 * What the host can write is offered, and nothing else (RoomTransport.supportsTool/supportsCall): the mobile app answers
 * update_task only with the completing change, so its rows can be ticked done but get no other status, no date
 * choices and no Ångra, and there is no "Flytta försenade".
 */
export function useRowOffers(transport: WorkTransport) {
  const offers = useToolSupport(transport);
  // `from` is the status the Task has now: a host that reopens only a completed Task answers "todo" by it.
  const statusOffered = (status: TaskStatusValue, from?: string) =>
    offers("update_task", {
      changes: { status },
      ...(from !== undefined ? { from_status: from } : {}),
    });
  const dueOffered = offers("update_task", { changes: { due_at: null } });
  const rescheduleOffered = offers("reschedule_tasks");
  /** The quick choices of a row: a status other than its own, or the due date. None: no long press, no hint. */
  const rowHasChoices = (item: WorkItemRecord) =>
    item.kind === "task" &&
    (dueOffered ||
      TASK_STATUSES.some(
        (value) => value !== item.status && statusOffered(value, item.status),
      ));
  return {
    offers,
    statusOffered,
    dueOffered,
    rescheduleOffered,
    rowHasChoices,
  };
}

/** What the host offers the rows: see `useRowOffers`. */
export type RowOffers = ReturnType<typeof useRowOffers>;
