import { useEffect, useState, type RefObject } from "react";

/** A board narrower than this (px) shows one status at a time; see `layout` of BoardView. */
export const SINGLE_LAYOUT_MAX_WIDTH = 640;
/** The board's layout: every status side by side, or one list grouped in status sections (a phone). */
export type BoardLayout = "columns" | "single";
/** The layout the latest board measured; the next board to mount starts from it. */
let lastMeasuredLayout: BoardLayout = "columns";

/**
 * The layout the board shows: the given one, or for "auto" the board's own width (the measured width is the only
 * source, CSS reads data-layout).
 */
export function useBoardLayout(
  layoutProp: "auto" | BoardLayout,
  root: RefObject<HTMLElement | null>,
): BoardLayout {
  // Starts as the layout the last board measured: a board that mounts again (Back from a card) must not
  // show one frame of columns, shorter than the single list, while the scroll is put back (it would clamp).
  const [measured, setMeasured] = useState<BoardLayout>(lastMeasuredLayout);
  useEffect(() => {
    const element = root.current;
    if (
      layoutProp !== "auto" ||
      !element ||
      typeof ResizeObserver === "undefined"
    )
      return undefined;
    const measureWidth = () => {
      const { width } = element.getBoundingClientRect();
      // A hidden pane (a room that was left) measures 0: keep the layout it had, or the page would shrink
      // and lose its scroll position before the room is shown again.
      if (width <= 0) return;
      lastMeasuredLayout =
        width < SINGLE_LAYOUT_MAX_WIDTH ? "single" : "columns";
      setMeasured(lastMeasuredLayout);
    };
    // The observer reports once when it starts observing, so no separate first measurement is made.
    const observer = new ResizeObserver(measureWidth);
    observer.observe(element);
    return () => observer.disconnect();
  }, [layoutProp, root]);
  return layoutProp === "auto" ? measured : layoutProp;
}

/** Whether columns lie hidden beyond the row's right edge: measured on scroll and on resize. */
export function useColumnsOverflow(
  row: RefObject<HTMLElement | null>,
): boolean {
  const [columnsMore, setColumnsMore] = useState(false);
  useEffect(() => {
    const element = row.current;
    if (!element) return undefined;
    const measure = () =>
      setColumnsMore(
        element.scrollLeft + element.clientWidth < element.scrollWidth - 1,
      );
    measure();
    element.addEventListener("scroll", measure, { passive: true });
    const observer =
      typeof ResizeObserver === "undefined"
        ? undefined
        : new ResizeObserver(measure);
    observer?.observe(element);
    return () => {
      element.removeEventListener("scroll", measure);
      observer?.disconnect();
    };
  }, [row]);
  return columnsMore;
}
