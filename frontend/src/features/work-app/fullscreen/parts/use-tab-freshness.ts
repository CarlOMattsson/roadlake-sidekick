import {
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
  type RefObject,
} from "react";

import type { WorkTransport } from "../../transport/transport";
import type { WorkTab } from "../../shell/work-shell";
import { initialRefreshState, refreshReducer } from "./refresh-reducer";
import { marking, TABS, type PerTab, type TabEntry } from "./tab-data";

type Options = {
  transport: WorkTransport;
  /** False while the room is hidden or covered; a hidden room reads nothing. */
  active: boolean;
  /** The To sort view covers the shell: nothing reads while it is open. */
  sorting: boolean;
  refreshKey: number | undefined;
  activeTab: WorkTab;
  activeEntry: TabEntry | undefined;
  /** From useTabReads: the tabs that were read, the shared order, and when each frame's read started. */
  startedRef: RefObject<Set<WorkTab>>;
  orderRef: RefObject<number>;
  readAtRef: RefObject<PerTab<number>>;
};

/**
 * Which tabs are out of date, and the transports that tell it. Each view writes through its own transport, so a write
 * marks the other tabs, never the one that made it (it shows the change itself); the To sort view marks every tab. The
 * shown tab that is out of date reads again in place (its view's refreshKey).
 */
export function useTabFreshness({
  transport,
  active,
  sorting,
  refreshKey,
  activeTab,
  activeEntry,
  startedRef,
  orderRef,
  readAtRef,
}: Options) {
  const [state, dispatch] = useReducer(refreshReducer, initialRefreshState);
  const staleAt = useRef<PerTab<number>>({});
  /** The tabs that were read are out of date from now; `except` is the one that holds the change itself. */
  const invalidate = useCallback(
    (except?: WorkTab) => {
      const at = (orderRef.current += 1);
      const marked = TABS.filter(
        (tab) => tab !== except && startedRef.current.has(tab),
      );
      for (const tab of marked) staleAt.current[tab] = at;
      dispatch({ type: "stale", tabs: marked });
    },
    [orderRef, startedRef],
  );
  const [wrote] = useState(() => new EventTarget());
  useEffect(() => {
    const onWrote = (event: Event) => {
      const origin = (event as CustomEvent<WorkTab | "all">).detail;
      invalidate(origin === "all" ? undefined : origin);
    };
    wrote.addEventListener("wrote", onWrote);
    return () => wrote.removeEventListener("wrote", onWrote);
  }, [wrote, invalidate]);
  const transports = useMemo(() => {
    const via = (origin: WorkTab | "all") =>
      marking(transport, () =>
        wrote.dispatchEvent(new CustomEvent("wrote", { detail: origin })),
      );
    return {
      agenda: via("agenda"),
      board: via("board"),
      hierarchy: via("hierarchy"),
      sorting: via("all"),
    };
  }, [transport, wrote]);
  // A new refreshKey: a write in another layer, or a minute hidden. Every tab is out of date, the shown one is read now.
  const seenKey = useRef(refreshKey ?? 0);
  useEffect(() => {
    if ((refreshKey ?? 0) === seenKey.current) return;
    seenKey.current = refreshKey ?? 0;
    invalidate();
  }, [refreshKey, invalidate]);

  // The mark stays while the tab's read is still on its way (a view that is not mounted yet cannot read again, and the
  // answer may be from before the write): it is cleared once the frame is there, and the tab reads again only when the
  // read that gave the frame started before the tab was marked.
  const reading =
    activeEntry?.status === "loading" ||
    (activeEntry?.status === "error" && activeEntry.retrying === true);
  const staleActive = state.stale[activeTab];
  useEffect(() => {
    if (!active || sorting || !staleActive || reading) return;
    const upToDate =
      activeEntry?.status === "ready" &&
      (readAtRef.current[activeTab] ?? 0) > (staleAt.current[activeTab] ?? 0);
    dispatch({ type: "consume", tab: activeTab, bump: !upToDate });
  }, [
    active,
    sorting,
    activeTab,
    staleActive,
    reading,
    activeEntry,
    readAtRef,
  ]);

  return { state, dispatch, invalidate, transports };
}
