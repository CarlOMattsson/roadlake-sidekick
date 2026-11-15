import { useEffect, useState } from "react";
import type { JournalTransport } from "./transport";

const NONE: ReadonlySet<string> = new Set();

/** The phone gives a note it has not sent yet an id with this prefix; the server does not know it. */
const STAND_IN_PREFIX = "queued-";

/** True for the id of a note that still waits in the phone's outbox: it cannot be opened on the server yet. */
export function isStandInId(id: string): boolean {
  return id.startsWith(STAND_IN_PREFIX);
}

/**
 * The ids (lower case) of the entries with a write still waiting in the phone's outbox: a new note and an edited one.
 * Read once, and again every time a run of the outbox ends. Empty where the host has no outbox (Claude).
 */
export function useQueuedRecords(
  transport: Pick<JournalTransport, "offline">,
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
      .then((queued) => {
        if (live) setIds(queued.size > 0 ? queued : NONE);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [offline, runs]);
  return ids;
}

/** Whether the entry with this id waits in the outbox. */
export function isQueued(ids: ReadonlySet<string>, id: string): boolean {
  return ids.has(id.toLowerCase());
}
