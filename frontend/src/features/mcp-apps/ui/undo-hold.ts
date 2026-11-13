import { useEffect, useRef, useState } from "react";
import "./undo.css";

/**
 * The time to undo (designsystem §3 Ångra): a change can be undone from its own row for `UNDO_MS`. It is the same in
 * every room, so a row that offers Ångra counts down the same fifteen seconds wherever it stands.
 */
export const UNDO_MS = 15000;

/** The handlers that pause the countdown while the pointer is over the element or focus is in it. */
export type UndoHoldHandlers = {
  onPointerEnter: () => void;
  onPointerLeave: () => void;
  onFocus: () => void;
  onBlur: () => void;
};

/**
 * The countdown of one Ångra. While `running` it counts down `UNDO_MS` and then calls `onExpire`; the time stops while
 * the pointer is over the element that gets `handlers` or focus is in it, and runs on with the time left when both
 * leave. When `running` ends the time starts over. `held` says the countdown stands still: put it on the element as
 * `data-held` so the time line under the button (`.sk-undo-time`, undo.css) stands still too.
 */
export function useUndoHold(running: boolean, onExpire: () => void) {
  const [pointer, setPointer] = useState(false);
  const [focused, setFocused] = useState(false);
  const held = pointer || focused;
  const left = useRef(UNDO_MS);
  // The latest callback, so a new function on every render does not restart the countdown.
  const latest = useRef(onExpire);
  useEffect(() => {
    latest.current = onExpire;
  });
  useEffect(() => {
    if (!running) {
      left.current = UNDO_MS;
      return undefined;
    }
    if (held) return undefined;
    const since = Date.now();
    const timer = setTimeout(() => latest.current(), left.current);
    return () => {
      clearTimeout(timer);
      left.current -= Date.now() - since;
    };
  }, [running, held]);
  const handlers: UndoHoldHandlers = {
    onPointerEnter: () => setPointer(true),
    onPointerLeave: () => setPointer(false),
    onFocus: () => setFocused(true),
    onBlur: () => setFocused(false),
  };
  return { held, handlers };
}
