import { useEffect } from "react";

import type { OfflineSupport } from "@/features/mcp-apps/room-types";

/**
 * Calls `onSent` when records that waited in the phone's outbox (a Task, Project or journal entry written or edited
 * without a network) have left it, because the server took them or refused them: the rooms then read again and replace
 * the stand-ins with the stored records. Reads the waiting ids at mount and whenever the outbox changes.
 */
export function useSentRefresh(
  offline:
    Pick<OfflineSupport, "queuedRecordIds" | "onQueueChanged"> | undefined,
  onSent: () => void,
): void {
  useEffect(() => {
    const read = offline?.queuedRecordIds;
    if (!offline || !read) return undefined;
    let live = true;
    let before: ReadonlySet<string> = new Set();
    const run = () =>
      read()
        .then((now) => {
          if (!live) return;
          const sent = [...before].some((id) => !now.has(id));
          before = now;
          if (sent) onSent();
        })
        .catch(() => undefined);
    void run();
    const stop = offline.onQueueChanged(() => void run());
    return () => {
      live = false;
      stop();
    };
  }, [offline, onSent]);
}
