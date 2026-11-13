import { useLayoutEffect, useRef, type RefObject } from "react";
import { menuButtonOf } from "../../shared/row-menu";

/**
 * A done or moved row of Försenade sinks under the group's line, and Undo brings it back: React moves the row's
 * node, and the browser drops the focus that was in it. The row whose change is written remembers that focus was in
 * it (`keepFocus`); once it is gone, focus goes back to the same row's ring (or title), and the page does not scroll.
 */
export function useKeepFocus(root: RefObject<HTMLElement | null>) {
  const refocus = useRef<string | undefined>(undefined);
  function keepFocus(key: string) {
    const row = root.current?.querySelector(`[data-agenda-key="${key}"]`);
    if (row?.contains(document.activeElement)) refocus.current = key;
  }
  useLayoutEffect(() => {
    const key = refocus.current;
    if (!key) return;
    const row = root.current?.querySelector(`[data-agenda-key="${key}"]`);
    const active = document.activeElement;
    if (row && active && row.contains(active)) return;
    refocus.current = undefined;
    if (active && active !== document.body) return;
    // The hidden menu button first when it opened the menu, else the ring or the title.
    (
      menuButtonOf(row) ??
      row?.querySelector<HTMLElement>(
        "button.work-agenda-glyph, .work-agenda-body > button",
      )
    )?.focus({ preventScroll: true });
  });
  return keepFocus;
}
