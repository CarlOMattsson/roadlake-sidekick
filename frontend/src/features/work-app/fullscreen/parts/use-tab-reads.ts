import { useCallback, useRef, useState } from "react";

import {
  definitionToFilters,
  namesSeveralPriorities,
} from "../../saved-views/saved-views";
import type { SavedViewTab } from "../../saved-views/saved-views";
import type {
  WorkSavedViewDefinition,
  WorkTransport,
} from "../../transport/transport";
import { useMounted } from "../../view/parts/use-mounted";
import type { WorkTab } from "../../shell/work-shell";
import {
  readTab,
  type PerTab,
  type TabEntries,
  type WorkTabFrame,
} from "./tab-data";

type Options = {
  transport: WorkTransport;
  /** Whether the host can answer the tool (WorkTransport.supportsTool). */
  offers: (name: string, args?: object) => boolean;
  /** The tab that is shown first, and its frame when the tool result gave one. */
  initialTab: WorkTab;
  firstFrame: WorkTabFrame | undefined;
  /** A saved view was opened in a tab: the caller restarts the tab's view and sets its notice. */
  onViewApplied: (tab: SavedViewTab, several: boolean, name: string) => void;
  /** A tab went back from its saved view to its own list. */
  onViewCleared: (tab: SavedViewTab) => void;
};

/**
 * The first read of each tab and the saved views that replace a tab's frame. Every tab but the first is read the first
 * time it is opened and kept, so switching tabs is local. A late answer never writes into a gone view, and never
 * replaces a saved view that was opened while the first read was still on its way.
 */
export function useTabReads({
  transport,
  offers,
  initialTab,
  firstFrame,
  onViewApplied,
  onViewCleared,
}: Options) {
  // False after unmount, so a late answer does not write into a gone view.
  const aliveRef = useMounted();
  const [entries, setEntries] = useState<TabEntries>(() =>
    firstFrame ? { [initialTab]: { status: "ready", frame: firstFrame } } : {},
  );
  // Tabs whose first read has started, or that already hold the first frame. A failed tab is
  // removed again by retry only.
  const started = useRef(new Set<WorkTab>(firstFrame ? [initialTab] : []));
  // One order for every read and every invalidation: a tab is up to date when the read that gave its frame started
  // after the tab was last marked out of date (`readAt` > its stale mark).
  const order = useRef(0);
  const readAt = useRef<PerTab<number>>({});
  // Tabs that a saved view has shown. A first read still in flight for such a tab must not replace it.
  const viewApplied = useRef(new Set<WorkTab>());

  const load = useCallback(
    (tab: WorkTab) => {
      if (started.current.has(tab)) return;
      started.current.add(tab);
      // A read again after a failure keeps the notice, its button saying "Försöker igen…" (designsystem §3).
      setEntries((current) => {
        const entry = current[tab];
        return {
          ...current,
          [tab]:
            entry?.status === "error"
              ? { ...entry, retrying: true }
              : { status: "loading" },
        };
      });
      const startedAt = (order.current += 1);
      readTab(
        transport,
        tab,
        offers("get_work_hierarchy", { include_tasks: true }),
      ).then(
        (frame) => {
          if (aliveRef.current && !viewApplied.current.has(tab)) {
            readAt.current[tab] = startedAt;
            setEntries((current) => ({
              ...current,
              [tab]: { status: "ready", frame },
            }));
          }
        },
        (cause: unknown) => {
          if (aliveRef.current && !viewApplied.current.has(tab))
            setEntries((current) => ({
              ...current,
              [tab]: { status: "error", cause },
            }));
        },
      );
    },
    [transport, offers, aliveRef],
  );
  const retry = useCallback(
    (tab: WorkTab) => {
      started.current.delete(tab);
      load(tab);
    },
    [load],
  );

  /**
   * Opens a saved view in the agenda or the board: reads its first page with the view's filters and
   * shows it in place of the tab's frame. The old view stays when the read fails. Resolves whether
   * the tab shows the view now.
   */
  const applyView = useCallback(
    async (
      tab: SavedViewTab,
      definition: WorkSavedViewDefinition,
      name: string,
    ): Promise<boolean> => {
      const filters = definitionToFilters(definition);
      const startedAt = (order.current += 1);
      try {
        const frame: WorkTabFrame =
          tab === "agenda"
            ? {
                kind: "agenda",
                filters,
                page: await transport.getWorkAgenda(filters),
              }
            : {
                kind: "board",
                filters,
                page: await transport.getWorkBoard(filters),
              };
        if (!aliveRef.current) return false;
        viewApplied.current.add(tab);
        readAt.current[tab] = startedAt;
        setEntries((current) => ({
          ...current,
          [tab]: { status: "ready", frame },
        }));
        onViewApplied(tab, namesSeveralPriorities(definition), name);
        return true;
      } catch {
        return false;
      }
    },
    [transport, aliveRef, onViewApplied],
  );

  /**
   * Goes back from a saved view to the tab's own list: reads the tab again without filters. The view stays when the
   * read fails. Resolves whether the tab shows its own list now.
   */
  const clearView = useCallback(
    async (tab: SavedViewTab): Promise<boolean> => {
      const startedAt = (order.current += 1);
      try {
        const frame = await readTab(transport, tab, false);
        if (!aliveRef.current) return false;
        viewApplied.current.delete(tab);
        readAt.current[tab] = startedAt;
        setEntries((current) => ({
          ...current,
          [tab]: { status: "ready", frame },
        }));
        onViewCleared(tab);
        return true;
      } catch {
        return false;
      }
    },
    [transport, aliveRef, onViewCleared],
  );

  return {
    entries,
    startedRef: started,
    orderRef: order,
    readAtRef: readAt,
    load,
    retry,
    applyView,
    clearView,
  };
}
