import { useRef, useState, type RefObject } from "react";

import { keyFor, type PendingKey } from "../../mcp-apps/idempotency";
import type { useReceipt } from "../../mcp-apps/ui/receipt";
import type { HomeLabels } from "./labels";
import type { StartTodayRow } from "./model";
import { withId, withoutId } from "./sets";
import type { HomeTransport } from "./transport";

export type TaskDoneState = ReturnType<typeof useTaskDone>;

/**
 * The ring of a task of today. Ticking sends update_task with the status "completed" against the row's version, once
 * per press (a retry of the same press reuses its idempotency key). The row leaves "Idag" at once, the count with it,
 * and the receipt bar offers Ångra, which writes "todo" back against the version the tick left. A recurring task
 * comes back from the server open again with its next date: the row leaves the same way, and the receipt has no
 * Ångra, because that would have to put the earlier completion on record back too and this page does not hold it.
 * Where the host cannot write the tick the rows have no ring; where it cannot write it back the receipt has no Ångra.
 */
export function useTaskDone({
  api,
  t,
  receipt,
  reload,
  titleRef,
}: {
  api: HomeTransport;
  t: HomeLabels;
  receipt: ReturnType<typeof useReceipt>;
  reload: () => void;
  titleRef: RefObject<HTMLHeadingElement | null>;
}) {
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set());
  const [busy, setBusy] = useState<ReadonlySet<string>>(new Set());
  const keys = useRef(new Map<string, PendingKey>());
  const running = useRef(new Set<string>());

  /** One write of a row: `send` is the tool call; the signature keeps its key across a retry of the same press. */
  const write = <Reply>(
    id: string,
    signature: string,
    send: (key: string) => Promise<Reply>,
    done: (reply: Reply) => void,
    fail: () => void,
  ) => {
    if (running.current.has(id)) return;
    const pending = keyFor(keys.current.get(signature), signature);
    keys.current.set(signature, pending);
    running.current.add(id);
    setBusy((now) => withId(now, id));
    send(pending.key).then(
      (reply) => {
        running.current.delete(id);
        keys.current.delete(signature);
        setBusy((now) => withoutId(now, id));
        done(reply);
      },
      () => {
        running.current.delete(id);
        setBusy((now) => withoutId(now, id));
        fail();
      },
    );
  };

  const reopen = (row: StartTodayRow, version: number) => {
    const reopenTask = api.reopen;
    if (!reopenTask) return;
    write(
      row.id,
      `${row.id}:reopen:${version}`,
      (key) => reopenTask(row.id, version, key),
      () => {
        setHidden((now) => withoutId(now, row.id));
        receipt.show({ message: t.taskReopened(row.title) });
        reload();
      },
      () => receipt.show({ message: t.reopenFailed }),
    );
  };

  const complete = (row: StartTodayRow) => {
    const completeTask = api.complete;
    if (!completeTask) return;
    write(
      row.id,
      `${row.id}:complete:${row.version}`,
      (key) => completeTask(row.id, row.version, key),
      (reply) => {
        const { task } = reply;
        setHidden((now) => withId(now, row.id));
        // The row leaves: the focus goes to the page's title rather than to nothing.
        titleRef.current?.focus();
        const back =
          api.reopen && task.status === "completed"
            ? { label: t.undo, onUndo: () => reopen(row, task.version) }
            : undefined;
        receipt.show({
          message: t.taskDone(row.title),
          ...(back ? { undo: back } : {}),
        });
        reload();
      },
      () => {
        receipt.show({ message: t.completeFailed });
        // The row's version may be stale: read again so the next press uses the server's.
        reload();
      },
    );
  };

  return {
    hidden,
    busy,
    complete: api.complete ? complete : undefined,
  };
}
