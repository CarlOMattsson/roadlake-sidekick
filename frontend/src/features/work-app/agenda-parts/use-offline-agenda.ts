import { useEffect, useState } from "react";
import type { WorkAgendaPage, WorkTransport } from "../transport";

const NONE: ReadonlySet<string> = new Set();

/**
 * The phone's offline state of an agenda page (the mobile app only; in Claude both are empty): when the page is the
 * offline copy, the moment that copy was read (null for a page the server answered), and the ids of the Tasks whose tick
 * waits in the phone's outbox (the widget's ticks too), lower-cased. The outbox is read again with every new page and
 * every time a run of it ends.
 */
export function useOfflineAgenda(
  transport: WorkTransport,
  page: WorkAgendaPage,
): { copiedAt: number | null; sending: ReadonlySet<string> } {
  const offline = transport.offline;
  const copiedAt = offline?.readAt(page) ?? null;
  const [sending, setSending] = useState<ReadonlySet<string>>(NONE);
  const [runs, setRuns] = useState(0);
  useEffect(
    () => offline?.onQueueChanged(() => setRuns((run) => run + 1)),
    [offline],
  );
  useEffect(() => {
    const read = offline?.queuedCompletions;
    if (!read) return undefined;
    let live = true;
    read()
      .then((ids) => {
        if (live) setSending(ids.size > 0 ? ids : NONE);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [offline, page, runs]);
  return { copiedAt, sending };
}
