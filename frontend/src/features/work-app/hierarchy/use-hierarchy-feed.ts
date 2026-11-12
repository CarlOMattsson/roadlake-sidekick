import { useEffect, useRef, useState } from "react";
import { toolOffered } from "../../mcp-apps/tool-support";
import { mergeHierarchyPage } from "./hierarchy-tree";
import type { WorkHierarchyFrame, WorkTransport } from "../transport/transport";

/**
 * Keeps the Projects list fresh in place, the way the agenda does: one read at mount when a page opened from it saved
 * something (`stale`) or when the frame came without its Tasks (Claude opened the tab without include_tasks, so the
 * counts would be missing), and one read for each new `refreshKey`. Each read asks for the Tasks when the host answers
 * include_tasks (the phone does not), and the answer replaces the frame through `onChange`. A failed read keeps what is
 * shown; the next request tries again. A request that arrives while a read is on its way is coalesced into one read
 * after it.
 */
export function useHierarchyRefresh({
  frame,
  transport,
  onChange,
  stale,
  onRead,
  refreshKey,
}: {
  frame: WorkHierarchyFrame;
  transport?: WorkTransport;
  onChange?: (next: WorkHierarchyFrame) => void;
  stale: boolean;
  onRead?: () => void;
  refreshKey?: number;
}) {
  const withTasks =
    transport !== undefined &&
    toolOffered(transport, "get_work_hierarchy", { include_tasks: true });
  const reading = useRef(false);
  // A request that comes while a read is on its way is not dropped: one read follows the one in flight (the way the
  // board and the agenda read again), however many requests came meanwhile.
  const again = useRef(false);
  const alive = useRef(true);
  const read = useRef<() => void>(() => undefined);
  useEffect(() => {
    read.current = () => {
      if (!transport || !onChange) return;
      if (reading.current) {
        again.current = true;
        return;
      }
      reading.current = true;
      const finish = () => {
        reading.current = false;
        if (again.current && alive.current) {
          again.current = false;
          read.current();
        }
      };
      transport.getWorkHierarchy({ includeTasks: withTasks }).then((next) => {
        if (alive.current) {
          onChange(next);
          onRead?.();
        }
        finish();
      }, finish);
    };
  });
  const atMount = useRef(stale || (withTasks && frame.tasks === undefined));
  useEffect(() => {
    alive.current = true;
    if (atMount.current) read.current();
    return () => {
      alive.current = false;
    };
  }, []);
  const seenKey = useRef(refreshKey);
  useEffect(() => {
    if (refreshKey === undefined || refreshKey === seenKey.current) return;
    seenKey.current = refreshKey;
    read.current();
  }, [refreshKey]);
}

type MorePhase = "idle" | "busy" | "failed";

/**
 * "Show more" for the list: reads the page after the frame's `next_cursor` (with Tasks when the host answers them) and
 * hands the two pages as one frame to `onChange`. A refresh that arrives meanwhile starts the list over, so a page
 * still on its way is dropped.
 */
export function useHierarchyMore({
  frame,
  transport,
  onChange,
  refreshKey,
}: {
  frame: WorkHierarchyFrame;
  transport?: WorkTransport;
  onChange?: (next: WorkHierarchyFrame) => void;
  refreshKey?: number;
}) {
  // The phase belongs to the refreshKey it started under: a refresh that arrives meanwhile starts the list over, so a
  // page still on its way is dropped and the phase reads as idle.
  const [state, setState] = useState<{ key?: number; phase: MorePhase }>({
    phase: "idle",
  });
  const more = state.key === refreshKey ? state.phase : "idle";
  const latest = useRef({ frame, refreshKey });
  useEffect(() => {
    latest.current = { frame, refreshKey };
  });
  const withTasks =
    transport !== undefined &&
    toolOffered(transport, "get_work_hierarchy", { include_tasks: true });
  const cursor = frame.next_cursor;
  function loadMore() {
    if (!transport || !onChange || !cursor || more === "busy") return;
    const key = refreshKey;
    setState({ key, phase: "busy" });
    transport.getWorkHierarchy({ includeTasks: withTasks, cursor }).then(
      (page) => {
        if (latest.current.refreshKey !== key) return;
        onChange(mergeHierarchyPage(latest.current.frame, page));
        setState({ key, phase: "idle" });
      },
      () => {
        if (latest.current.refreshKey === key)
          setState({ key, phase: "failed" });
      },
    );
  }
  return { more, loadMore, offered: transport && onChange && cursor };
}
