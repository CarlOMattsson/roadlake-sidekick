import { useSyncExternalStore } from "react";

/** The frame width from which a row has room for more than two tags (48rem at a 16 px root). */
const WIDE_FRAME_PX = 768;

function subscribe(onChange: () => void): () => void {
  window.addEventListener("resize", onChange);
  return () => window.removeEventListener("resize", onChange);
}

/**
 * True when the app's frame is wide (a desktop host), where a list row can name more of an entry's tags before it
 * counts the rest. The app runs in its own frame, so the window width is the frame width.
 */
export function useWideFrame(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => window.innerWidth >= WIDE_FRAME_PX,
    () => false,
  );
}
