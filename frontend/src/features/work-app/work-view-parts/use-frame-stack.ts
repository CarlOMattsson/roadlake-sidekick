import { useEffect, useReducer, useRef } from "react";
import type { RoomTarget } from "../../mcp-apps/room-types";
import type { WorkFrame } from "../transport";
import {
  createFrameStackState,
  frameStackReducer,
} from "./frame-stack-reducer";
import { listScrollKey, routeOfFrame } from "./frame-routing";

/**
 * The navigation stack of WorkView: the frames, the session counter that remounts them after a reset,
 * the push/pop counter that moves focus, the scroll memory of the lists, and the stale flag.
 */
export function useFrameStack({
  initial,
  onStackDepth,
  onRoute,
}: {
  initial?: WorkFrame;
  /** Called with the depth of the navigation stack whenever it changes. */
  onStackDepth?: (depth: number) => void;
  /** Given by a host that routes: opening a Task, Project, Process or Contact asks the shell instead of pushing. */
  onRoute?: (target: RoomTarget) => void;
}) {
  const [state, dispatch] = useReducer(
    frameStackReducer,
    initial,
    createFrameStackState,
  );
  // The page scroll of each list when a Task or Project is opened from it, by session and list key.
  const scrollMemo = useRef(new Map<string, number>());
  // The scroll to put back once the list that Back returns to has rendered.
  const scrollRestore = useRef<number | undefined>(undefined);
  // A new initial (a new tool result) replaces the whole navigation stack. Only a change dispatches:
  // a render-phase dispatch renders again.
  if (initial !== state.seen) dispatch({ type: "reset", initial });
  const { stack, session, moves, stale, editContactId } = state;
  const top = stack.at(-1);
  useEffect(() => {
    onStackDepth?.(stack.length);
  }, [stack.length, onStackDepth]);
  function push(frame: WorkFrame, label?: string, edit = false) {
    const target = onRoute ? routeOfFrame(frame, label, top) : undefined;
    if (target) {
      onRoute?.(target);
      return;
    }
    const key = listScrollKey(top);
    if (key !== undefined)
      scrollMemo.current.set(`${session}:${key}`, window.scrollY);
    dispatch({ type: "push", frame, edit });
    // Reported in the same event as the push, not in an effect: the shell then hides the agenda's toolbar
    // in the same render, so no scroll is put back while the page is still a row shorter or taller.
    onStackDepth?.(stack.length + 1);
  }
  const open = (frame: WorkFrame, label?: string) => push(frame, label);
  const openContact = (id: string, edit: boolean) =>
    push({ kind: "contact", id }, undefined, edit);
  /** A board or agenda frame that re-read its page replaces itself, wherever it sits in the stack. */
  function replaceFrame<F extends WorkFrame>(before: F, after: F) {
    dispatch({ type: "replace", before, after });
  }
  function back() {
    const key = listScrollKey(stack.at(-2));
    scrollRestore.current =
      key === undefined
        ? undefined
        : scrollMemo.current.get(`${session}:${key}`);
    dispatch({ type: "back" });
    // Same render as the pop: the toolbar is shown again before the restored scroll is applied below.
    onStackDepth?.(Math.max(1, stack.length - 1));
  }
  // Runs after the list's own focus effect (children run first), so the restored scroll is not undone.
  useEffect(() => {
    const y = scrollRestore.current;
    if (y === undefined) return;
    scrollRestore.current = undefined;
    window.scrollTo(0, y);
  });
  return {
    stack,
    top,
    session,
    moves,
    stale,
    setStale: (next: boolean) => dispatch({ type: "stale", stale: next }),
    editContactId,
    open,
    openContact,
    replaceFrame,
    back,
  };
}
