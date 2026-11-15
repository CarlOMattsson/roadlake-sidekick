import { useEffect, useState } from "react";
import type { WorkTransport } from "../transport/transport";

const NONE: ReadonlySet<string> = new Set();

/**
 * The ids (lower case) of the records with a write still waiting in the phone's outbox: a Task or Project that was
 * edited, and the stand-in of a Task that was made, without a network. Read again whenever `readOn` changes (the page
 * or record the caller shows) and every time a run of the outbox ends. Empty in Claude, which has no outbox.
 */
export function useQueuedRecords(
  transport: WorkTransport,
  readOn: unknown,
): ReadonlySet<string> {
  const offline = transport.offline;
  const [ids, setIds] = useState<ReadonlySet<string>>(NONE);
  const [runs, setRuns] = useState(0);
  useEffect(
    () => offline?.onQueueChanged(() => setRuns((run) => run + 1)),
    [offline],
  );
  useEffect(() => {
    const read = offline?.queuedRecordIds;
    if (!read) return undefined;
    let live = true;
    read()
      .then((next) => {
        if (live) setIds(next.size > 0 ? next : NONE);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [offline, readOn, runs]);
  return ids;
}

/** A stand-in id (`queued-…`): the Task was made offline and the server does not know it yet, so nothing can be written against it. */
export function isStandIn(id: string): boolean {
  return id.toLowerCase().startsWith("queued-");
}
